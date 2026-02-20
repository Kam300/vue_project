"""
Combined Server для приложения Семейное Древо
Объединяет Face Recognition (server.py) и PDF Generation (pdf_server.py) на одном порту
БЕЗ ПОТЕРИ ФУНКЦИОНАЛЬНОСТИ
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import numpy as np
import base64
import io
from PIL import Image, ImageOps
import os
import json
import logging
from datetime import datetime
import time
import pickle
import hashlib
import tempfile
import zipfile
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

try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport.requests import Request as GoogleAuthRequest
    GOOGLE_TOKEN_VERIFY_AVAILABLE = True
except ImportError:
    GOOGLE_TOKEN_VERIFY_AVAILABLE = False
    logging.warning("Google auth token verification is unavailable. Install google-auth.")

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


_DLL_DIR_HANDLES = []


def configure_windows_dll_dirs():
    """Register CUDA/cuDNN DLL directories before importing dlib/face_recognition."""
    if os.name != 'nt' or not hasattr(os, 'add_dll_directory'):
        return

    repo_root = BASE_DIR.parent
    candidates = []

    cuda_env = os.environ.get('CUDA_PATH')
    if cuda_env:
        cuda_env_path = Path(cuda_env)
        candidates.extend([cuda_env_path / 'bin' / 'x64', cuda_env_path / 'bin'])

    cuda_root = Path(r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA')
    if cuda_root.exists():
        cuda_versions = sorted(cuda_root.glob('v*'), key=lambda path: path.name, reverse=True)
        if cuda_versions:
            candidates.extend([cuda_versions[0] / 'bin' / 'x64', cuda_versions[0] / 'bin'])

    candidates.extend([
        repo_root / '.runtime' / 'cudnn-cu13-extracted' / 'cudnn-windows-x86_64-9.19.0.56_cuda13-archive' / 'bin' / 'x64',
        BASE_DIR / '.venv' / 'Lib' / 'site-packages' / 'nvidia' / 'cu13' / 'bin' / 'x86_64',
        BASE_DIR / '.venv' / 'Lib' / 'site-packages' / 'nvidia' / 'cudnn' / 'bin',
        BASE_DIR / '.venv' / 'Lib' / 'site-packages' / 'nvidia' / 'cudnn' / 'bin' / 'x64',
    ])

    seen = set()
    path_entries = []
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str in seen or not candidate.exists():
            continue
        seen.add(candidate_str)
        path_entries.append(candidate_str)
        try:
            _DLL_DIR_HANDLES.append(os.add_dll_directory(candidate_str))
        except OSError:
            continue

    if path_entries:
        current_path = os.environ.get('PATH', '')
        os.environ['PATH'] = ';'.join(path_entries) + ';' + current_path


configure_windows_dll_dirs()
import face_recognition


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


def env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default

    normalized = raw.strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False

    logger.warning(f"Invalid boolean value {name}={raw!r}, using default {default}")
    return default


def env_csv(name, default=None):
    raw = os.environ.get(name, "")
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if items:
        return items
    return list(default or [])


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

_DEFAULT_CORS_ORIGINS = [
    PUBLIC_ORIGIN,
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:4173',
    'http://127.0.0.1:4173',
]
CORS_ORIGINS = list(dict.fromkeys(_DEFAULT_CORS_ORIGINS + env_csv('CORS_ORIGINS')))

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
    headers = dict(request.headers)
    if 'Authorization' in headers:
        headers['Authorization'] = 'Bearer ***'
    logger.info(f"Headers: {headers}")
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
USE_CUDA = env_bool('USE_CUDA', USE_CUDA)
FACE_MODEL = 'cnn' if USE_CUDA else 'hog'


def detect_cuda_runtime():
    """Detects real CUDA availability in dlib on this host."""
    result = {
        'dlib_use_cuda': False,
        'cuda_device_count': 0,
        'cuda_enabled': False,
        'reason': ''
    }

    try:
        import dlib
    except Exception as exc:
        result['reason'] = f'dlib import error: {exc}'
        return result

    result['dlib_use_cuda'] = bool(getattr(dlib, 'DLIB_USE_CUDA', False))
    try:
        result['cuda_device_count'] = int(dlib.cuda.get_num_devices())
    except Exception as exc:
        result['reason'] = f'cuda device check error: {exc}'
        result['cuda_device_count'] = 0

    result['cuda_enabled'] = result['dlib_use_cuda'] and result['cuda_device_count'] > 0
    if not result['cuda_enabled'] and not result['reason']:
        if not result['dlib_use_cuda']:
            result['reason'] = 'dlib built without CUDA support'
        elif result['cuda_device_count'] <= 0:
            result['reason'] = 'no CUDA devices available for dlib'

    return result


CUDA_RUNTIME = detect_cuda_runtime()
CUDA_ENABLED = USE_CUDA and CUDA_RUNTIME['cuda_enabled']
DLIB_USE_CUDA = CUDA_RUNTIME['dlib_use_cuda']
CUDA_DEVICE_COUNT = CUDA_RUNTIME['cuda_device_count']
CUDA_DISABLED_REASON = CUDA_RUNTIME['reason']
FACE_MODEL = 'cnn' if CUDA_ENABLED else 'hog'

# Количество раз для повышения разрешения при поиске лиц
# 1 обычно заметно повышает детекцию на портретных фото с телефона
NUMBER_OF_TIMES_TO_UPSAMPLE = max(0, env_int('FACE_UPSAMPLE', 1))
FALLBACK_UPSAMPLE = max(NUMBER_OF_TIMES_TO_UPSAMPLE, env_int('FACE_UPSAMPLE_FALLBACK', 2))

# Количество jitters при кодировании лица (больше = точнее, но медленнее)
# 1 = быстро, 100 = очень точно но медленно
# Для GPU можно увеличить до 10-20 без потери скорости
NUM_JITTERS = 1  # 1 = быстро, уменьшено для скорости

# Дополнительные оптимизации для GPU
BATCH_SIZE = 128  # Размер батча для обработки (больше = быстрее на GPU)
MAX_IMAGE_SIZE = max(400, env_int('MAX_IMAGE_SIZE', 1920))
DECODE_MAX_IMAGE_SIZE = max(MAX_IMAGE_SIZE, env_int('DECODE_MAX_IMAGE_SIZE', 2560))
DETECTION_UPSCALE_FACTORS = (1.6, 2.0, 2.6)
CROP_UPSCALE_FACTORS = (1.4, 1.8, 2.2)
EXTRA_UPSAMPLE_MAX_PIXELS = max(300000, env_int('EXTRA_UPSAMPLE_MAX_PIXELS', 1400000))

# Кэш для ускорения повторных запросов
face_detection_cache = {}
CACHE_MAX_SIZE = 100

logger.info(f"Face Recognition настроен: model={FACE_MODEL}, CUDA={'включен' if CUDA_ENABLED else 'выключен'}")
if USE_CUDA and not CUDA_ENABLED:
    logger.warning(
        f"CUDA requested but unavailable, fallback to CPU/HOG. "
        f"dlib_cuda={DLIB_USE_CUDA}, devices={CUDA_DEVICE_COUNT}, reason={CUDA_DISABLED_REASON}"
    )
logger.info(
    f"Face runtime: requested_cuda={USE_CUDA}, active_cuda={CUDA_ENABLED}, "
    f"dlib_cuda={DLIB_USE_CUDA}, cuda_devices={CUDA_DEVICE_COUNT}, model={FACE_MODEL}"
)

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
GOOGLE_OAUTH_WEB_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_WEB_CLIENT_ID', '').strip()

# ========================================
# BACKUP - Конфигурация
# ========================================
BACKUP_STORAGE_DIR = resolve_backend_path(os.environ.get('BACKUP_STORAGE_DIR', 'backup_storage'))
BACKUP_MAX_FILE_MB = env_int('BACKUP_MAX_FILE_MB', 250)
BACKUP_MAX_FILE_BYTES = max(1, BACKUP_MAX_FILE_MB) * 1024 * 1024
BACKUP_MAX_UNCOMPRESSED_MB = env_int('BACKUP_MAX_UNCOMPRESSED_MB', 700)
BACKUP_MAX_UNCOMPRESSED_BYTES = max(1, BACKUP_MAX_UNCOMPRESSED_MB) * 1024 * 1024
BACKUP_SCHEMA_VERSION = max(1, env_int('BACKUP_SCHEMA_VERSION', 1))
os.makedirs(BACKUP_STORAGE_DIR, exist_ok=True)

# Ensure Flask request cap does not block backup upload before route validation.
if int(app.config.get('MAX_CONTENT_LENGTH', 0) or 0) < BACKUP_MAX_FILE_BYTES:
    app.config['MAX_CONTENT_LENGTH'] = BACKUP_MAX_FILE_BYTES

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


def _schema_error(message, status=400):
    return make_response_json({
        'success': False,
        'schemaVersion': BACKUP_SCHEMA_VERSION,
        'error': message
    }, status)


def parse_bearer_token(auth_header):
    if not auth_header:
        return None
    parts = auth_header.strip().split(' ', 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    return parts[1].strip() or None


def require_google_auth():
    if not GOOGLE_TOKEN_VERIFY_AVAILABLE:
        return None, _schema_error(
            'Google token verification is unavailable on server',
            status=500
        )

    if not GOOGLE_OAUTH_WEB_CLIENT_ID:
        return None, _schema_error(
            'GOOGLE_OAUTH_WEB_CLIENT_ID is not configured',
            status=500
        )

    bearer_token = parse_bearer_token(request.headers.get('Authorization'))
    if not bearer_token:
        return None, _schema_error('Missing Bearer token', status=401)

    try:
        token_info = google_id_token.verify_oauth2_token(
            bearer_token,
            GoogleAuthRequest(),
            GOOGLE_OAUTH_WEB_CLIENT_ID
        )
        issuer = str(token_info.get('iss', ''))
        if issuer not in {'accounts.google.com', 'https://accounts.google.com'}:
            raise ValueError('Invalid token issuer')

        owner_sub = str(token_info.get('sub', '')).strip()
        if not owner_sub:
            raise ValueError('Token sub is missing')

        return owner_sub, None
    except Exception as exc:
        logger.warning(f"Google token verification failed: {exc}")
        return None, _schema_error('Invalid or expired Google token', status=401)


def owner_storage_key(owner_sub):
    return hashlib.sha256(owner_sub.encode('utf-8')).hexdigest()


def get_backup_paths(owner_sub):
    owner_dir = Path(BACKUP_STORAGE_DIR) / owner_storage_key(owner_sub)
    owner_dir.mkdir(parents=True, exist_ok=True)
    return owner_dir, owner_dir / 'latest.zip', owner_dir / 'latest.meta.json'


def compute_file_sha256(file_path):
    digest = hashlib.sha256()
    with open(file_path, 'rb') as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_zip_entry(name):
    normalized = Path(name).as_posix().lstrip('/')
    parts = Path(normalized).parts
    if not normalized or '..' in parts:
        raise ValueError(f'Unsafe zip entry: {name}')
    if normalized.startswith('\\') or ':' in parts[0]:
        raise ValueError(f'Unsafe zip entry: {name}')
    return normalized


def _read_json_entry(archive, name):
    with archive.open(name, 'r') as entry_stream:
        payload = entry_stream.read()
    return json.loads(payload.decode('utf-8'))


def validate_backup_archive(file_path):
    try:
        total_uncompressed = 0
        asset_entries = []
        all_entries = set()

        with zipfile.ZipFile(file_path, 'r') as archive:
            for info in archive.infolist():
                normalized_name = _normalize_zip_entry(info.filename)
                if info.is_dir():
                    continue

                all_entries.add(normalized_name)
                total_uncompressed += int(info.file_size)
                if total_uncompressed > BACKUP_MAX_UNCOMPRESSED_BYTES:
                    return False, 'Backup archive is too large after extraction'

                if normalized_name.startswith('assets/'):
                    asset_entries.append(normalized_name)

            required_entries = {'manifest.json', 'members.json', 'member_photos.json'}
            missing = required_entries - all_entries
            if missing:
                return False, f'Missing required files: {", ".join(sorted(missing))}'

            manifest = _read_json_entry(archive, 'manifest.json')
            members = _read_json_entry(archive, 'members.json')
            member_photos = _read_json_entry(archive, 'member_photos.json')

        if not isinstance(manifest, dict):
            return False, 'manifest.json must be a JSON object'
        if not isinstance(members, list):
            return False, 'members.json must be a JSON array'
        if not isinstance(member_photos, list):
            return False, 'member_photos.json must be a JSON array'

        schema_version = manifest.get('schemaVersion')
        try:
            schema_version = int(schema_version)
        except (TypeError, ValueError):
            return False, 'manifest.schemaVersion must be an integer'
        if schema_version < 1:
            return False, 'manifest.schemaVersion must be >= 1'

        counts = manifest.get('counts') if isinstance(manifest.get('counts'), dict) else {}
        created_at_utc = manifest.get('createdAtUtc') or datetime.utcnow().isoformat() + 'Z'
        metadata = {
            'schemaVersion': schema_version,
            'createdAtUtc': created_at_utc,
            'compression': manifest.get('compression', 'jpeg_1280_q80'),
            'membersCount': int(counts.get('members', len(members))),
            'memberPhotosCount': int(counts.get('memberPhotos', len(member_photos))),
            'assetsCount': int(counts.get('assets', len(asset_entries))),
        }
        return True, metadata
    except zipfile.BadZipFile:
        return False, 'File is not a valid ZIP archive'
    except UnicodeDecodeError:
        return False, 'Backup archive contains invalid UTF-8 JSON'
    except json.JSONDecodeError as exc:
        return False, f'Invalid JSON in backup archive: {exc.msg}'
    except Exception as exc:
        logger.exception("Backup archive validation failed")
        return False, f'Backup archive validation failed: {exc}'


def write_backup_meta(meta_path, metadata):
    temp_meta = Path(str(meta_path) + '.tmp')
    with open(temp_meta, 'w', encoding='utf-8') as meta_file:
        json.dump(metadata, meta_file, ensure_ascii=False, indent=2)
    os.replace(temp_meta, meta_path)


def load_backup_meta(meta_path):
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, 'r', encoding='utf-8') as meta_file:
            data = json.load(meta_file)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        logger.warning(f"Failed to read backup metadata {meta_path}: {exc}")
    return None


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
    img_hash = get_image_hash(image)
    if img_hash in face_detection_cache:
        logger.info("Использован кэш для обнаружения лиц")
        return face_detection_cache[img_hash]

    optimized_image = optimize_image_for_gpu(image)

    source_height, source_width = image.shape[:2]
    optimized_height, optimized_width = optimized_image.shape[:2]
    optimization_scale = 1.0
    if source_width > 0 and source_height > 0:
        width_ratio = optimized_width / source_width
        height_ratio = optimized_height / source_height
        optimization_scale = max(1e-6, min(width_ratio, height_ratio))

    if optimization_scale != 1.0:
        logger.info(
            f"Face detection scale: source={source_width}x{source_height}, "
            f"optimized={optimized_width}x{optimized_height}, ratio={optimization_scale:.4f}"
        )

    def run_face_detection(image_array, model_name, upsample_value, attempt_name):
        start_time = time.time()
        locations = face_recognition.face_locations(
            image_array,
            model=model_name,
            number_of_times_to_upsample=upsample_value
        )
        detection_time = time.time() - start_time
        logger.info(
            f"Обнаружение лиц [{attempt_name}]: {detection_time:.3f}s, "
            f"model={model_name}, upsample={upsample_value}, найдено={len(locations)}"
        )
        return locations

    def clamp_location(location):
        top, right, bottom, left = location
        top = max(0, min(source_height, int(round(top))))
        right = max(0, min(source_width, int(round(right))))
        bottom = max(0, min(source_height, int(round(bottom))))
        left = max(0, min(source_width, int(round(left))))
        if bottom <= top or right <= left:
            return None
        return top, right, bottom, left

    def upscale_image(image_array, scale):
        height, width = image_array.shape[:2]
        target_width = max(1, int(round(width * scale)))
        target_height = max(1, int(round(height * scale)))
        pil_image = Image.fromarray(image_array)
        upscaled = pil_image.resize((target_width, target_height), Image.LANCZOS)
        return np.array(upscaled)

    def detect_and_map(image_array, model_name, upsample_value, attempt_name, scale=1.0, offset_top=0, offset_left=0):
        detected_locations = run_face_detection(image_array, model_name, upsample_value, attempt_name)
        if len(detected_locations) == 0:
            return []

        mapped_locations = []
        for top, right, bottom, left in detected_locations:
            mapped = clamp_location((
                (top / scale + offset_top) / optimization_scale,
                (right / scale + offset_left) / optimization_scale,
                (bottom / scale + offset_top) / optimization_scale,
                (left / scale + offset_left) / optimization_scale
            ))
            if mapped is not None:
                mapped_locations.append(mapped)

        return mapped_locations

    def detect_on_source(image_array, model_name, upsample_value, attempt_name, scale=1.0, offset_top=0, offset_left=0):
        detected_locations = run_face_detection(image_array, model_name, upsample_value, attempt_name)
        if len(detected_locations) == 0:
            return []

        mapped_locations = []
        for top, right, bottom, left in detected_locations:
            mapped = clamp_location((
                top / scale + offset_top,
                right / scale + offset_left,
                bottom / scale + offset_top,
                left / scale + offset_left
            ))
            if mapped is not None:
                mapped_locations.append(mapped)

        return mapped_locations

    def map_location_from_rotated(location, rotation_k, original_height, original_width):
        top, right, bottom, left = location
        if bottom <= top or right <= left:
            return None

        corners = [
            (top, left),
            (top, right - 1),
            (bottom - 1, left),
            (bottom - 1, right - 1)
        ]

        mapped_points = []
        for y, x in corners:
            if rotation_k == 1:
                mapped_y, mapped_x = x, original_width - 1 - y
            elif rotation_k == 2:
                mapped_y, mapped_x = original_height - 1 - y, original_width - 1 - x
            elif rotation_k == 3:
                mapped_y, mapped_x = original_height - 1 - x, y
            else:
                mapped_y, mapped_x = y, x
            mapped_points.append((mapped_y, mapped_x))

        ys = [item[0] for item in mapped_points]
        xs = [item[1] for item in mapped_points]
        mapped_top = min(ys)
        mapped_bottom = max(ys) + 1
        mapped_left = min(xs)
        mapped_right = max(xs) + 1

        if mapped_bottom <= mapped_top or mapped_right <= mapped_left:
            return None

        mapped_top = max(0, min(original_height, mapped_top))
        mapped_right = max(0, min(original_width, mapped_right))
        mapped_bottom = max(0, min(original_height, mapped_bottom))
        mapped_left = max(0, min(original_width, mapped_left))

        if mapped_bottom <= mapped_top or mapped_right <= mapped_left:
            return None

        return mapped_top, mapped_right, mapped_bottom, mapped_left

    def detect_rotated_and_map(image_array, rotation_k, model_name, upsample_value, attempt_name, map_scale):
        rotated_image = np.ascontiguousarray(np.rot90(image_array, k=rotation_k))
        detected_locations = run_face_detection(rotated_image, model_name, upsample_value, attempt_name)
        if len(detected_locations) == 0:
            return []

        map_scale = max(1e-6, map_scale)
        image_height, image_width = image_array.shape[:2]
        mapped_locations = []
        for location in detected_locations:
            unrotated_location = map_location_from_rotated(
                location,
                rotation_k=rotation_k,
                original_height=image_height,
                original_width=image_width
            )
            if unrotated_location is None:
                continue

            mapped = clamp_location((
                unrotated_location[0] / map_scale,
                unrotated_location[1] / map_scale,
                unrotated_location[2] / map_scale,
                unrotated_location[3] / map_scale
            ))
            if mapped is not None:
                mapped_locations.append(mapped)

        return mapped_locations

    face_locations = detect_and_map(
        optimized_image,
        FACE_MODEL,
        NUMBER_OF_TIMES_TO_UPSAMPLE,
        'primary'
    )

    if len(face_locations) == 0 and FALLBACK_UPSAMPLE > NUMBER_OF_TIMES_TO_UPSAMPLE:
        face_locations = detect_and_map(
            optimized_image,
            FACE_MODEL,
            FALLBACK_UPSAMPLE,
            'fallback-upsample'
        )

    if len(face_locations) == 0 and FACE_MODEL == 'cnn':
        face_locations = detect_and_map(
            optimized_image,
            'hog',
            FALLBACK_UPSAMPLE,
            'fallback-hog'
        )

    # Retry on auto-contrast frame for low-contrast portraits.
    if len(face_locations) == 0:
        contrasted = np.array(ImageOps.autocontrast(Image.fromarray(optimized_image), cutoff=1))
        if contrasted.shape == optimized_image.shape:
            face_locations = detect_and_map(
                contrasted,
                FACE_MODEL,
                FALLBACK_UPSAMPLE,
                'fallback-autocontrast'
            )
            if len(face_locations) == 0 and FACE_MODEL == 'cnn':
                face_locations = detect_and_map(
                    contrasted,
                    'hog',
                    FALLBACK_UPSAMPLE,
                    'fallback-autocontrast-hog'
                )

    if len(face_locations) == 0:
        for scale in DETECTION_UPSCALE_FACTORS:
            upscaled_image = upscale_image(optimized_image, scale)
            for upsample_value in (0, 1):
                face_locations = detect_and_map(
                    upscaled_image,
                    FACE_MODEL,
                    upsample_value,
                    f'fallback-upscaled-{scale}-u{upsample_value}',
                    scale=scale
                )
                if len(face_locations) > 0:
                    break

                if FACE_MODEL == 'cnn':
                    face_locations = detect_and_map(
                        upscaled_image,
                        'hog',
                        upsample_value,
                        f'fallback-upscaled-hog-{scale}-u{upsample_value}',
                        scale=scale
                    )
                    if len(face_locations) > 0:
                        break

            if len(face_locations) > 0:
                break

    if len(face_locations) == 0:
        crop_specs = [
            ('center', 0.08, 0.12, 0.92, 0.88),
            ('upper_center', 0.00, 0.12, 0.78, 0.88),
        ]
        for crop_name, top_ratio, left_ratio, bottom_ratio, right_ratio in crop_specs:
            top = int(optimized_height * top_ratio)
            left = int(optimized_width * left_ratio)
            bottom = int(optimized_height * bottom_ratio)
            right = int(optimized_width * right_ratio)
            crop = optimized_image[top:bottom, left:right]
            if crop.size == 0:
                continue

            for scale in CROP_UPSCALE_FACTORS:
                upscaled_crop = upscale_image(crop, scale)
                for upsample_value in (0, 1):
                    face_locations = detect_and_map(
                        upscaled_crop,
                        FACE_MODEL,
                        upsample_value,
                        f'fallback-crop-{crop_name}-{scale}-u{upsample_value}',
                        scale=scale,
                        offset_top=top,
                        offset_left=left
                    )
                    if len(face_locations) > 0:
                        break

                    if FACE_MODEL == 'cnn':
                        face_locations = detect_and_map(
                            upscaled_crop,
                            'hog',
                            upsample_value,
                            f'fallback-crop-{crop_name}-hog-{scale}-u{upsample_value}',
                            scale=scale,
                            offset_top=top,
                            offset_left=left
                        )
                        if len(face_locations) > 0:
                            break

                if len(face_locations) > 0:
                    break

            if len(face_locations) > 0:
                break

    if len(face_locations) == 0:
        rotation_attempts = [
            (1, 'rot90ccw'),
            (3, 'rot90cw'),
            (2, 'rot180'),
        ]
        optimized_pixels = optimized_height * optimized_width
        rotation_upsamples = [FALLBACK_UPSAMPLE]
        if FALLBACK_UPSAMPLE < 3 and optimized_pixels <= EXTRA_UPSAMPLE_MAX_PIXELS:
            rotation_upsamples.append(FALLBACK_UPSAMPLE + 1)

        for rotation_k, rotation_name in rotation_attempts:
            for upsample_value in rotation_upsamples:
                face_locations = detect_rotated_and_map(
                    optimized_image,
                    rotation_k=rotation_k,
                    model_name=FACE_MODEL,
                    upsample_value=upsample_value,
                    attempt_name=f'fallback-{rotation_name}-u{upsample_value}',
                    map_scale=optimization_scale
                )
                if len(face_locations) > 0:
                    break

                if FACE_MODEL == 'cnn':
                    face_locations = detect_rotated_and_map(
                        optimized_image,
                        rotation_k=rotation_k,
                        model_name='hog',
                        upsample_value=upsample_value,
                        attempt_name=f'fallback-{rotation_name}-hog-u{upsample_value}',
                        map_scale=optimization_scale
                    )
                    if len(face_locations) > 0:
                        break

            if len(face_locations) > 0:
                break

    if len(face_locations) == 0 and optimization_scale < 0.999:
        source_pixels = source_height * source_width
        source_upsamples = [FALLBACK_UPSAMPLE]
        if NUMBER_OF_TIMES_TO_UPSAMPLE not in source_upsamples:
            source_upsamples.insert(0, NUMBER_OF_TIMES_TO_UPSAMPLE)
        if FALLBACK_UPSAMPLE < 3 and source_pixels <= EXTRA_UPSAMPLE_MAX_PIXELS:
            source_upsamples.append(FALLBACK_UPSAMPLE + 1)

        for upsample_value in source_upsamples:
            face_locations = detect_on_source(
                image,
                FACE_MODEL,
                upsample_value,
                f'fallback-fullres-u{upsample_value}'
            )
            if len(face_locations) > 0:
                break

            if FACE_MODEL == 'cnn':
                face_locations = detect_on_source(
                    image,
                    'hog',
                    upsample_value,
                    f'fallback-fullres-hog-u{upsample_value}'
                )
                if len(face_locations) > 0:
                    break

        if len(face_locations) == 0:
            rotation_attempts = [
                (1, 'fullres-rot90ccw'),
                (3, 'fullres-rot90cw'),
                (2, 'fullres-rot180'),
            ]
            for rotation_k, rotation_name in rotation_attempts:
                for upsample_value in source_upsamples:
                    face_locations = detect_rotated_and_map(
                        image,
                        rotation_k=rotation_k,
                        model_name=FACE_MODEL,
                        upsample_value=upsample_value,
                        attempt_name=f'fallback-{rotation_name}-u{upsample_value}',
                        map_scale=1.0
                    )
                    if len(face_locations) > 0:
                        break

                    if FACE_MODEL == 'cnn':
                        face_locations = detect_rotated_and_map(
                            image,
                            rotation_k=rotation_k,
                            model_name='hog',
                            upsample_value=upsample_value,
                            attempt_name=f'fallback-{rotation_name}-hog-u{upsample_value}',
                            map_scale=1.0
                        )
                        if len(face_locations) > 0:
                            break

                if len(face_locations) > 0:
                    break

    if len(face_detection_cache) >= CACHE_MAX_SIZE:
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
        image = ImageOps.exif_transpose(image)

        # Конвертируем в RGB если нужно
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Оптимизация размера для GPU - уменьшаем большие изображения
        width, height = image.size
        if max(width, height) > DECODE_MAX_IMAGE_SIZE:
            ratio = DECODE_MAX_IMAGE_SIZE / max(width, height)
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
        'backup': True,
        'members_count': len(face_encodings_db),
        'recent_events': events_list,
        'gpu': {
            'requested_cuda': USE_CUDA,
            'active_cuda': CUDA_ENABLED,
            'dlib_use_cuda': DLIB_USE_CUDA,
            'cuda_devices': CUDA_DEVICE_COUNT,
            'face_model': FACE_MODEL,
            'reason': '' if CUDA_ENABLED else CUDA_DISABLED_REASON
        }
    })


# ========================================
# BACKUP - Роуты
# ========================================

@app.route('/api/backup/upload', methods=['POST'])
@app.route('/backup/upload', methods=['POST'])
def upload_backup_archive():
    owner_sub, auth_error = require_google_auth()
    if auth_error is not None:
        return auth_error

    backup_file = request.files.get('backup_file')
    if backup_file is None:
        return _schema_error('Missing form file: backup_file', status=400)

    owner_dir, zip_path, meta_path = get_backup_paths(owner_sub)
    temp_file = tempfile.NamedTemporaryFile(
        prefix='backup_upload_',
        suffix='.zip.tmp',
        delete=False,
        dir=owner_dir
    )
    temp_path = Path(temp_file.name)
    temp_file.close()

    try:
        backup_file.save(temp_path)
        size_bytes = temp_path.stat().st_size

        if size_bytes <= 0:
            return _schema_error('Uploaded file is empty', status=400)

        if size_bytes > BACKUP_MAX_FILE_BYTES:
            return _schema_error(
                f'Backup exceeds max size of {BACKUP_MAX_FILE_MB} MB',
                status=413
            )

        is_valid, validation_data = validate_backup_archive(temp_path)
        if not is_valid:
            return _schema_error(validation_data, status=400)

        checksum = compute_file_sha256(temp_path)
        metadata = {
            'schemaVersion': int(validation_data['schemaVersion']),
            'createdAtUtc': validation_data['createdAtUtc'],
            'compression': validation_data['compression'],
            'sizeBytes': int(size_bytes),
            'membersCount': int(validation_data['membersCount']),
            'memberPhotosCount': int(validation_data['memberPhotosCount']),
            'assetsCount': int(validation_data['assetsCount']),
            'checksumSha256': checksum,
            'updatedAtUtc': datetime.utcnow().isoformat() + 'Z',
        }

        os.replace(temp_path, zip_path)
        write_backup_meta(meta_path, metadata)

        add_event('💾', f"Backup uploaded: {metadata['membersCount']} members", 'success')
        return make_response_json({
            'success': True,
            'exists': True,
            **metadata
        })
    except Exception as exc:
        logger.exception("Backup upload failed")
        return _schema_error(f'Backup upload failed: {exc}', status=500)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@app.route('/api/backup/meta', methods=['GET'])
@app.route('/backup/meta', methods=['GET'])
def backup_meta():
    owner_sub, auth_error = require_google_auth()
    if auth_error is not None:
        return auth_error

    _, zip_path, meta_path = get_backup_paths(owner_sub)
    if not zip_path.exists():
        return make_response_json({
            'success': True,
            'schemaVersion': BACKUP_SCHEMA_VERSION,
            'exists': False
        })

    metadata = load_backup_meta(meta_path)
    if metadata is None:
        is_valid, validation_data = validate_backup_archive(zip_path)
        if not is_valid:
            return _schema_error('Stored backup archive is invalid', status=500)

        metadata = {
            'schemaVersion': int(validation_data['schemaVersion']),
            'createdAtUtc': validation_data['createdAtUtc'],
            'compression': validation_data['compression'],
            'sizeBytes': int(zip_path.stat().st_size),
            'membersCount': int(validation_data['membersCount']),
            'memberPhotosCount': int(validation_data['memberPhotosCount']),
            'assetsCount': int(validation_data['assetsCount']),
            'checksumSha256': compute_file_sha256(zip_path),
            'updatedAtUtc': datetime.utcnow().isoformat() + 'Z',
        }
        write_backup_meta(meta_path, metadata)

    return make_response_json({
        'success': True,
        'exists': True,
        **metadata
    })


@app.route('/api/backup/download', methods=['GET'])
@app.route('/backup/download', methods=['GET'])
def backup_download():
    owner_sub, auth_error = require_google_auth()
    if auth_error is not None:
        return auth_error

    _, zip_path, _ = get_backup_paths(owner_sub)
    if not zip_path.exists():
        return _schema_error('Backup not found', status=404)

    return send_file(
        str(zip_path),
        mimetype='application/zip',
        as_attachment=True,
        download_name='familyone_backup_latest.zip',
        max_age=0
    )


@app.route('/api/backup', methods=['DELETE'])
@app.route('/backup', methods=['DELETE'])
def delete_backup_archive():
    owner_sub, auth_error = require_google_auth()
    if auth_error is not None:
        return auth_error

    _, zip_path, meta_path = get_backup_paths(owner_sub)
    deleted = False

    for file_path in (zip_path, meta_path):
        if file_path.exists():
            try:
                file_path.unlink()
                deleted = True
            except Exception as exc:
                logger.warning(f"Failed deleting backup file {file_path}: {exc}")

    return make_response_json({
        'success': True,
        'schemaVersion': BACKUP_SCHEMA_VERSION,
        'deleted': deleted
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
    logger.info(
        f"CUDA: {'включен' if CUDA_ENABLED else 'выключен'} "
        f"(requested={USE_CUDA}, dlib_cuda={DLIB_USE_CUDA}, devices={CUDA_DEVICE_COUNT})"
    )
    logger.info(f"CORS origins: {', '.join(CORS_ORIGINS)}")
    effective_max_mb = int(app.config.get('MAX_CONTENT_LENGTH', 0)) // (1024 * 1024)
    logger.info(f"MAX_CONTENT_LENGTH: {effective_max_mb} MB")
    logger.info(
        f"Backup: dir={BACKUP_STORAGE_DIR}, max_file={BACKUP_MAX_FILE_MB}MB, "
        f"max_uncompressed={BACKUP_MAX_UNCOMPRESSED_MB}MB, schema={BACKUP_SCHEMA_VERSION}"
    )
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

