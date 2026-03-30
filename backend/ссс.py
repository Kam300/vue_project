# family_tree.py
# pip install reportlab pillow requests

import io
import base64
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from PIL import Image
import requests

# --------- Конфиг шрифтов и цветов ---------

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

BACKGROUND_COLOR = (0.99, 0.97, 0.92)
CARD_FILL = (0.97, 0.94, 0.88)
CARD_BORDER = (0.6, 0.5, 0.3)
TEXT_MAIN = (0.25, 0.2, 0.1)
TEXT_GRAY = (0.5, 0.45, 0.35)
LINE_COLOR = (0.5, 0.4, 0.3)
PURPLE = (0.5, 0.2, 0.7)


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
    return roles.get(role or "OTHER", "Родственник")


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
    rolemap = {
        "GRANDFATHER": "grandparents",
        "GRANDMOTHER": "grandparents",
        "FATHER": "parents",
        "MOTHER": "parents",
        "UNCLE": "uncles",
        "AUNT": "uncles",
        "SON": "children",
        "DAUGHTER": "children",
        "BROTHER": "children",
        "SISTER": "children",
        "NEPHEW": "nephews",
        "NIECE": "nephews",
        "GRANDSON": "grandchildren",
        "GRANDDAUGHTER": "grandchildren",
        "OTHER": "other",
    }
    for m in members:
        role = (m.get("role") or "OTHER").upper()
        gen = rolemap.get(role, "other")
        gens[gen].append(m)
    return gens


def get_gender_order(role):
    maleroles = {"GRANDFATHER", "FATHER", "SON", "BROTHER", "UNCLE", "NEPHEW", "GRANDSON"}
    femaleroles = {"GRANDMOTHER", "MOTHER", "DAUGHTER", "SISTER", "AUNT", "NIECE", "GRANDDAUGHTER"}
    if role in maleroles:
        return 1
    if role in femaleroles:
        return 2
    return 3


def find_couples(gen_members, all_members):
    # Пара = отец+мать ребёнка, оба в текущем поколении
    couples = []
    member_ids = {m["id"] for m in gen_members}
    for child in all_members:
        fid = child.get("fatherId")
        mid = child.get("motherId")
        if fid and mid and fid in member_ids and mid in member_ids:
            couple = (fid, mid)
            if couple not in couples:
                couples.append(couple)
    # Если пар не нашли — пытаемся собрать по полу
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
    used_ids = set()
    for mid, fid in couples:
        male = next((m for m in gen_members if m["id"] == mid), None)
        female = next((m for m in gen_members if m["id"] == fid), None)
        if male and male["id"] not in used_ids:
            result.append(male)
            used_ids.add(male["id"])
        if female and female["id"] not in used_ids:
            result.append(female)
            used_ids.add(female["id"])
    remaining = [m for m in gen_members if m["id"] not in used_ids]
    remaining.sort(key=lambda m: get_gender_order(m.get("role", "OTHER")))
    result.extend(remaining)
    return result


def fit_text(text, max_chars):
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


# --------- Отрисовка базовых элементов ---------

def draw_beautiful_background(c, width, height):
    c.setFillColorRGB(*BACKGROUND_COLOR)
    c.rect(0, 0, width, height, stroke=0, fill=1)


def draw_header(c, width, height, title):
    c.setFillColorRGB(*TEXT_MAIN)
    c.setFont(FONT_BOLD, 20)
    c.drawCentredString(width / 2, height - 40, title or "Семейное древо")


def draw_footer(c, width):
    c.setFillColorRGB(*TEXT_GRAY)
    c.setFont(FONT_REGULAR, 9)
    datestr = datetime.now().strftime("%d.%m.%Y")
    c.drawCentredString(width / 2, 15, f"Сгенерировано {datestr}")


def draw_avatar(c, x, y, size):
    cx, cy = x + size / 2, y + size / 2
    c.setFillColorRGB(0.8, 0.75, 0.6)
    c.circle(cx, cy, size * 0.48, stroke=0, fill=1)
    c.setFillColorRGB(0.6, 0.5, 0.3)
    c.circle(cx, cy + size * 0.13, size * 0.2, stroke=0, fill=1)
    c.ellipse(cx - size * 0.25, cy - size * 0.2, cx + size * 0.25, cy - size * 0.45, stroke=0, fill=1)


def load_image_from_any(photodata):
    if not photodata:
        return None
    try:
        if "," in photodata and photodata.strip().startswith("data:"):
            _, data = photodata.split(",", 1)
            imgdata = base64.b64decode(data)
        elif photodata.strip().startswith(("http://", "https://")):
            resp = requests.get(photodata, timeout=5)
            resp.raise_for_status()
            imgdata = resp.content
        else:
            imgdata = base64.b64decode(photodata)
        img = Image.open(io.BytesIO(imgdata))
        return img.convert("RGBA")
    except Exception:
        return None


def draw_photo(c, photodata, x, y, size):
    img = load_image_from_any(photodata)
    if not img:
        draw_avatar(c, x, y, size)
        return
    iw, ih = img.size
    scale = min(size / iw, size / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    ir = ImageReader(buf)
    c.drawImage(ir, x + (size - nw) / 2, y + (size - nh) / 2, width=nw, height=nh, mask="auto")


def draw_member_card(c, member, x, y, w, h, settings):
    show_photos = settings.get("showPhotos", True)
    show_dates = settings.get("showDates", True)
    show_patronymic = settings.get("showPatronymic", True)

    # фон и рамка
    c.setFillColorRGB(*CARD_FILL)
    c.setStrokeColorRGB(*CARD_BORDER)
    c.roundRect(x, y, w, h, 10, stroke=1, fill=1)

    inset = 6
    curry = y + h - inset

    # Имя
    last = member.get("lastName") or ""
    first = member.get("firstName") or ""
    name = f"{last} {first}".strip()
    name = fit_text(name, 28)
    name_font = 11
    c.setFillColorRGB(*TEXT_MAIN)
    c.setFont(FONT_BOLD, name_font)
    c.drawCentredString(x + w / 2, curry, name)
    curry -= name_font + 2

    # Отчество
    if show_patronymic:
        patronymic = (member.get("patronymic") or "").strip()
        if patronymic:
            patronymic = fit_text(patronymic, 26)
            detail_font = 9
            c.setFillColorRGB(0.4, 0.35, 0.25)
            c.setFont(FONT_REGULAR, detail_font)
            c.drawCentredString(x + w / 2, curry, patronymic)
            curry -= detail_font + 1

    # Роль
    role_name = get_role_name(member.get("role", "OTHER"))
    role_font = 9
    c.setFillColorRGB(0.2, 0.5, 0.3)
    c.setFont(FONT_ITALIC, role_font)
    c.drawCentredString(x + w / 2, curry, role_name)
    curry -= role_font + 1

    # Социальные роли
    social = format_social_roles(member)
    if social:
        social = fit_text(social, 30)
        detail_font = 8
        if curry > y + inset + detail_font:
            c.setFillColorRGB(0.35, 0.28, 0.18)
            c.setFont(FONT_REGULAR, detail_font)
            c.drawCentredString(x + w / 2, curry, social)
            curry -= detail_font + 1

    # Даты
    if show_dates:
        birth = (member.get("birthDate") or "").strip()
        death = (member.get("deathDate") or "").strip()
        if birth or death:
            text = ""
            if birth:
                text += f"р. {birth}"
            if death:
                text += f"  ✝ {death}"
            text = fit_text(text, 30)
            detail_font = 8
            c.setFillColorRGB(*TEXT_GRAY)
            c.setFont(FONT_REGULAR, detail_font)
            c.drawCentredString(x + w / 2, curry, text)
            curry -= detail_font + 1

    # Фото
    if show_photos:
        photosize = int(w * 0.38)
        photox = x + (w - photosize) / 2
        photoy = y + inset
        photodata = member.get("photoBase64") or member.get("photoUri")
        try:
            draw_photo(c, photodata, photox, photoy, photosize)
        except Exception:
            draw_avatar(c, photox, photoy, photosize)


def draw_tree_line(c, x1, y1, x2, y2):
    midy = (y1 + y2) / 2
    c.setStrokeColorRGB(*LINE_COLOR)
    c.setLineWidth(1.4)
    # вертикаль от ребёнка вверх
    c.line(x1, y1, x1, midy)
    # вертикаль от родителя вниз
    c.line(x2, y2, x2, midy)
    # соединяющая горизонталь
    c.line(min(x1, x2), midy, max(x1, x2), midy)
    # маленький маркер у ребёнка
    c.setFillColorRGB(*PURPLE)
    c.circle(x1, y1, 2.5, fill=1, stroke=0)


def draw_connections(c, positions, members):
    drawn_pairs = set()
    for member in members:
        mid = member["id"]
        if mid not in positions:
            continue
        child = positions[mid]
        cx, ctop = child["xcenter"], child["ytop"]
        father_id = member.get("fatherId")
        mother_id = member.get("motherId")

        if father_id and father_id in positions:
            pair = tuple(sorted((mid, father_id)))
            if pair not in drawn_pairs:
                parent = positions[father_id]
                draw_tree_line(c, cx, ctop, parent["xcenter"], parent["ybottom"])
                drawn_pairs.add(pair)

        if mother_id and mother_id in positions:
            pair = tuple(sorted((mid, mother_id)))
            if pair not in drawn_pairs:
                parent = positions[mother_id]
                draw_tree_line(c, cx, ctop, parent["xcenter"], parent["ybottom"])
                drawn_pairs.add(pair)


# --------- Основной рендеринг ---------

def draw_family_tree_single_page(c, members, width, height, settings):
    gens = group_by_generation(members)
    gen_order = [
        ("grandparents", "Бабушки и дедушки"),
        ("parents", "Родители"),
        ("uncles", "Дяди и тёти"),
        ("children", "Дети, братья, сёстры"),
        ("nephews", "Племянники и племянницы"),
        ("grandchildren", "Внуки"),
        ("other", "Прочие"),
    ]
    active = [(k, name) for k, name in gen_order if gens.get(k)]

    if not active:
        return

    margin_x = 40
    header_h = 80
    footer_h = 40
    gen_label_h = 24

    usable_width = width - 2 * margin_x
    usable_height = height - header_h - footer_h - 20

    # оценка сетки
    max_in_row = max(len(gens[k]) for k, _ in active)
    min_card_w = 110
    min_gap = 12
    max_cards_per_row = max(1, int((usable_width + min_gap) / (min_card_w + min_gap)))

    def rows_for_gen(k):
        n = len(gens[k])
        if n == 0:
            return 0
        return (n + max_cards_per_row - 1) // max_cards_per_row

    total_rows = sum(rows_for_gen(k) for k, _ in active)
    card_width = min(160, max(min_card_w, (usable_width - (max_cards_per_row - 1) * min_gap) / max_cards_per_row))
    card_height = int(card_width * 1.15)
    row_gap = 8
    gen_gap_y = 26

    total_content_h = total_rows * card_height + (total_rows - 1) * row_gap + len(active) * gen_label_h + (len(active) - 1) * gen_gap_y
    scale = min(1.0, usable_height / total_content_h)
    if scale < 0.55:
        scale = 0.55

    card_width = max(90, int(card_width * scale))
    card_height = max(60, int(card_height * scale))
    row_gap = max(6, int(row_gap * scale))
    gen_gap_y = max(12, int(gen_gap_y * scale))

    max_cards_per_row = max(1, int((usable_width + min_gap) / (card_width + min_gap)))
    positions = {}
    current_y = height - header_h - 10

    for gen_key, gen_name in active:
        gen_members = gens[gen_key]
        gen_members = sort_as_couples(gen_members, members)

        c.setFillColorRGB(*TEXT_MAIN)
        c.setFont(FONT_BOLD, 13)
        current_y -= gen_label_h
        c.drawCentredString(width / 2, current_y, gen_name)
        current_y -= 4

        # делим на ряды
        rows = []
        for i in range(0, len(gen_members), max_cards_per_row):
            rows.append(gen_members[i:i + max_cards_per_row])

        for row in rows:
            num = len(row)
            total_w = num * card_width + (num - 1) * min_gap
            start_x = (width - total_w) / 2
            y = current_y - card_height
            for idx, member in enumerate(row):
                x = start_x + idx * (card_width + min_gap)
                draw_member_card(c, member, x, y, card_width, card_height, settings)
                mid = member["id"]
                positions[mid] = {
                    "xcenter": x + card_width / 2,
                    "ytop": y + card_height,
                    "ybottom": y,
                    "ycenter": y + card_height / 2,
                }
            current_y = y - row_gap
        current_y -= gen_gap_y

    draw_connections(c, positions, members)


def render_family_tree_pdf(members, filename, title="", page_format="A4_LANDSCAPE",
                           show_photos=True, show_dates=True, show_patronymic=True):
    if page_format == "A4":
        pagesize = A4
    elif page_format == "A4_LANDSCAPE":
        pagesize = landscape(A4)
    else:
        pagesize = landscape(A4)

    settings = {
        "showPhotos": show_photos,
        "showDates": show_dates,
        "showPatronymic": show_patronymic,
        "title": title,
    }

    c = canvas.Canvas(filename, pagesize=pagesize)
    width, height = pagesize

    draw_beautiful_background(c, width, height)
    draw_header(c, width, height, title)
    draw_family_tree_single_page(c, members, width, height, settings)
    draw_footer(c, width)

    c.showPage()
    c.save()


# --------- Пример использования ---------

if __name__ == "__main__":
    sample_members = [
        {
            "id": "1",
            "firstName": "Иван",
            "lastName": "Иванов",
            "patronymic": "Петрович",
            "role": "GRANDFATHER",
            "birthDate": "1940",
            "deathDate": "",
            "socialRoles": ["ветеран", "инженер"],
            "photoBase64": "",   # сюда можно подставить base64
            "photoUri": "",
            "fatherId": None,
            "motherId": None,
        },
        {
            "id": "2",
            "firstName": "Мария",
            "lastName": "Иванова",
            "patronymic": "Сергеевна",
            "role": "GRANDMOTHER",
            "birthDate": "1945",
            "deathDate": "",
            "socialRoles": ["учитель"],
            "photoBase64": "",
            "photoUri": "",
            "fatherId": None,
            "motherId": None,
        },
        {
            "id": "3",
            "firstName": "Пётр",
            "lastName": "Иванов",
            "patronymic": "Иванович",
            "role": "FATHER",
            "birthDate": "1970",
            "socialRoles": ["программист"],
            "photoBase64": "",
            "photoUri": "",
            "fatherId": "1",
            "motherId": "2",
        },
        {
            "id": "4",
            "firstName": "Анна",
            "lastName": "Иванова",
            "patronymic": "Алексеевна",
            "role": "MOTHER",
            "birthDate": "1972",
            "socialRoles": [],
            "photoBase64": "",
            "photoUri": "",
            "fatherId": None,
            "motherId": None,
        },
        {
            "id": "5",
            "firstName": "Дмитрий",
            "lastName": "Иванов",
            "patronymic": "Петрович",
            "role": "SON",
            "birthDate": "2000",
            "photoBase64": "",
            "photoUri": "",
            "fatherId": "3",
            "motherId": "4",
        },
    ]

    render_family_tree_pdf(
        sample_members,
        "family_tree_demo.pdf",
        title="Семейное древо семьи Ивановых",
        page_format="A4_LANDSCAPE",
        show_photos=True,
        show_dates=True,
        show_patronymic=True,
    )
