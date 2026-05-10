# family_tree.py
# pip install reportlab pillow requests

import io
import os
import base64
import logging
import platform
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageDraw
import requests

logger = logging.getLogger(__name__)

# --------- Регистрация шрифтов с поддержкой кириллицы ---------

def _setup_fonts():
    """Регистрируем TTF-шрифты с поддержкой кириллицы.
    Без них Helvetica/Times в reportlab используют WinAnsiEncoding
    и русский текст превращается в мусор.
    """
    candidates = []

    if platform.system() == "Windows":
        win_fonts = os.environ.get("WINDIR", "C:/Windows") + "/Fonts"
        candidates += [
            (f"{win_fonts}/arial.ttf",
             f"{win_fonts}/arialbd.ttf",
             f"{win_fonts}/ariali.ttf"),
            (f"{win_fonts}/times.ttf",
             f"{win_fonts}/timesbd.ttf",
             f"{win_fonts}/timesi.ttf"),
        ]
    # Linux / WSL
    candidates += [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    ]
    # macOS
    candidates += [
        ("/Library/Fonts/Arial.ttf",
         "/Library/Fonts/Arial Bold.ttf",
         "/Library/Fonts/Arial Italic.ttf"),
    ]

    for regular, bold, italic in candidates:
        if not os.path.exists(regular):
            continue
        try:
            pdfmetrics.registerFont(TTFont("CustomFont", regular))
            reg_name = "CustomFont"

            if os.path.exists(bold):
                pdfmetrics.registerFont(TTFont("CustomBold", bold))
                bold_name = "CustomBold"
            else:
                bold_name = reg_name

            if os.path.exists(italic):
                pdfmetrics.registerFont(TTFont("CustomItalic", italic))
                italic_name = "CustomItalic"
            else:
                italic_name = reg_name

            logger.info("Loaded fonts: %s / %s / %s", regular, bold, italic)
            return reg_name, bold_name, italic_name
        except Exception as exc:
            logger.warning("Font registration failed for %s: %s", regular, exc)
            continue

    logger.warning("Cyrillic fonts not found, falling back to Helvetica (без кириллицы)")
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


FONT_REGULAR, FONT_BOLD, FONT_ITALIC = _setup_fonts()


# --------- Палитра ---------

BACKGROUND_COLOR = (0.99, 0.97, 0.92)
BACKGROUND_EDGE = (0.95, 0.93, 0.85)
CARD_FILL = (0.98, 0.96, 0.90)
CARD_BORDER_OUT = (0.60, 0.50, 0.30)
CARD_BORDER_IN = (0.75, 0.65, 0.45)
TEXT_MAIN = (0.25, 0.20, 0.10)
TEXT_SUB = (0.40, 0.35, 0.25)
TEXT_GRAY = (0.50, 0.45, 0.35)
LINE_COLOR = (0.50, 0.40, 0.30)
ROLE_COLOR = (0.20, 0.50, 0.30)
PURPLE = (0.50, 0.20, 0.70)
WHITE = (1, 1, 1)


# --------- Вспомогательные функции ---------

def get_role_name(role):
    roles = {
        "GRANDFATHER": "Дедушка",
        "GRANDMOTHER": "Бабушка",
        "FATHER": "Отец",
        "MOTHER": "Мать",
        "SON": "Сын",
        "DAUGHTER": "Дочь",
        "BROTHER": "Брат",
        "SISTER": "Сестра",
        "UNCLE": "Дядя",
        "AUNT": "Тётя",
        "NEPHEW": "Племянник",
        "NIECE": "Племянница",
        "GRANDSON": "Внук",
        "GRANDDAUGHTER": "Внучка",
        "OTHER": "Родственник",
    }
    return roles.get((role or "OTHER").upper(), "Родственник")


def format_social_roles(member):
    value = member.get("socialRoles")
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts)
    return str(value).strip()


def group_by_generation(members):
    gens = {
        "grandparents": [],
        "parents": [],
        "uncles": [],
        "children": [],
        "nephews": [],
        "grandchildren": [],
        "other": [],
    }
    role_map = {
        "GRANDFATHER": "grandparents", "GRANDMOTHER": "grandparents",
        "FATHER": "parents", "MOTHER": "parents",
        "UNCLE": "uncles", "AUNT": "uncles",
        "SON": "children", "DAUGHTER": "children",
        "BROTHER": "children", "SISTER": "children",
        "NEPHEW": "nephews", "NIECE": "nephews",
        "GRANDSON": "grandchildren", "GRANDDAUGHTER": "grandchildren",
        "OTHER": "other",
    }
    for m in members:
        role = (m.get("role") or "OTHER").upper()
        gens[role_map.get(role, "other")].append(m)
    return gens


def get_gender_order(role):
    male = {"GRANDFATHER", "FATHER", "SON", "BROTHER", "UNCLE", "NEPHEW", "GRANDSON"}
    female = {"GRANDMOTHER", "MOTHER", "DAUGHTER", "SISTER", "AUNT", "NIECE", "GRANDDAUGHTER"}
    role = (role or "OTHER").upper()
    if role in male:
        return 1
    if role in female:
        return 2
    return 3


def find_couples(gen_members, all_members):
    couples = []
    ids_in_gen = {m["id"] for m in gen_members}
    for child in all_members:
        fid = child.get("fatherId")
        mid = child.get("motherId")
        if fid and mid and fid in ids_in_gen and mid in ids_in_gen:
            pair = (fid, mid)
            if pair not in couples:
                couples.append(pair)
    if not couples:
        males = [m for m in gen_members if get_gender_order(m.get("role", "OTHER")) == 1]
        females = [m for m in gen_members if get_gender_order(m.get("role", "OTHER")) == 2]
        for i, male in enumerate(males):
            if i < len(females):
                couples.append((male["id"], females[i]["id"]))
    return couples


def sort_as_couples(gen_members, all_members):
    if len(gen_members) <= 1:
        return list(gen_members)
    couples = find_couples(gen_members, all_members)
    result = []
    used = set()
    for mid, fid in couples:
        male = next((m for m in gen_members if m["id"] == mid), None)
        female = next((m for m in gen_members if m["id"] == fid), None)
        if male and male["id"] not in used:
            result.append(male)
            used.add(male["id"])
        if female and female["id"] not in used:
            result.append(female)
            used.add(female["id"])
    remaining = [m for m in gen_members if m["id"] not in used]
    remaining.sort(key=lambda m: get_gender_order(m.get("role", "OTHER")))
    result.extend(remaining)
    return result


def fit_text_canvas(c, text, font_name, font_size, max_width):
    """Обрезает текст по реальной ширине canvas, а не по количеству символов."""
    text = text or ""
    if not text:
        return ""
    if c.stringWidth(text, font_name, font_size) <= max_width:
        return text
    suffix = "…"
    while len(text) > 1 and c.stringWidth(text + suffix, font_name, font_size) > max_width:
        text = text[:-1]
    return text + suffix


# --------- Фон и заголовок ---------

def draw_beautiful_background(c, width, height):
    # Лёгкая градиентная заливка: пергамент
    c.setFillColorRGB(*BACKGROUND_COLOR)
    c.rect(0, 0, width, height, stroke=0, fill=1)

    # Тонкая рамка по периметру
    c.setStrokeColorRGB(*BACKGROUND_EDGE)
    c.setLineWidth(2)
    c.rect(18, 18, width - 36, height - 36, stroke=1, fill=0)

    # Декоративные уголки
    corner = 40
    c.setStrokeColorRGB(*CARD_BORDER_OUT)
    c.setLineWidth(1.2)
    for cx, cy, dx, dy in (
        (24, 24, 1, 1),
        (width - 24, 24, -1, 1),
        (24, height - 24, 1, -1),
        (width - 24, height - 24, -1, -1),
    ):
        c.line(cx, cy + dy * 2, cx + dx * corner, cy + dy * 2)
        c.line(cx + dx * 2, cy, cx + dx * 2, cy + dy * corner)


def draw_header(c, width, height, title):
    header_h = 70
    y = height - header_h

    # Плашка заголовка
    c.setFillColorRGB(0.97, 0.94, 0.87)
    c.setStrokeColorRGB(*CARD_BORDER_OUT)
    c.setLineWidth(1.5)
    pad = 60
    c.roundRect(pad, y, width - 2 * pad, header_h - 10, 8, fill=1, stroke=1)

    c.setFillColorRGB(*TEXT_MAIN)
    c.setFont(FONT_BOLD, 22)
    c.drawCentredString(width / 2, y + header_h - 35, title or "Семейное древо")

    c.setFillColorRGB(*TEXT_SUB)
    c.setFont(FONT_ITALIC, 10)
    c.drawCentredString(width / 2, y + 12, "~ Семейное древо ~")

    return header_h


def draw_gen_label(c, name, width, y):
    text_w = c.stringWidth(name, FONT_ITALIC, 11) + 40
    x = (width - text_w) / 2

    c.setFillColorRGB(0.95, 0.92, 0.83)
    c.setStrokeColorRGB(*CARD_BORDER_IN)
    c.setLineWidth(0.8)
    c.roundRect(x, y - 10, text_w, 20, 6, fill=1, stroke=1)

    c.setFillColorRGB(*TEXT_SUB)
    c.setFont(FONT_ITALIC, 11)
    c.drawCentredString(width / 2, y - 4, name)


def draw_footer(c, width):
    c.setFillColorRGB(*TEXT_GRAY)
    c.setFont(FONT_REGULAR, 9)
    date_str = datetime.now().strftime("%d.%m.%Y")
    c.drawCentredString(width / 2, 18, f"Дата создания: {date_str}")


# --------- Фото и аватар ---------

def _load_image(photo_data):
    if not photo_data:
        return None
    try:
        data = photo_data.strip()
        if "," in data and data.startswith("data:"):
            data = data.split(",", 1)[1]
            raw = base64.b64decode(data)
        elif data.startswith(("http://", "https://")):
            resp = requests.get(data, timeout=5)
            resp.raise_for_status()
            raw = resp.content
        else:
            raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw))
        return img.convert("RGBA")
    except Exception as exc:
        logger.debug("Failed to load photo: %s", exc)
        return None


def draw_photo(c, photo_data, x, y, size):
    img = _load_image(photo_data)
    if img is None:
        draw_avatar(c, x, y, size)
        return

    # обрезаем в квадрат по центру
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((int(size * 3), int(size * 3)), Image.LANCZOS)

    # круглая маска
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, img.size[0], img.size[1]), fill=255)
    out = Image.new("RGBA", img.size, (255, 255, 255, 0))
    out.paste(img, (0, 0))
    out.putalpha(mask)

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)

    # фиолетовая рамка
    c.setFillColorRGB(*PURPLE)
    c.circle(x + size / 2, y + size / 2, size / 2 + 2.5, fill=1, stroke=0)

    # белый фон (чтобы прозрачность не сквозила)
    c.setFillColorRGB(*WHITE)
    c.circle(x + size / 2, y + size / 2, size / 2, fill=1, stroke=0)

    c.drawImage(ImageReader(buf), x, y, size, size, mask="auto")


def draw_avatar(c, x, y, size):
    cx, cy = x + size / 2, y + size / 2

    # фиолетовая рамка
    c.setFillColorRGB(*PURPLE)
    c.circle(cx, cy, size / 2 + 2.5, fill=1, stroke=0)

    # круг-подложка
    c.setFillColorRGB(0.92, 0.90, 0.96)
    c.circle(cx, cy, size / 2, fill=1, stroke=0)

    # иконка человечка
    c.setFillColorRGB(*TEXT_GRAY)
    c.circle(cx, cy + size * 0.12, size * 0.18, fill=1, stroke=0)
    c.ellipse(cx - size * 0.28, cy - size * 0.40,
              cx + size * 0.28, cy - size * 0.05, fill=1, stroke=0)


# --------- Карточка ---------

def draw_member_card(c, member, x, y, w, h, settings):
    show_photos = settings.get("showPhotos", True)
    show_dates = settings.get("showDates", True)
    show_patronymic = settings.get("showPatronymic", True)

    s = w / 130.0  # масштаб относительно базовой ширины 130
    inset = max(3, int(4 * s))

    # Тень
    c.setFillColorRGB(0.70, 0.65, 0.55)
    c.roundRect(x + 3, y - 3, w, h, 8, fill=1, stroke=0)

    # Фон карточки
    c.setFillColorRGB(*CARD_FILL)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=0)

    # Внешняя рамка
    c.setStrokeColorRGB(*CARD_BORDER_OUT)
    c.setLineWidth(max(1, 1.8 * s))
    c.roundRect(x, y, w, h, 8, fill=0, stroke=1)

    # Внутренняя рамка
    c.setStrokeColorRGB(*CARD_BORDER_IN)
    c.setLineWidth(1)
    c.roundRect(x + inset, y + inset, w - 2 * inset, h - 2 * inset, 5, fill=0, stroke=1)

    curr_y = y + h - max(8, int(10 * s))

    # --- Фото ---
    if show_photos:
        photo_size = max(25, int(w * 0.38))
        photo_x = x + (w - photo_size) / 2
        photo_y = curr_y - photo_size
        photo_data = member.get("photoBase64") or member.get("photoUri")
        try:
            draw_photo(c, photo_data, photo_x, photo_y, photo_size)
        except Exception as exc:
            logger.debug("Photo fallback for %s: %s", member.get("id"), exc)
            draw_avatar(c, photo_x, photo_y, photo_size)
        curr_y = photo_y - max(4, int(5 * s))

    # адаптивные размеры шрифтов
    name_font = max(7, min(11, int(9 * s)))
    detail_font = max(6, min(9, int(8 * s)))
    role_font = max(7, min(11, int(10 * s)))

    max_text_w = w - 2 * inset - 4

    # --- ФИО ---
    last = (member.get("lastName") or "").strip()
    first = (member.get("firstName") or "").strip()
    name = f"{last} {first}".strip()
    name = fit_text_canvas(c, name, FONT_BOLD, name_font, max_text_w)
    c.setFillColorRGB(*TEXT_MAIN)
    c.setFont(FONT_BOLD, name_font)
    c.drawCentredString(x + w / 2, curr_y, name)
    curr_y -= name_font + 2

    # --- Отчество ---
    if show_patronymic:
        patronymic = (member.get("patronymic") or "").strip()
        if patronymic:
            patronymic = fit_text_canvas(c, patronymic, FONT_REGULAR, detail_font, max_text_w)
            c.setFillColorRGB(*TEXT_SUB)
            c.setFont(FONT_REGULAR, detail_font)
            c.drawCentredString(x + w / 2, curr_y, patronymic)
            curr_y -= detail_font + 1

    # --- Роль ---
    role = get_role_name(member.get("role", "OTHER"))
    c.setFillColorRGB(*ROLE_COLOR)
    c.setFont(FONT_ITALIC, role_font)
    c.drawCentredString(x + w / 2, curr_y, role)
    curr_y -= role_font + 1

    # --- Социальные роли ---
    social = format_social_roles(member)
    if social and curr_y > y + inset + detail_font:
        social = fit_text_canvas(c, social, FONT_REGULAR, detail_font, max_text_w)
        c.setFillColorRGB(0.35, 0.28, 0.18)
        c.setFont(FONT_REGULAR, detail_font)
        c.drawCentredString(x + w / 2, curr_y, social)
        curr_y -= detail_font + 1

    # --- Даты ---
    if show_dates:
        birth = (member.get("birthDate") or "").strip()
        death = (member.get("deathDate") or "").strip()
        if birth or death:
            if birth and death:
                date_line = f"{birth}  —  {death}"
            elif birth:
                date_line = birth
            else:
                date_line = f"✝ {death}"
            date_line = fit_text_canvas(c, date_line, FONT_REGULAR, detail_font, max_text_w)
            c.setFillColorRGB(*TEXT_GRAY)
            c.setFont(FONT_REGULAR, detail_font)
            c.drawCentredString(x + w / 2, curr_y, date_line)


# --------- Связи ---------

def draw_tree_line(c, x1, y1, x2, y2):
    """Линия от родителя (x1,y1) к ребёнку (x2,y2)."""
    mid_y = (y1 + y2) / 2
    c.setStrokeColorRGB(*LINE_COLOR)
    c.setLineWidth(1.5)
    c.line(x1, y1, x1, mid_y)
    c.line(min(x1, x2), mid_y, max(x1, x2), mid_y)
    c.line(x2, mid_y, x2, y2)
    # маркер у ребёнка
    c.setFillColorRGB(*PURPLE)
    c.circle(x2, y2, 3, fill=1, stroke=0)


def draw_connections(c, positions, members):
    drawn = set()
    for member in members:
        mid = member.get("id")
        if mid not in positions:
            continue
        child = positions[mid]
        for parent_id in (member.get("fatherId"), member.get("motherId")):
            if not parent_id or parent_id not in positions:
                continue
            pair = tuple(sorted((mid, parent_id)))
            if pair in drawn:
                continue
            parent = positions[parent_id]
            draw_tree_line(
                c,
                parent["xcenter"], parent["ybottom"],
                child["xcenter"], child["ytop"],
            )
            drawn.add(pair)


# --------- Рендер страницы ---------

GEN_ORDER = [
    ("grandparents", "Бабушки и Дедушки"),
    ("parents", "Родители"),
    ("uncles", "Дяди и Тёти"),
    ("children", "Дети"),
    ("nephews", "Племянники"),
    ("grandchildren", "Внуки"),
    ("other", "Другие"),
]


def _draw_single_page(c, members, width, height, active, gens, settings):
    margin_x = 40
    header_h = 80
    footer_h = 40
    gen_label_h = 28
    usable_width = width - 2 * margin_x
    usable_height = height - header_h - footer_h - 20

    max_in_row = max((len(gens[k]) for k, _ in active), default=1)
    min_card_w = 90
    min_gap = 12

    # Ширина карточки
    ideal_card_w = min(140, max(min_card_w, (usable_width - (max_in_row - 1) * min_gap) / max(max_in_row, 1)))
    card_gap_x = min(20, max(min_gap, ideal_card_w * 0.12))

    max_per_row = max(1, int((usable_width + card_gap_x) / (min_card_w + card_gap_x)))
    needs_wrap = any(len(gens[k]) > max_per_row for k, _ in active)
    card_width = ideal_card_w if not needs_wrap else max(
        min_card_w,
        (usable_width - (min(max_in_row, max_per_row) - 1) * card_gap_x) / min(max_in_row, max_per_row),
    )

    # Высота карточки по содержимому
    show_photos = settings.get("showPhotos", True)
    show_patronymic = settings.get("showPatronymic", True)
    show_dates = settings.get("showDates", True)

    s = card_width / 130.0
    top_pad = max(8, int(10 * s))
    bottom_pad = max(6, int(8 * s))
    name_h = max(7, min(11, int(9 * s))) + 2
    role_h = max(7, min(11, int(10 * s))) + 1
    detail_h = max(6, min(9, int(8 * s))) + 1

    content_h = top_pad + name_h + role_h + bottom_pad + detail_h  # + social roles
    if show_photos:
        content_h += max(25, int(card_width * 0.38)) + max(4, int(5 * s))
    if show_patronymic:
        content_h += detail_h
    if show_dates:
        content_h += detail_h

    card_height = int(content_h)

    def rows_for(key):
        n = len(gens[key])
        if n == 0:
            return 0
        return (n + max_per_row - 1) // max_per_row

    total_rows = sum(rows_for(k) for k, _ in active)
    gen_gap_y = 30
    row_gap = 8
    total_content_h = (
        total_rows * card_height
        + max(0, total_rows - 1) * row_gap
        + len(active) * gen_label_h
        + max(0, len(active) - 1) * gen_gap_y
    )

    if total_content_h > usable_height:
        scale = usable_height / total_content_h
        if scale < 0.55:
            return False  # не помещается, нужна многостраничность
        card_height = max(60, int(card_height * scale))
        card_width = max(80, int(card_width * scale))
        card_gap_x = max(8, int(card_gap_x * scale))
        gen_gap_y = max(10, int(gen_gap_y * scale))

    # --- Отрисовка ---
    draw_beautiful_background(c, width, height)
    header_height = draw_header(c, width, height, settings.get("title", "Семейное Древо"))

    positions = {}
    current_y = height - header_height - 15

    for _, (gen_key, gen_name) in enumerate(active):
        gen_members = sort_as_couples(gens[gen_key], members)

        current_y -= gen_label_h
        draw_gen_label(c, gen_name, width, current_y + 8)
        current_y -= 4

        # разбиваем на ряды
        rows = [gen_members[i:i + max_per_row] for i in range(0, len(gen_members), max_per_row)]
        for row in rows:
            num = len(row)
            total_w = num * card_width + (num - 1) * card_gap_x
            start_x = (width - total_w) / 2
            for i, member in enumerate(row):
                x = start_x + i * (card_width + card_gap_x)
                y = current_y - card_height
                draw_member_card(c, member, x, y, card_width, card_height, settings)
                positions[member["id"]] = {
                    "xcenter": x + card_width / 2,
                    "ytop": y + card_height,
                    "ybottom": y,
                }
            current_y -= card_height + row_gap

        current_y -= gen_gap_y

    draw_connections(c, positions, members)
    draw_footer(c, width)
    return True


def _draw_multipage(c, members, width, height, active, gens, settings):
    """Многостраничный режим: фиксированный размер карточек, переносы."""
    margin_x = 40
    header_h = 80
    footer_h = 40
    gen_label_h = 28

    usable_width = width - 2 * margin_x

    max_in_row_raw = max((len(gens[k]) for k, _ in active), default=1)
    max_per_row = max(1, int((usable_width + 12) / (110 + 12)))
    card_width = min(
        140,
        max(100, (usable_width - (min(max_in_row_raw, max_per_row) - 1) * 15)
            / min(max_in_row_raw, max_per_row)),
    )
    card_gap_x = min(20, max(10, card_width * 0.12))
    card_height = int(card_width * 1.12)
    if not settings.get("showPhotos", True):
        card_height = int(card_width * 0.7)
    gen_gap_y = 25
    row_gap = 8

    all_rows = []
    for gen_key, gen_name in active:
        gen_members = sort_as_couples(gens[gen_key], members)
        rows = [gen_members[i:i + max_per_row] for i in range(0, len(gen_members), max_per_row)]
        all_rows.append((gen_name, rows))

    positions = {}
    page_num = 0
    gen_index = 0
    row_index = 0
    title = settings.get("title", "Семейное Древо")

    while gen_index < len(all_rows):
        if page_num > 0:
            c.showPage()
        draw_beautiful_background(c, width, height)
        page_title = title if page_num == 0 else f"{title} (стр. {page_num + 1})"
        header_height = draw_header(c, width, height, page_title)
        cur_y = height - header_height - 10
        page_bottom = footer_h + 20

        while gen_index < len(all_rows):
            gen_name, rows = all_rows[gen_index]

            needed = gen_label_h + card_height + row_gap
            if cur_y - needed < page_bottom and cur_y < height - header_height - 50:
                break  # переход на новую страницу

            cur_y -= gen_label_h
            draw_gen_label(c, gen_name, width, cur_y + 8)
            cur_y -= 4

            while row_index < len(rows):
                row = rows[row_index]
                if cur_y - card_height - row_gap < page_bottom:
                    break
                num = len(row)
                total_w = num * card_width + (num - 1) * card_gap_x
                start_x = (width - total_w) / 2
                for i, member in enumerate(row):
                    x = start_x + i * (card_width + card_gap_x)
                    y = cur_y - card_height
                    draw_member_card(c, member, x, y, card_width, card_height, settings)
                    positions[member["id"]] = {
                        "xcenter": x + card_width / 2,
                        "ytop": y + card_height,
                        "ybottom": y,
                    }
                cur_y -= card_height + row_gap
                row_index += 1

            if row_index >= len(rows):
                cur_y -= gen_gap_y
                gen_index += 1
                row_index = 0
            else:
                break

        draw_connections(c, positions, members)
        draw_footer(c, width)
        page_num += 1


def draw_family_tree(c, members, width, height, settings):
    gens = group_by_generation(members)
    active = [(k, name) for k, name in GEN_ORDER if gens.get(k)]
    if not active:
        return

    # Пробуем одностраничный режим, если не помещается - рендерим заново многостраничным
    if not _draw_single_page(c, members, width, height, active, gens, settings):
        _draw_multipage(c, members, width, height, active, gens, settings)


def render_family_tree_pdf(members, filename, title="Семейное Древо",
                           page_format="A4_LANDSCAPE",
                           show_photos=True, show_dates=True, show_patronymic=True):
    pagesize = {
        "A4": A4,
        "A4_LANDSCAPE": landscape(A4),
        "A3": A3,
        "A3_LANDSCAPE": landscape(A3),
    }.get(page_format, landscape(A4))

    settings = {
        "showPhotos": show_photos,
        "showDates": show_dates,
        "showPatronymic": show_patronymic,
        "title": title,
    }

    c = canvas.Canvas(filename, pagesize=pagesize)
    width, height = pagesize
    draw_family_tree(c, members, width, height, settings)
    c.save()


# --------- Пример использования ---------

if __name__ == "__main__":
    sample_members = [
        {"id": "1", "firstName": "Иван", "lastName": "Иванов", "patronymic": "Петрович",
         "role": "GRANDFATHER", "birthDate": "1940", "deathDate": "",
         "socialRoles": ["ветеран", "инженер"]},
        {"id": "2", "firstName": "Мария", "lastName": "Иванова", "patronymic": "Сергеевна",
         "role": "GRANDMOTHER", "birthDate": "1945", "socialRoles": ["учитель"]},
        {"id": "3", "firstName": "Пётр", "lastName": "Иванов", "patronymic": "Иванович",
         "role": "FATHER", "birthDate": "1970", "socialRoles": ["программист"],
         "fatherId": "1", "motherId": "2"},
        {"id": "4", "firstName": "Анна", "lastName": "Иванова", "patronymic": "Алексеевна",
         "role": "MOTHER", "birthDate": "1972"},
        {"id": "5", "firstName": "Дмитрий", "lastName": "Иванов", "patronymic": "Петрович",
         "role": "SON", "birthDate": "2000", "fatherId": "3", "motherId": "4"},
        {"id": "6", "firstName": "Ольга", "lastName": "Иванова", "patronymic": "Петровна",
         "role": "DAUGHTER", "birthDate": "2005", "fatherId": "3", "motherId": "4"},
    ]

    render_family_tree_pdf(
        sample_members,
        "family_tree_demo.pdf",
        title="Семейное древо семьи Ивановых",
        page_format="A4_LANDSCAPE",
    )
    print("PDF generated: family_tree_demo.pdf")
