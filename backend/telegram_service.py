"""
Combined Server для приложения Семейное Древо
Объединяет Face Recognition (server.py) и PDF Generation (pdf_server.py) на одном порту
БЕЗ ПОТЕРИ ФУНКЦИОНАЛЬНОСТИ
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import face_recognition
import numpy as np
import base64
import io
from PIL import Image
import os
import json
import logging
from datetime import datetime
import time
import pickle
from pathlib import Path

# Google Drive imports
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:
    GOOGLE_DRIVE_AVAILABLE = False
    logging.warning("Google Drive API не установлен. Используйте: pip install google-api-python-client google-auth-oauthlib")

# PDF imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def load_env_file(env_path):
    """Загружает .env без внешних зависимостей."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def env_int(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"Некорректное значение {name}={raw!r}, используется {default}")
        return default


def resolve_backend_path(path_value):
    path = Path(path_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


load_env_file(BASE_DIR / '.env')

API_HOST = os.environ.get('API_HOST', '127.0.0.1')
API_PORT = env_int('API_PORT', 5000)
PUBLIC_ORIGIN = os.environ.get('PUBLIC_ORIGIN', 'https://totalcode.indevs.in')
MAX_CONTENT_LENGTH_MB = env_int('MAX_CONTENT_LENGTH_MB', 10)
MAX_CONTENT_LENGTH_BYTES = MAX_CONTENT_LENGTH_MB * 1024 * 1024
CORS_ORIGINS = [
    PUBLIC_ORIGIN,
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:4173',
    'http://127.0.0.1:4173',
]

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH_BYTES
CORS(app, resources={r'/*': {'origins': CORS_ORIGINS}})


def make_response_json(data, status=200):
    """
    Создает JSON ответ с явным Content-Length.
    Это исправляет проблему chunked encoding через Cloudflare Tunnel.
    """
    response_data = json.dumps(data, ensure_ascii=False)
    return Response(
        response_data,
        status=status,
        mimetype='application/json',
        headers={'Content-Length': str(len(response_data.encode('utf-8')))}
    )


# ========================================
# MIDDLEWARE для решения проблемы с ngrok
# ========================================

@app.before_request
def log_request_info():
    """Логируем детали каждого входящего запроса для отладки"""
    logger.info(f"=== Входящий запрос ===")
    logger.info(f"Метод: {request.method}")
    logger.info(f"URL: {request.url}")
    logger.info(f"Path: {request.path}")
    logger.info(f"Headers: {dict(request.headers)}")
    if request.method == 'POST':
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Content-Length: {request.content_length}")

@app.after_request
def after_request(response):
    """Добавляем заголовки для правильной работы с ngrok"""
    # Отключаем буферизацию nginx/ngrok
    response.headers['X-Accel-Buffering'] = 'no'
    # Кэширование
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ========================================
# FACE RECOGNITION - Конфигурация
# ========================================
REFERENCE_PHOTOS_DIR = str(BASE_DIR / 'reference_photos')
UPLOADED_PHOTOS_DIR = str(BASE_DIR / 'uploaded_photos')
ENCODINGS_FILE = str(BASE_DIR / 'face_encodings.json')

os.makedirs(REFERENCE_PHOTOS_DIR, exist_ok=True)
os.makedirs(UPLOADED_PHOTOS_DIR, exist_ok=True)

face_encodings_db = {}

# ========================================
# CUDA / GPU Настройки
# ========================================
# Используем CNN модель для GPU ускорения (требуется dlib с CUDA)
# 'cnn' - использует GPU (CUDA), более точный но требует GPU
# 'hog' - использует CPU, быстрее на CPU но менее точный
USE_CUDA = True  # Отключено для скорости (HOG быстрее на CPU)
FACE_MODEL = 'cnn' if USE_CUDA else 'hog'

# Количество раз для повышения разрешения при поиске лиц (0 = без увеличения)
# Увеличение замедляет работу, но находит мелкие лица
# Для скорости с GPU можно оставить 0 или 1
NUMBER_OF_TIMES_TO_UPSAMPLE = 0

# Количество jitters при кодировании лица (больше = точнее, но медленнее)
# 1 = быстро, 100 = очень точно но медленно
# Для GPU можно увеличить до 10-20 без потери скорости
NUM_JITTERS = 1  # 1 = быстро, уменьшено для скорости

# Дополнительные оптимизации для GPU
BATCH_SIZE = 128  # Размер батча для обработки (больше = быстрее на GPU)
MAX_IMAGE_SIZE = 400  # Уменьшено для быстрой обработки

# Кэш для ускорения повторных запросов
face_detection_cache = {}
CACHE_MAX_SIZE = 100

logger.info(f"Face Recognition настроен: model={FACE_MODEL}, CUDA={'включен' if USE_CUDA else 'выключен'}")

# ========================================
# PDF - Конфигурация
# ========================================
TEMP_DIR = str(BASE_DIR / 'temp_pdf')
os.makedirs(TEMP_DIR, exist_ok=True)

# Цвета
PURPLE = (94/255, 67/255, 236/255)
PURPLE_LIGHT = (130/255, 100/255, 255/255)
ORANGE = (255/255, 107/255, 53/255)
LIGHT_BG = (248/255, 246/255, 255/255)
DARK_TEXT = (30/255, 30/255, 30/255)
GRAY_TEXT = (100/255, 100/255, 100/255)
LINE_COLOR = (160/255, 140/255, 200/255)
CARD_BORDER = (180/255, 160/255, 220/255)
WHITE = (1, 1, 1)

# ========================================
# GOOGLE DRIVE - Конфигурация
# ========================================
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '1DuNnC5uQbAIsL3beihEoSc7SZOqcmiUf')
GOOGLE_CREDENTIALS_FILE = resolve_backend_path(os.environ.get('GOOGLE_CREDENTIALS_FILE', 'oauth_credentials.json'))
GOOGLE_TOKEN_FILE = resolve_backend_path(os.environ.get('GOOGLE_TOKEN_FILE', 'token.pickle'))
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Кэшированный сервис Google Drive
_google_drive_service = None

# Журнал последних событий для веб-панели
from collections import deque
recent_events = deque(maxlen=20)

def add_event(icon, message, event_type='info'):
    """Добавить событие в журнал для веб-панели"""
    from datetime import datetime
    recent_events.appendleft({
        'ts': datetime.now().strftime('%H:%M:%S'),
        'icon': icon,
        'message': message,
        'type': event_type
    })


def get_google_drive_service():
    """
    Получает авторизованный сервис Google Drive.
    При первом запуске откроет браузер для авторизации.
    """
    global _google_drive_service
    
    if not GOOGLE_DRIVE_AVAILABLE:
        logger.warning("Google Drive API не доступен")
        return None
    
    if _google_drive_service is not None:
        return _google_drive_service
    
    creds = None
    
    # Загружаем сохранённый токен
    if os.path.exists(GOOGLE_TOKEN_FILE):
        try:
            with open(GOOGLE_TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            logger.warning(f"Ошибка загрузки токена: {e}")
    
    # Если токен невалидный - обновляем или запрашиваем новый
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Токен Google Drive обновлён")
            except Exception as e:
                logger.warning(f"Ошибка обновления токена: {e}")
                creds = None
        
        if not creds:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                logger.error(f"Файл {GOOGLE_CREDENTIALS_FILE} не найден!")
                return None
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES)
                creds = flow.run_local_server(port=0, open_browser=True)
                logger.info("Авторизация Google Drive успешна")
            except Exception as e:
                logger.error(f"Ошибка авторизации Google Drive: {e}")
                return None
        
        # Сохраняем токен
        try:
            with open(GOOGLE_TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
            logger.info("Токен Google Drive сохранён")
        except Exception as e:
            logger.warning(f"Ошибка сохранения токена: {e}")
    
    try:
        _google_drive_service = build('drive', 'v3', credentials=creds)
        return _google_drive_service
    except Exception as e:
        logger.error(f"Ошибка создания сервиса Google Drive: {e}")
        return None


def upload_to_google_drive(filepath, filename, mimetype='application/pdf'):
    """
    Загружает файл в Google Drive и создаёт публичную ссылку.
    
    Args:
        filepath: путь к локальному файлу
        filename: имя файла для Drive
        mimetype: MIME тип файла
    
    Returns:
        dict с download_url и drive_id или None при ошибке
    """
    service = get_google_drive_service()
    
    if not service:
        return None
    
    try:
        # Метаданные файла
        file_metadata = {
            'name': filename,
            'parents': [GOOGLE_DRIVE_FOLDER_ID] if GOOGLE_DRIVE_FOLDER_ID else []
        }
        
        # Загружаем файл
        media = MediaFileUpload(filepath, mimetype=mimetype, resumable=True)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, webContentLink'
        ).execute()
        
        file_id = file.get('id')
        web_content_link = file.get('webContentLink')
        
        # Делаем файл публичным (anyone with link can view)
        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        # Используем webContentLink если есть, иначе формируем ссылку
        # webContentLink - прямая ссылка на скачивание
        if web_content_link:
            download_url = web_content_link
        else:
            # Альтернативный формат для прямого скачивания
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        # Дополнительная ссылка для просмотра в браузере
        view_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        
        logger.info(f"Файл загружен в Google Drive: {filename} (ID: {file_id})")
        logger.info(f"Download URL: {download_url}")
        
        return {
            'drive_id': file_id,
            'download_url': download_url,
            'view_url': view_url,
            'web_view_url': file.get('webViewLink')
        }
        
    except Exception as e:
        logger.error(f"Ошибка загрузки в Google Drive: {e}")
        import traceback
        traceback.print_exc()
        return None

def setup_fonts():
    """Настройка шрифтов с поддержкой кириллицы"""
    # Шрифты с поддержкой кириллицы
    font_paths = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
        ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/timesi.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
    ]

    regular_font = 'Helvetica'
    bold_font = 'Helvetica-Bold'
    italic_font = 'Helvetica'

    for regular, bold, italic in font_paths:
        if os.path.exists(regular):
            try:
                pdfmetrics.registerFont(TTFont('CustomFont', regular))
                regular_font = 'CustomFont'
                if os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont('CustomBold', bold))
                    bold_font = 'CustomBold'
                else:
                    pdfmetrics.registerFont(TTFont('CustomBold', regular))
                    bold_font = 'CustomBold'
                if os.path.exists(italic):
                    pdfmetrics.registerFont(TTFont('CustomItalic', italic))
                    italic_font = 'CustomItalic'
                else:
                    italic_font = regular_font
                logger.info(f"Загружены шрифты: {regular}")
                break
            except Exception as e:
                logger.warning(f"Ошибка шрифта: {e}")

    return regular_font, bold_font, italic_font

FONT_REGULAR, FONT_BOLD, FONT_ITALIC = setup_fonts()


# ========================================
# FACE RECOGNITION - Функции
# ========================================

def load_encodings():
    """Загрузка сохраненных кодировок лиц"""
    global face_encodings_db
    if os.path.exists(ENCODINGS_FILE):
        try:
            with open(ENCODINGS_FILE, 'r') as f:
                data = json.load(f)
                # Конвертируем списки обратно в numpy arrays
                face_encodings_db = {
                    member_id: {
                        'name': info['name'],
                        'encoding': np.array(info['encoding'])
                    }
                    for member_id, info in data.items()
                }
            logger.info(f"Загружено {len(face_encodings_db)} кодировок лиц")
        except Exception as e:
            logger.error(f"Ошибка загрузки кодировок: {e}")
            face_encodings_db = {}


def save_encodings():
    """Сохранение кодировок лиц"""
    try:
        # Конвертируем numpy arrays в списки для JSON
        data = {
            member_id: {
                'name': info['name'],
                'encoding': info['encoding'].tolist()
            }
            for member_id, info in face_encodings_db.items()
        }
        with open(ENCODINGS_FILE, 'w') as f:
            json.dump(data, f)
        logger.info("Кодировки сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения кодировок: {e}")


def get_image_hash(image_array):
    """Получает хэш изображения для кэширования"""
    return hash(image_array.tobytes())


def optimize_image_for_gpu(image):
    """Оптимизирует изображение для обработки на GPU"""
    height, width = image.shape[:2]

    # Уменьшаем изображение если оно слишком большое
    if max(width, height) > MAX_IMAGE_SIZE:
        ratio = MAX_IMAGE_SIZE / max(width, height)
        new_width = int(width * ratio)
        new_height = int(height * ratio)

        # Используем PIL для качественного ресайза
        pil_image = Image.fromarray(image)
        pil_image = pil_image.resize((new_width, new_height), Image.LANCZOS)
        image = np.array(pil_image)
        logger.info(f"Изображение оптимизировано: {width}x{height} → {new_width}x{new_height}")

    return image


def detect_faces_optimized(image):
    """Оптимизированное обнаружение лиц с кэшированием"""
    # Проверяем кэш
    img_hash = get_image_hash(image)
    if img_hash in face_detection_cache:
        logger.info("Использован кэш для обнаружения лиц")
        return face_detection_cache[img_hash]

    # Оптимизируем изображение
    optimized_image = optimize_image_for_gpu(image)

    # Обнаруживаем лица
    start_time = time.time()
    face_locations = face_recognition.face_locations(
        optimized_image,
        model=FACE_MODEL,
        number_of_times_to_upsample=NUMBER_OF_TIMES_TO_UPSAMPLE
    )
    detection_time = time.time() - start_time

    logger.info(f"Обнаружение лиц: {detection_time:.3f}s, найдено: {len(face_locations)}")

    # Сохраняем в кэш
    if len(face_detection_cache) >= CACHE_MAX_SIZE:
        # Удаляем старые записи
        oldest_key = next(iter(face_detection_cache))
        del face_detection_cache[oldest_key]

    face_detection_cache[img_hash] = face_locations
    return face_locations


def decode_base64_image(base64_string):
    """Декодирование base64 изображения с оптимизацией для GPU"""
    try:
        # Убираем префикс data:image если есть
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]

        image_data = base64.b64decode(base64_string)
        image = Image.open(io.BytesIO(image_data))

        # Конвертируем в RGB если нужно
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Оптимизация размера для GPU - уменьшаем большие изображения
        width, height = image.size
        if max(width, height) > MAX_IMAGE_SIZE:
            ratio = MAX_IMAGE_SIZE / max(width, height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.info(f"Изображение уменьшено с {width}x{height} до {new_width}x{new_height}")

        return np.array(image)
    except Exception as e:
        logger.error(f"Ошибка декодирования изображения: {e}")
        return None
    """Декодирование base64 изображения с оптимизацией для GPU"""
    try:
        # Убираем префикс data:image если есть
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]

        image_data = base64.b64decode(base64_string)
        image = Image.open(io.BytesIO(image_data))

        # Конвертируем в RGB если нужно
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Оптимизация размера для GPU - уменьшаем большие изображения
        width, height = image.size
        if max(width, height) > MAX_IMAGE_SIZE:
            ratio = MAX_IMAGE_SIZE / max(width, height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.info(f"Изображение уменьшено с {width}x{height} до {new_width}x{new_height}")

        return np.array(image)
    except Exception as e:
        logger.error(f"Ошибка декодирования изображения: {e}")
        return None


# ========================================
# ОБЩИЕ РОУТЫ
# ========================================

@app.route('/api/health', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Проверка работоспособности сервера"""
    # Собираем новые события (которые клиент ещё не видел)
    since = request.args.get('since', '')
    events_list = list(recent_events)
    if since:
        # Отдаём только события новее указанной метки
        events_list = [e for e in events_list if e['ts'] > since]

    return make_response_json({
        'status': 'ok',
        'service': 'combined_server',
        'face_recognition': True,
        'pdf_generation': True,
        'members_count': len(face_encodings_db),
        'recent_events': events_list
    })


# ========================================
# FACE RECOGNITION - Роуты
# ========================================

@app.route('/api/register_face', methods=['POST'])
@app.route('/register_face', methods=['POST'])
def register_face():
    """
    Регистрация эталонного фото члена семьи

    Параметры:
    - member_id: ID члена семьи
    - member_name: Имя члена семьи
    - image: base64 изображение
    """
    try:
        data = request.json
        member_id = data.get('member_id')
        member_name = data.get('member_name')
        image_base64 = data.get('image')

        if not all([member_id, member_name, image_base64]):
            return make_response_json({
                'success': False,
                'error': 'Отсутствуют обязательные параметры'
            }, 400)

        # Декодируем изображение
        image = decode_base64_image(image_base64)
        if image is None:
            return make_response_json({
                'success': False,
                'error': 'Не удалось декодировать изображение'
            }, 400)

        # Находим лица на изображении (используем оптимизированную функцию)
        face_locations = detect_faces_optimized(image)

        if len(face_locations) == 0:
            return make_response_json({
                'success': False,
                'error': 'На фото не обнаружено лиц'
            }, 400)

        if len(face_locations) > 1:
            return make_response_json({
                'success': False,
                'error': 'На фото обнаружено несколько лиц. Используйте фото с одним человеком'
            }, 400)

        # Получаем кодировку лица (num_jitters для точности)
        face_encodings = face_recognition.face_encodings(image, face_locations, num_jitters=NUM_JITTERS)

        if len(face_encodings) == 0:
            return make_response_json({
                'success': False,
                'error': 'Не удалось получить кодировку лица'
            }, 400)

        # Сохраняем кодировку
        face_encodings_db[str(member_id)] = {
            'name': member_name,
            'encoding': face_encodings[0]
        }

        # Сохраняем эталонное фото
        photo_path = os.path.join(REFERENCE_PHOTOS_DIR, f"{member_id}.jpg")
        Image.fromarray(image).save(photo_path)

        # Сохраняем в файл
        save_encodings()

        logger.info(f"Зарегистрировано лицо для {member_name} (ID: {member_id})")

        return make_response_json({
            'success': True,
            'message': f'Лицо {member_name} успешно зарегистрировано',
            'member_id': member_id
        })

    except Exception as e:
        logger.error(f"Ошибка регистрации лица: {e}")
        return make_response_json({
            'success': False,
            'error': str(e)
        }, 500)


@app.route('/api/recognize_face', methods=['POST'])
@app.route('/recognize_face', methods=['POST'])
def recognize_face():
    """
    Распознавание лица на фото

    Параметры:
    - image: base64 изображение
    - threshold: порог совпадения (по умолчанию 0.6)
    """
    try:
        data = request.json
        image_base64 = data.get('image')
        threshold = data.get('threshold', 0.6)

        if not image_base64:
            return make_response_json({
                'success': False,
                'error': 'Отсутствует изображение'
            }, 400)

        if len(face_encodings_db) == 0:
            return make_response_json({
                'success': False,
                'error': 'Нет зарегистрированных лиц'
            }, 400)

        # Декодируем изображение
        image = decode_base64_image(image_base64)
        if image is None:
            return make_response_json({
                'success': False,
                'error': 'Не удалось декодировать изображение'
            }, 400)

        # Находим лица на изображении (используем оптимизированную функцию)
        face_locations = detect_faces_optimized(image)

        if len(face_locations) == 0:
            return make_response_json({
                'success': False,
                'error': 'На фото не обнаружено лиц'
            }, 400)

        # Получаем кодировки всех лиц на фото
        face_encodings = face_recognition.face_encodings(image, face_locations, num_jitters=NUM_JITTERS)

        # Результаты распознавания
        results = []

        # Получаем известные кодировки
        known_encodings = [info['encoding'] for info in face_encodings_db.values()]
        known_ids = list(face_encodings_db.keys())
        known_names = [info['name'] for info in face_encodings_db.values()]

        # Проверяем каждое лицо на фото
        for face_encoding, face_location in zip(face_encodings, face_locations):
            # Сравниваем с известными лицами
            matches = face_recognition.compare_faces(
                known_encodings,
                face_encoding,
                tolerance=threshold
            )

            # Вычисляем расстояния
            face_distances = face_recognition.face_distance(known_encodings, face_encoding)

            if True in matches:
                # Находим лучшее совпадение
                best_match_index = np.argmin(face_distances)

                if matches[best_match_index]:
                    member_id = known_ids[best_match_index]
                    member_name = known_names[best_match_index]
                    confidence = 1 - face_distances[best_match_index]

                    results.append({
                        'member_id': member_id,
                        'member_name': member_name,
                        'confidence': float(confidence),
                        'location': {
                            'top': face_location[0],
                            'right': face_location[1],
                            'bottom': face_location[2],
                            'left': face_location[3]
                        }
                    })

        if len(results) == 0:
            return make_response_json({
                'success': False,
                'error': 'Лица не распознаны. Возможно, этих людей нет в базе',
                'faces_found': len(face_locations)
            })

        logger.info(f"Распознано {len(results)} лиц")

        return make_response_json({
            'success': True,
            'faces_count': len(face_locations),
            'recognized_count': len(results),
            'results': results
        })

    except Exception as e:
        logger.error(f"Ошибка распознавания: {e}")
        return make_response_json({
            'success': False,
            'error': str(e)
        }, 500)


@app.route('/api/delete_face/<member_id>', methods=['DELETE'])
@app.route('/delete_face/<member_id>', methods=['DELETE'])
def delete_face(member_id):
    """Удаление эталонного фото члена семьи"""
    try:
        if str(member_id) not in face_encodings_db:
            return make_response_json({
                'success': False,
                'error': 'Член семьи не найден'
            }, 404)

        # Удаляем из базы
        del face_encodings_db[str(member_id)]

        # Удаляем файл фото
        photo_path = os.path.join(REFERENCE_PHOTOS_DIR, f"{member_id}.jpg")
        if os.path.exists(photo_path):
            os.remove(photo_path)

        # Сохраняем изменения
        save_encodings()

        logger.info(f"Удалено лицо для ID: {member_id}")

        return make_response_json({
            'success': True,
            'message': 'Лицо успешно удалено'
        })

    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        return make_response_json({
            'success': False,
            'error': str(e)
        }, 500)


@app.route('/api/list_faces', methods=['GET'])
@app.route('/list_faces', methods=['GET'])
def list_faces():
    """Получение списка зарегистрированных лиц"""
    try:
        faces = [
            {
                'member_id': member_id,
                'member_name': info['name']
            }
            for member_id, info in face_encodings_db.items()
        ]

        return make_response_json({
            'success': True,
            'count': len(faces),
            'faces': faces
        })

    except Exception as e:
        logger.error(f"Ошибка получения списка: {e}")
        return make_response_json({
            'success': False,
            'error': str(e)
        }, 500)


@app.route('/api/clear_all', methods=['DELETE'])
@app.route('/clear_all', methods=['DELETE'])
def clear_all():
    """Очистка всей базы распознавания лиц"""
    global face_encodings_db
    try:
        count = len(face_encodings_db)

        # Очищаем базу в памяти
        face_encodings_db = {}

        # Удаляем файл кодировок
        if os.path.exists(ENCODINGS_FILE):
            os.remove(ENCODINGS_FILE)

        # Удаляем все эталонные фото
        for filename in os.listdir(REFERENCE_PHOTOS_DIR):
            filepath = os.path.join(REFERENCE_PHOTOS_DIR, filename)
            if os.path.isfile(filepath):
                os.remove(filepath)

        logger.info(f"База очищена. Удалено {count} лиц")

        return make_response_json({
            'success': True,
            'message': f'База очищена. Удалено {count} лиц',
            'deleted_count': count
        })

    except Exception as e:
        logger.error(f"Ошибка очистки базы: {e}")
        return make_response_json({
            'success': False,
            'error': str(e)
        }, 500)


# ========================================
# PDF GENERATION - Роуты
# ========================================

@app.route('/api/generate_pdf', methods=['POST'])
@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.json
        logger.info(f"PDF request keys: {list(data.keys())}")
        logger.info(f"PDF raw show_photos={data.get('show_photos')}, show_dates={data.get('show_dates')}, show_patronymic={data.get('show_patronymic')}, title={data.get('title')}")
        members = data.get('members', [])
        page_format = data.get('format', 'A4_LANDSCAPE')
        use_drive = data.get('use_drive', True)

        # Новые настройки PDF
        pdf_settings = {
            'show_photos': data.get('show_photos', True),
            'show_dates': data.get('show_dates', True),
            'show_patronymic': data.get('show_patronymic', True),
            'title': data.get('title', 'Семейное Древо'),
            'photo_quality': data.get('photo_quality', 'medium'),
        }
        logger.info(f"PDF settings received: {pdf_settings}")

        if not members:
            return make_response_json({'success': False, 'error': 'Нет данных'}, 400)

        if page_format == 'A4':
            pagesize = A4
        elif page_format == 'A4_LANDSCAPE':
            pagesize = landscape(A4)
        elif page_format == 'A3':
            pagesize = A3
        elif page_format == 'A3_LANDSCAPE':
            pagesize = landscape(A3)
        else:
            pagesize = landscape(A4)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"family_tree_{timestamp}.pdf"
        filepath = os.path.join(TEMP_DIR, filename)

        c = canvas.Canvas(filepath, pagesize=pagesize)
        width, height = pagesize

        draw_family_tree(c, members, width, height, pdf_settings)

        c.save()

        # Получаем размер файла
        pdf_size = os.path.getsize(filepath)
        logger.info(f"PDF создан: {filename}, размер: {pdf_size} байт")
        
        # Событие для веб-панели
        members_count = len(members)
        size_kb = round(pdf_size / 1024)
        settings_info = []
        if not pdf_settings.get('show_photos', True):
            settings_info.append('без фото')
        if not pdf_settings.get('show_dates', True):
            settings_info.append('без дат')
        if not pdf_settings.get('show_patronymic', True):
            settings_info.append('без отчеств')
        extra = f" ({', '.join(settings_info)})" if settings_info else ""
        add_event('📄', f"PDF создан: {members_count} чел., {page_format}, {size_kb} КБ{extra}", 'success')

        # Пробуем загрузить в Google Drive
        if use_drive and GOOGLE_DRIVE_AVAILABLE:
            drive_result = upload_to_google_drive(filepath, filename)
            
            if drive_result:
                # Успешно загружено в Drive
                drive_id = drive_result['drive_id']
                # Прокси ссылка через наш сервер (обходит перехват Android)
                proxy_download_url = f"/download_pdf/{drive_id}"
                
                return make_response_json({
                    'success': True,
                    'filename': filename,
                    'download_url': proxy_download_url,  # Прокси через сервер
                    'direct_drive_url': drive_result['download_url'],  # Прямая ссылка Drive
                    'drive_id': drive_id,
                    'view_url': drive_result.get('view_url'),
                    'size': pdf_size,
                    'storage': 'google_drive'
                })
            else:
                logger.warning("Google Drive загрузка не удалась, возвращаем base64")

        # Fallback: возвращаем как base64
        with open(filepath, 'rb') as f:
            pdf_data = f.read()

        pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')

        logger.info(f"Возвращаем PDF как base64: {len(pdf_base64)} символов")

        return make_response_json({
            'success': True,
            'filename': filename,
            'pdf_base64': pdf_base64,
            'size': pdf_size,
            'storage': 'base64'
        })

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return make_response_json({'success': False, 'error': str(e)}, 500)


@app.route('/api/download_pdf/<drive_id>', methods=['GET'])
@app.route('/download_pdf/<drive_id>', methods=['GET'])
def download_pdf_proxy(drive_id):
    """
    Прокси для скачивания PDF из Google Drive.
    Файл скачивается через сервер, что обходит перехват Android приложением.
    """
    try:
        service = get_google_drive_service()
        
        if not service:
            return make_response_json({'success': False, 'error': 'Google Drive не доступен'}, 500)
        
        # Получаем метаданные файла
        file_metadata = service.files().get(fileId=drive_id, fields='name, mimeType, size').execute()
        filename = file_metadata.get('name', 'download.pdf')
        
        # Скачиваем файл из Google Drive
        from googleapiclient.http import MediaIoBaseDownload
        
        request = service.files().get_media(fileId=drive_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        file_buffer.seek(0)
        pdf_data = file_buffer.read()
        
        logger.info(f"Проксирование PDF: {filename}, размер: {len(pdf_data)} байт")
        
        # Возвращаем файл напрямую
        return Response(
            pdf_data,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(len(pdf_data)),
                'Content-Type': 'application/pdf'
            }
        )
        
    except Exception as e:
        logger.error(f"Ошибка скачивания PDF: {e}")
        import traceback
        traceback.print_exc()
        return make_response_json({'success': False, 'error': str(e)}, 500)




# ========================================
# PDF - Функции (ПОЛНЫЕ из pdf_server.py)
# ========================================

def draw_family_tree(c, members, width, height, settings=None):
    """Рисует семейное древо с автомасштабированием и многостраничностью"""
    if settings is None:
        settings = {}

    show_photos = settings.get('show_photos', True)
    show_dates = settings.get('show_dates', True)
    show_patronymic = settings.get('show_patronymic', True)
    title = settings.get('title', 'Семейное Древо')

    # Группируем по поколениям
    generations = group_by_generation(members)

    gen_order = [
        ('grandparents', 'Бабушки и Дедушки'),
        ('parents', 'Родители'),
        ('uncles', 'Дяди и Тёти'),
        ('children', 'Дети'),
        ('nephews', 'Племянники'),
        ('grandchildren', 'Внуки'),
        ('other', 'Другие')
    ]

    active_gens = [(key, name) for key, name in gen_order if generations.get(key)]

    if not active_gens:
        return

    # --- Авто-расчёт размеров карточек ---
    margin_x = 40
    usable_width = width - 2 * margin_x
    header_h = 80
    footer_h = 40
    gen_label_h = 28  # высота метки поколения
    usable_height = height - header_h - footer_h - 20

    # Максимальное кол-во карточек в одном ряду
    max_in_row = max(len(generations[k]) for k, _ in active_gens)
    max_in_row = max(max_in_row, 1)

    # Вычисляем ширину карточки по самому широкому поколению
    min_gap = 12
    ideal_card_w = min(140, max(90, (usable_width - (max_in_row - 1) * min_gap) / max_in_row))
    card_gap_x = min(20, max(min_gap, ideal_card_w * 0.12))

    # Проверяем, нужен ли перенос в ряду (если карточки слишком узкие)
    max_cards_per_row = max(1, int((usable_width + card_gap_x) / (90 + card_gap_x)))

    # Считаем кол-во строк на каждое поколение
    def rows_for_gen(gen_key):
        n = len(generations[gen_key])
        return max(1, (n + max_cards_per_row - 1) // max_cards_per_row)

    # Пересчёт card_width если перенос не нужен
    needs_wrap = any(len(generations[k]) > max_cards_per_row for k, _ in active_gens)
    if not needs_wrap:
        card_width = ideal_card_w
    else:
        card_width = max(90, (usable_width - (min(max_in_row, max_cards_per_row) - 1) * card_gap_x) / min(max_in_row, max_cards_per_row))

    # Высота карточки по содержимому (а не по фиксированному коэффициенту)
    s = card_width / 130.0
    top_pad = max(8, int(10 * s))
    bottom_pad = max(6, int(8 * s))
    name_h = max(7, min(11, int(9 * s))) + 2
    role_h = max(7, min(11, int(10 * s))) + 1
    
    content_h = top_pad + name_h + role_h + bottom_pad
    
    if show_photos:
        photo_h = max(25, int(card_width * 0.38))
        content_h += photo_h + max(4, int(5 * s))
    if show_patronymic:
        content_h += max(6, min(9, int(8 * s))) + 1
    if show_dates:
        content_h += max(6, min(9, int(8 * s))) + 2
    
    card_height = int(content_h)

    # Вычисляем общее кол-во строк всех поколений
    total_rows = sum(rows_for_gen(k) for k, _ in active_gens)
    gen_gap_y = 30
    total_content_h = total_rows * card_height + (total_rows - 1) * 8 + len(active_gens) * gen_label_h + (len(active_gens) - 1) * gen_gap_y

    # Масштабируем если не помещается на одну страницу
    if total_content_h > usable_height:
        scale = usable_height / total_content_h
        if scale >= 0.55:
            # Уменьшаем пропорционально
            card_height = max(60, int(card_height * scale))
            card_width = max(80, int(card_width * scale))
            card_gap_x = max(8, int(card_gap_x * scale))
            gen_gap_y = max(10, int(gen_gap_y * scale))
        else:
            # Слишком мало места — многостраничность
            _draw_multipage_tree(c, members, width, height, active_gens, generations, settings)
            return

    # --- Одностраничная отрисовка ---
    draw_beautiful_background(c, width, height)
    header_height = draw_header(c, width, height, title)

    card_positions = {}
    current_y = height - header_height - 15

    for gen_idx, (gen_key, gen_name) in enumerate(active_gens):
        gen_members = generations[gen_key]

        # Метка поколения
        current_y -= gen_label_h
        draw_gen_label(c, gen_name, width, current_y + 8)
        current_y -= 4

        # Разбиваем на ряды
        rows = []
        for i in range(0, len(gen_members), max_cards_per_row):
            rows.append(gen_members[i:i + max_cards_per_row])

        for row in rows:
            num = len(row)
            total_w = num * card_width + (num - 1) * card_gap_x
            start_x = (width - total_w) / 2

            for i, member in enumerate(row):
                x = start_x + i * (card_width + card_gap_x)
                y = current_y - card_height

                draw_member_card(c, member, x, y, card_width, card_height, settings)

                member_id = member.get('id')
                card_positions[member_id] = {
                    'x_center': x + card_width / 2,
                    'y_top': y + card_height,
                    'y_bottom': y,
                    'y_center': y + card_height / 2
                }

            current_y -= card_height + 8

        current_y -= gen_gap_y

    draw_connections(c, card_positions, members)
    draw_footer(c, width)


def _draw_multipage_tree(c, members, width, height, active_gens, generations, settings):
    """Многостраничная отрисовка когда не помещается на одну страницу"""
    title = settings.get('title', 'Семейное Древо')
    margin_x = 40
    usable_width = width - 2 * margin_x
    header_h = 80
    footer_h = 40

    # Размеры карточек для многостраничного режима - побольше
    max_in_row_raw = max(len(generations[k]) for k, _ in active_gens)
    max_cards_per_row = max(1, int((usable_width + 12) / (110 + 12)))
    card_width = min(140, max(100, (usable_width - (min(max_in_row_raw, max_cards_per_row) - 1) * 15) / min(max_in_row_raw, max_cards_per_row)))
    card_gap_x = min(20, max(10, card_width * 0.12))
    card_height = int(card_width * 1.12)
    if not settings.get('show_photos', True):
        card_height = int(card_width * 0.7)
    gen_gap_y = 25
    gen_label_h = 28

    page_num = 0

    # Собираем все ряды: [(gen_name, row_members)]
    all_rows = []
    for gen_key, gen_name in active_gens:
        gen_members = generations[gen_key]
        rows_data = []
        for i in range(0, len(gen_members), max_cards_per_row):
            rows_data.append(gen_members[i:i + max_cards_per_row])
        all_rows.append((gen_name, rows_data))

    card_positions = {}
    row_index = 0
    gen_index = 0

    while gen_index < len(all_rows):
        # Новая страница
        if page_num > 0:
            c.showPage()
        draw_beautiful_background(c, width, height)

        if page_num == 0:
            cur_y = height - draw_header(c, width, height, title) - 10
        else:
            draw_header(c, width, height, f"{title} (стр. {page_num + 1})")
            cur_y = height - header_h - 10

        page_bottom = footer_h + 20

        while gen_index < len(all_rows):
            gen_name, rows_data = all_rows[gen_index]

            # Проверяем, поместится ли хотя бы метка + 1 ряд
            needed = gen_label_h + card_height + 8
            if cur_y - needed < page_bottom and cur_y < height - header_h - 50:
                break  # Следующая страница

            # Метка поколения
            cur_y -= gen_label_h
            draw_gen_label(c, gen_name, width, cur_y + 8)
            cur_y -= 4

            while row_index < len(rows_data):
                row = rows_data[row_index]
                if cur_y - card_height - 8 < page_bottom:
                    break  # Ряд не помещается

                num = len(row)
                total_w = num * card_width + (num - 1) * card_gap_x
                start_x = (width - total_w) / 2

                for i, member in enumerate(row):
                    x = start_x + i * (card_width + card_gap_x)
                    y = cur_y - card_height

                    draw_member_card(c, member, x, y, card_width, card_height, settings)

                    member_id = member.get('id')
                    card_positions[member_id] = {
                        'x_center': x + card_width / 2,
                        'y_top': y + card_height,
                        'y_bottom': y,
                        'y_center': y + card_height / 2
                    }

                cur_y -= card_height + 8
                row_index += 1

            if row_index >= len(rows_data):
                cur_y -= gen_gap_y
                gen_index += 1
                row_index = 0
            else:
                break  # Продолжим на следующей странице

        draw_connections(c, card_positions, members)
        draw_footer(c, width)
        page_num += 1


def draw_beautiful_background(c, width, height):
    """Рисует красивый фон с элементами дерева"""
    # Основной градиент - от светло-бежевого к светло-зелёному (пергамент)
    steps = 30
    for i in range(steps):
        ratio = i / steps
        # От тёплого бежевого сверху к светло-зелёному снизу
        r = 0.97 - ratio * 0.04
        g = 0.95 - ratio * 0.01
        b = 0.88 - ratio * 0.06

        y = height - (height / steps) * (i + 1)
        h = height / steps + 1
        c.setFillColorRGB(r, g, b)
        c.rect(0, y, width, h, fill=1, stroke=0)

    # Центральный ствол дерева (снизу)
    c.saveState()
    c.setStrokeColorRGB(0.45, 0.35, 0.2)  # Тёмно-коричневый
    c.setLineWidth(8)
    c.setLineCap(1)

    # Основной ствол
    trunk_x = width / 2
    c.line(trunk_x, 0, trunk_x, 60)
    c.line(trunk_x - 15, 60, trunk_x, 90)
    c.line(trunk_x + 15, 60, trunk_x, 90)

    # Корни
    c.setLineWidth(4)
    c.line(trunk_x, 0, trunk_x - 40, -10)
    c.line(trunk_x, 0, trunk_x + 40, -10)
    c.line(trunk_x - 20, 10, trunk_x - 50, 0)
    c.line(trunk_x + 20, 10, trunk_x + 50, 0)

    c.restoreState()

    # Декоративные ветви по углам
    c.saveState()
    c.setStrokeColorRGB(0.55, 0.45, 0.25)  # Коричневый для веток
    c.setLineWidth(4)
    c.setLineCap(1)

    # Левый верхний угол - ветка с изгибом
    c.line(0, height, 60, height - 40)
    c.line(60, height - 40, 50, height - 80)
    c.line(60, height - 40, 100, height - 60)
    c.line(100, height - 60, 90, height - 100)
    c.line(100, height - 60, 140, height - 75)

    # Правый верхний угол
    c.line(width, height, width - 60, height - 40)
    c.line(width - 60, height - 40, width - 50, height - 80)
    c.line(width - 60, height - 40, width - 100, height - 60)
    c.line(width - 100, height - 60, width - 90, height - 100)
    c.line(width - 100, height - 60, width - 140, height - 75)

    # Нижние углы - маленькие веточки
    c.setLineWidth(3)
    c.line(0, 50, 40, 70)
    c.line(40, 70, 30, 100)
    c.line(40, 70, 70, 85)

    c.line(width, 50, width - 40, 70)
    c.line(width - 40, 70, width - 30, 100)
    c.line(width - 40, 70, width - 70, 85)

    c.restoreState()

    # Листочки (разных оттенков зелёного)
    leaf_positions = [
        # Верхний левый
        (55, height - 75, 10), (95, height - 55, 8), (45, height - 95, 7),
        (135, height - 70, 9), (85, height - 95, 6), (110, height - 85, 7),
        # Верхний правый
        (width - 55, height - 75, 10), (width - 95, height - 55, 8), (width - 45, height - 95, 7),
        (width - 135, height - 70, 9), (width - 85, height - 95, 6), (width - 110, height - 85, 7),
        # Нижний левый
        (35, 95, 7), (65, 80, 6), (25, 75, 5),
        # Нижний правый
        (width - 35, 95, 7), (width - 65, 80, 6), (width - 25, 75, 5),
    ]

    for x, y, size in leaf_positions:
        # Разные оттенки зелёного
        green_shade = 0.5 + (hash((x, y)) % 20) / 100
        c.setFillColorRGB(0.3, green_shade, 0.3)
        c.circle(x, y, size, fill=1, stroke=0)

    # Декоративная двойная рамка (золотисто-коричневая)
    margin = 12
    c.setStrokeColorRGB(0.6, 0.5, 0.3)
    c.setLineWidth(3)
    c.roundRect(margin, margin, width - 2*margin, height - 2*margin, 15, fill=0, stroke=1)

    # Внутренняя рамка
    c.setStrokeColorRGB(0.75, 0.65, 0.45)
    c.setLineWidth(1.5)
    c.roundRect(margin + 6, margin + 6, width - 2*margin - 12, height - 2*margin - 12, 12, fill=0, stroke=1)

    # Декоративные уголки рамки
    corner_len = 25
    c.setStrokeColorRGB(0.5, 0.4, 0.2)
    c.setLineWidth(2)
    # Верхний левый
    c.line(margin + 3, height - margin - 3, margin + 3, height - margin - 3 - corner_len)
    c.line(margin + 3, height - margin - 3, margin + 3 + corner_len, height - margin - 3)
    # Верхний правый
    c.line(width - margin - 3, height - margin - 3, width - margin - 3, height - margin - 3 - corner_len)
    c.line(width - margin - 3, height - margin - 3, width - margin - 3 - corner_len, height - margin - 3)
    # Нижний левый
    c.line(margin + 3, margin + 3, margin + 3, margin + 3 + corner_len)
    c.line(margin + 3, margin + 3, margin + 3 + corner_len, margin + 3)
    # Нижний правый
    c.line(width - margin - 3, margin + 3, width - margin - 3, margin + 3 + corner_len)
    c.line(width - margin - 3, margin + 3, width - margin - 3 - corner_len, margin + 3)


def draw_header(c, width, height, title='Семейное Древо'):
    """Заголовок документа с рукописным шрифтом"""
    header_h = 80

    # Декоративный баннер для заголовка
    banner_y = height - header_h + 10
    banner_h = 60

    # Ширина баннера зависит от длины заголовка
    title_pixel_w = len(title) * 14 + 80
    banner_w = max(400, min(width - 80, title_pixel_w))

    # Фон баннера - пергамент
    c.setFillColorRGB(0.95, 0.92, 0.85)
    c.roundRect(width/2 - banner_w/2, banner_y, banner_w, banner_h, 10, fill=1, stroke=0)

    # Рамка баннера
    c.setStrokeColorRGB(0.6, 0.5, 0.3)
    c.setLineWidth(2)
    c.roundRect(width/2 - banner_w/2, banner_y, banner_w, banner_h, 10, fill=0, stroke=1)

    # Декоративные завитки по бокам
    c.setStrokeColorRGB(0.5, 0.4, 0.2)
    c.setLineWidth(1.5)
    c.arc(width/2 - banner_w/2 - 10, banner_y + 15, width/2 - banner_w/2 + 10, banner_y + 45, 90, 180)
    c.arc(width/2 + banner_w/2 - 10, banner_y + 15, width/2 + banner_w/2 + 10, banner_y + 45, 270, 180)

    # Заголовок — адаптивный размер шрифта
    font_size = min(32, max(18, int(banner_w / max(len(title), 1) * 1.6)))
    c.setFillColorRGB(0.3, 0.2, 0.1)
    c.setFont(FONT_BOLD, font_size)
    c.drawCentredString(width / 2, banner_y + 22, title)

    # Подзаголовок
    c.setFont(FONT_REGULAR, 10)
    c.setFillColorRGB(0.5, 0.4, 0.3)
    c.drawCentredString(width / 2, banner_y + 5, "~ FamilyOne ~")

    # Декоративная линия под заголовком
    c.setStrokeColorRGB(0.6, 0.5, 0.3)
    c.setLineWidth(1)
    c.line(width/2 - 100, banner_y + 2, width/2 + 100, banner_y + 2)

    return header_h


def draw_gen_label(c, name, width, y):
    """Метка поколения в винтажном стиле"""
    text_width = len(name) * 8 + 40

    # Фон для метки - пергамент
    c.setFillColorRGB(0.95, 0.92, 0.85)
    c.roundRect(width/2 - text_width/2, y - 8, text_width, 20, 5, fill=1, stroke=0)

    # Рамка метки
    c.setStrokeColorRGB(0.6, 0.5, 0.3)
    c.setLineWidth(1)
    c.roundRect(width/2 - text_width/2, y - 8, text_width, 20, 5, fill=0, stroke=1)

    # Декоративные линии по бокам
    c.setStrokeColorRGB(0.7, 0.6, 0.4)
    c.setLineWidth(1.5)
    line_width = 60

    # Левая линия с завитком
    c.line(width/2 - text_width/2 - line_width, y + 2, width/2 - text_width/2 - 8, y + 2)
    c.circle(width/2 - text_width/2 - line_width - 4, y + 2, 3, fill=1, stroke=0)

    # Правая линия с завитком
    c.line(width/2 + text_width/2 + 8, y + 2, width/2 + text_width/2 + line_width, y + 2)
    c.circle(width/2 + text_width/2 + line_width + 4, y + 2, 3, fill=1, stroke=0)

    # Текст курсивом (с поддержкой кириллицы)
    c.setFillColorRGB(0.4, 0.25, 0.1)  # Тёмно-коричневый
    c.setFont(FONT_ITALIC, 13)
    c.drawCentredString(width / 2, y - 3, name)


def draw_member_card(c, member, x, y, w, h, settings=None):
    """Карточка члена семьи — адаптивная под размер и настройки"""
    if settings is None:
        settings = {}

    show_photos = settings.get('show_photos', True)
    show_dates = settings.get('show_dates', True)
    show_patronymic = settings.get('show_patronymic', True)

    # Масштаб шрифта пропорционален ширине карточки (базовая: 130)
    s = w / 130.0

    # Тень
    c.setFillColorRGB(0.7, 0.65, 0.55)
    c.roundRect(x + 3, y - 3, w, h, 8, fill=1, stroke=0)

    # Основа карточки
    c.setFillColorRGB(0.98, 0.96, 0.90)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=0)

    # Внешняя рамка
    c.setStrokeColorRGB(0.6, 0.5, 0.3)
    c.setLineWidth(max(1, 2 * s))
    c.roundRect(x, y, w, h, 8, fill=0, stroke=1)

    # Внутренняя рамка
    c.setStrokeColorRGB(0.75, 0.65, 0.45)
    c.setLineWidth(1)
    inset = max(3, int(4 * s))
    c.roundRect(x + inset, y + inset, w - 2*inset, h - 2*inset, 5, fill=0, stroke=1)

    # Декоративные уголки
    corner_size = max(6, int(12 * s))
    edge = max(5, int(8 * s))
    c.setFillColorRGB(0.6, 0.5, 0.3)
    c.line(x + edge, y + h - edge, x + edge, y + h - edge - corner_size)
    c.line(x + edge, y + h - edge, x + edge + corner_size, y + h - edge)
    c.line(x + w - edge, y + h - edge, x + w - edge, y + h - edge - corner_size)
    c.line(x + w - edge, y + h - edge, x + w - edge - corner_size, y + h - edge)
    c.line(x + edge, y + edge, x + edge, y + edge + corner_size)
    c.line(x + edge, y + edge, x + edge + corner_size, y + edge)
    c.line(x + w - edge, y + edge, x + w - edge, y + edge + corner_size)
    c.line(x + w - edge, y + edge, x + w - edge - corner_size, y + edge)

    curr_y = y + h - max(8, int(10 * s))

    # Фото
    if show_photos:
        photo_size = max(25, int(w * 0.38))
        photo_x = x + (w - photo_size) / 2
        photo_y = curr_y - photo_size

        photo_data = member.get('photoBase64')
        if photo_data:
            try:
                draw_photo(c, photo_data, photo_x, photo_y, photo_size)
            except Exception as e:
                logger.warning(f"Фото ошибка: {e}")
                draw_avatar(c, photo_x, photo_y, photo_size)
        else:
            draw_avatar(c, photo_x, photo_y, photo_size)

        curr_y = photo_y - max(4, int(5 * s))

    # Адаптивные размеры шрифтов
    name_font = max(7, min(11, int(9 * s)))
    detail_font = max(6, min(9, int(8 * s)))
    role_font = max(7, min(11, int(10 * s)))

    # Функция-обрезчик по ширине
    max_text_w = w - 2 * inset - 4
    def fit_text(text, font_name, font_size):
        c.setFont(font_name, font_size)
        tw = c.stringWidth(text, font_name, font_size)
        if tw <= max_text_w:
            return text
        while len(text) > 3 and c.stringWidth(text + "..", font_name, font_size) > max_text_w:
            text = text[:-1]
        return text + ".."

    # Имя
    c.setFillColorRGB(0.25, 0.2, 0.1)
    name = f"{member.get('lastName', '')} {member.get('firstName', '')}"
    name = fit_text(name, FONT_BOLD, name_font)
    c.setFont(FONT_BOLD, name_font)
    c.drawCentredString(x + w/2, curr_y, name)
    curr_y -= name_font + 2

    # Отчество
    if show_patronymic:
        patronymic = member.get('patronymic', '')
        if patronymic:
            c.setFillColorRGB(0.4, 0.35, 0.25)
            patronymic = fit_text(patronymic, FONT_REGULAR, detail_font)
            c.setFont(FONT_REGULAR, detail_font)
            c.drawCentredString(x + w/2, curr_y, patronymic)
            curr_y -= detail_font + 1

    # Роль
    role = get_role_name(member.get('role', 'OTHER'))
    c.setFillColorRGB(0.2, 0.5, 0.3)
    c.setFont(FONT_ITALIC, role_font)
    c.drawCentredString(x + w/2, curr_y, role)
    curr_y -= role_font + 1

    # Дата
    if show_dates:
        birth = member.get('birthDate', '')
        if birth:
            c.setFillColorRGB(0.5, 0.45, 0.35)
            c.setFont(FONT_REGULAR, detail_font)
            c.drawCentredString(x + w/2, curr_y, birth)


def draw_photo(c, photo_data, x, y, size):
    """Рисует круглое фото"""
    if ',' in photo_data:
        photo_data = photo_data.split(',')[1]

    img_data = base64.b64decode(photo_data)
    img = Image.open(io.BytesIO(img_data))
    img = img.convert('RGBA')

    # Делаем квадратное изображение (обрезаем по центру)
    width_img, height_img = img.size
    min_side = min(width_img, height_img)
    left = (width_img - min_side) // 2
    top = (height_img - min_side) // 2
    img = img.crop((left, top, left + min_side, top + min_side))

    # Масштабируем
    img = img.resize((int(size * 3), int(size * 3)), Image.LANCZOS)

    # Создаём круглую маску
    mask = Image.new('L', img.size, 0)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, img.size[0], img.size[1]), fill=255)

    # Применяем маску
    output = Image.new('RGBA', img.size, (255, 255, 255, 0))
    output.paste(img, (0, 0))
    output.putalpha(mask)

    # Сохраняем
    temp_path = os.path.join(TEMP_DIR, f"photo_{hash(photo_data) % 10000}.png")
    output.save(temp_path, 'PNG')

    # Рисуем фиолетовую рамку
    c.setFillColorRGB(*PURPLE)
    c.circle(x + size/2, y + size/2, size/2 + 3, fill=1, stroke=0)

    # Белый фон под фото
    c.setFillColorRGB(*WHITE)
    c.circle(x + size/2, y + size/2, size/2, fill=1, stroke=0)

    # Рисуем фото
    c.drawImage(temp_path, x, y, size, size, mask='auto')

    try:
        os.remove(temp_path)
    except:
        pass


def draw_avatar(c, x, y, size):
    """Плейсхолдер"""
    # Круг
    c.setFillColorRGB(0.92, 0.90, 0.96)
    c.circle(x + size/2, y + size/2, size/2, fill=1, stroke=0)

    # Рамка
    c.setStrokeColorRGB(*CARD_BORDER)
    c.setLineWidth(2)
    c.circle(x + size/2, y + size/2, size/2, fill=0, stroke=1)

    # Иконка человека
    c.setFillColorRGB(*GRAY_TEXT)
    cx, cy = x + size/2, y + size/2

    # Голова
    c.circle(cx, cy + 8, 8, fill=1, stroke=0)
    # Тело
    c.ellipse(cx - 12, cy - 18, cx + 12, cy - 2, fill=1, stroke=0)


def draw_connections(c, positions, members):
    """Линии связей"""
    c.setStrokeColorRGB(*LINE_COLOR)
    c.setLineWidth(2)

    drawn_pairs = set()

    for member in members:
        member_id = member.get('id')
        father_id = member.get('fatherId')
        mother_id = member.get('motherId')

        if member_id not in positions:
            continue

        child = positions[member_id]

        # К отцу
        if father_id and father_id in positions:
            pair = tuple(sorted([member_id, father_id]))
            if pair not in drawn_pairs:
                parent = positions[father_id]
                draw_tree_line(c, parent['x_center'], parent['y_bottom'],
                              child['x_center'], child['y_top'])
                drawn_pairs.add(pair)

        # К матери
        if mother_id and mother_id in positions:
            pair = tuple(sorted([member_id, mother_id]))
            if pair not in drawn_pairs:
                parent = positions[mother_id]
                draw_tree_line(c, parent['x_center'], parent['y_bottom'],
                              child['x_center'], child['y_top'])
                drawn_pairs.add(pair)


def draw_tree_line(c, x1, y1, x2, y2):
    """Рисует линию древа"""
    mid_y = (y1 + y2) / 2

    c.setStrokeColorRGB(*LINE_COLOR)
    c.setLineWidth(2)

    # Вертикальная от родителя
    c.line(x1, y1, x1, mid_y)
    # Горизонтальная
    c.line(x1, mid_y, x2, mid_y)
    # Вертикальная к ребёнку
    c.line(x2, mid_y, x2, y2)

    # Точка соединения
    c.setFillColorRGB(*PURPLE)
    c.circle(x2, y2, 4, fill=1, stroke=0)


def draw_footer(c, width):
    """Футер"""
    c.setFillColorRGB(*GRAY_TEXT)
    c.setFont(FONT_REGULAR, 9)
    date_str = datetime.now().strftime("%d.%m.%Y")
    c.drawCentredString(width / 2, 15, f"Дата создания: {date_str}")

    # Линия над футером
    c.setStrokeColorRGB(*LINE_COLOR)
    c.setLineWidth(0.5)
    c.line(50, 30, width - 50, 30)


def get_role_name(role):
    roles = {
        'GRANDFATHER': 'Дедушка', 'GRANDMOTHER': 'Бабушка',
        'FATHER': 'Отец', 'MOTHER': 'Мать',
        'SON': 'Сын', 'DAUGHTER': 'Дочь',
        'BROTHER': 'Брат', 'SISTER': 'Сестра',
        'UNCLE': 'Дядя', 'AUNT': 'Тётя',
        'NEPHEW': 'Племянник', 'NIECE': 'Племянница',
        'GRANDSON': 'Внук', 'GRANDDAUGHTER': 'Внучка',
        'OTHER': 'Родственник'
    }
    return roles.get(role, 'Родственник')


def group_by_generation(members):
    gens = {
        'grandparents': [], 'parents': [], 'uncles': [],
        'children': [], 'nephews': [], 'grandchildren': [], 'other': []
    }

    role_map = {
        'GRANDFATHER': 'grandparents', 'GRANDMOTHER': 'grandparents',
        'FATHER': 'parents', 'MOTHER': 'parents',
        'UNCLE': 'uncles', 'AUNT': 'uncles',
        'SON': 'children', 'DAUGHTER': 'children',
        'BROTHER': 'children', 'SISTER': 'children',
        'NEPHEW': 'nephews', 'NIECE': 'nephews',
        'GRANDSON': 'grandchildren', 'GRANDDAUGHTER': 'grandchildren',
        'OTHER': 'other'
    }

    for member in members:
        role = member.get('role', 'OTHER')
        gen = role_map.get(role, 'other')
        gens[gen].append(member)

    # Группируем пары (муж+жена) вместе
    for gen_key in gens:
        gens[gen_key] = sort_as_couples(gens[gen_key], members)

    return gens


def sort_as_couples(gen_members, all_members):
    """Сортирует членов поколения парами (муж+жена рядом)"""
    if len(gen_members) <= 1:
        return gen_members

    # Находим пары через общих детей
    couples = find_couples(gen_members, all_members)

    result = []
    used_ids = set()

    # Сначала добавляем пары
    for m_id, f_id in couples:
        male = next((m for m in gen_members if m.get('id') == m_id), None)
        female = next((m for m in gen_members if m.get('id') == f_id), None)

        if male and male.get('id') not in used_ids:
            result.append(male)
            used_ids.add(male.get('id'))
        if female and female.get('id') not in used_ids:
            result.append(female)
            used_ids.add(female.get('id'))

    # Добавляем оставшихся (одиночек), сортируя мужчин перед женщинами
    remaining = [m for m in gen_members if m.get('id') not in used_ids]
    remaining.sort(key=lambda m: get_gender_order(m.get('role', 'OTHER')))
    result.extend(remaining)

    return result


def find_couples(gen_members, all_members):
    """Находит пары (муж+жена) через общих детей"""
    couples = []
    member_ids = {m.get('id') for m in gen_members}

    # Ищем детей, у которых оба родителя в этом поколении
    for member in all_members:
        father_id = member.get('fatherId')
        mother_id = member.get('motherId')

        if father_id and mother_id:
            if father_id in member_ids and mother_id in member_ids:
                couple = (father_id, mother_id)
                if couple not in couples:
                    couples.append(couple)

    # Если не нашли через детей, группируем по ролям (дедушка+бабушка, отец+мать)
    if not couples:
        males = [m for m in gen_members if get_gender_order(m.get('role', 'OTHER')) == 1]
        females = [m for m in gen_members if get_gender_order(m.get('role', 'OTHER')) == 2]

        # Создаём пары по порядку
        for i, male in enumerate(males):
            if i < len(females):
                couples.append((male.get('id'), females[i].get('id')))

    return couples


def get_gender_order(role):
    """Возвращает порядок: 1 - мужской, 2 - женский, 3 - другое"""
    male_roles = {'GRANDFATHER', 'FATHER', 'SON', 'BROTHER', 'UNCLE', 'NEPHEW', 'GRANDSON'}
    female_roles = {'GRANDMOTHER', 'MOTHER', 'DAUGHTER', 'SISTER', 'AUNT', 'NIECE', 'GRANDDAUGHTER'}

    if role in male_roles:
        return 1
    elif role in female_roles:
        return 2
    return 3


# ========================================
# MAIN
# ========================================

if __name__ == '__main__':
    # Загружаем сохраненные кодировки при запуске
    load_encodings()

    # Запускаем сервер
    logger.info("=" * 50)
    logger.info(f"Combined Server запущен на {API_HOST}:{API_PORT}")
    logger.info("Face Recognition + PDF Generation")
    logger.info(f"Загружено {len(face_encodings_db)} лиц")
    logger.info(f"CUDA: {'включен' if USE_CUDA else 'выключен'}")
    logger.info(f"CORS origins: {', '.join(CORS_ORIGINS)}")
    logger.info(f"MAX_CONTENT_LENGTH: {MAX_CONTENT_LENGTH_MB} MB")
    logger.info("=" * 50)

    # Используем waitress для production (решает проблему с ngrok)
    # Flask dev-server может блокировать ответы через ngrok
    try:
        from waitress import serve
        logger.info("Запуск через Waitress (production mode)")
        serve(app, host=API_HOST, port=API_PORT, threads=8)
    except ImportError:
        logger.warning("Waitress не установлен, используем Flask dev-server")
        logger.warning("Для лучшей работы с ngrok: pip install waitress")
        app.run(host=API_HOST, port=API_PORT, debug=False)

