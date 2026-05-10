"""
pdf_v2.py — Гибкий генератор PDF семейного древа v2.

Поддерживает:
- Темы (themes): vintage, modern, minimal, dark, sakura, forest, paper
- Стили карточек (card_styles): classic, modern, minimal, dark, photo, poster
- Layouts: generations, compact, centered
- Свой фон: color / gradient / image (url или data-url)
- Форма фото: circle, rounded, square
- Тип линий: orthogonal, curve, straight
- Кастомные цвета, шрифты, размеры
- Декор (уголки, листочки, дерево, рамка) — включается опционально

Пример:
    from pdf_v2 import render_family_tree_pdf_v2

    render_family_tree_pdf_v2(
        members=[...],
        filename='tree.pdf',
        theme='modern',
        card_style='photo',
        layout='compact',
        options={
            'title': 'Наша семья',
            'accent_color': '#3b82f6',
            'photo_shape': 'rounded',
            'connection_style': 'curve',
            'show_photos': True,
            'background': {'type': 'gradient', 'from': '#fef3c7', 'to': '#fde68a'},
        },
    )
"""

from __future__ import annotations

import io
import os
import base64
import logging
import platform
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageDraw

try:
    import requests  # опционально, для URL изображений
except ImportError:
    requests = None

logger = logging.getLogger(__name__)


# ========================================================================
#  ШРИФТЫ
# ========================================================================

def _register_ttf_families() -> dict[str, tuple[str, str, str]]:
    """Регистрирует доступные шрифтовые семьи. Возвращает карту
    family_key -> (regular, bold, italic).
    """
    families_raw = {
        'sans': [
            ('arial.ttf', 'arialbd.ttf', 'ariali.ttf'),
            ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'DejaVuSans-Oblique.ttf'),
            ('LiberationSans-Regular.ttf', 'LiberationSans-Bold.ttf', 'LiberationSans-Italic.ttf'),
        ],
        'serif': [
            ('times.ttf', 'timesbd.ttf', 'timesi.ttf'),
            ('DejaVuSerif.ttf', 'DejaVuSerif-Bold.ttf', 'DejaVuSerif-Italic.ttf'),
            ('LiberationSerif-Regular.ttf', 'LiberationSerif-Bold.ttf', 'LiberationSerif-Italic.ttf'),
        ],
        'mono': [
            ('cour.ttf', 'courbd.ttf', 'couri.ttf'),
            ('DejaVuSansMono.ttf', 'DejaVuSansMono-Bold.ttf', 'DejaVuSansMono-Oblique.ttf'),
        ],
    }

    search_dirs = []
    if platform.system() == 'Windows':
        search_dirs.append(os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts'))
    search_dirs += [
        '/usr/share/fonts/truetype/dejavu',
        '/usr/share/fonts/truetype/liberation',
        '/usr/share/fonts/truetype/msttcorefonts',
        '/Library/Fonts',
        '/System/Library/Fonts',
    ]

    def _find(name: str) -> str | None:
        for d in search_dirs:
            path = os.path.join(d, name)
            if os.path.exists(path):
                return path
        return None

    registered: dict[str, tuple[str, str, str]] = {}
    for family, variants in families_raw.items():
        for regular, bold, italic in variants:
            reg_path = _find(regular)
            if not reg_path:
                continue
            reg_name = f'V2_{family}_R'
            bold_name = f'V2_{family}_B'
            italic_name = f'V2_{family}_I'
            try:
                pdfmetrics.registerFont(TTFont(reg_name, reg_path))
                bold_path = _find(bold)
                if bold_path:
                    pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                else:
                    bold_name = reg_name
                italic_path = _find(italic)
                if italic_path:
                    pdfmetrics.registerFont(TTFont(italic_name, italic_path))
                else:
                    italic_name = reg_name
                registered[family] = (reg_name, bold_name, italic_name)
                logger.info('PDF v2: registered %s -> %s', family, reg_path)
                break
            except Exception as exc:
                logger.warning('PDF v2: font %s failed: %s', reg_path, exc)

    if 'sans' not in registered:
        registered['sans'] = ('Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique')
        logger.warning('PDF v2: using Helvetica fallback — кириллица будет битой!')
    if 'serif' not in registered:
        registered['serif'] = ('Times-Roman', 'Times-Bold', 'Times-Italic')
    if 'mono' not in registered:
        registered['mono'] = ('Courier', 'Courier-Bold', 'Courier-Oblique')

    return registered


_FONT_FAMILIES = _register_ttf_families()


def _fonts_for(family: str) -> tuple[str, str, str]:
    return _FONT_FAMILIES.get(family, _FONT_FAMILIES['sans'])


# ========================================================================
#  ЦВЕТА
# ========================================================================

def _hex_to_rgb(value: str | tuple | list) -> tuple[float, float, float]:
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(float(x) for x in value[:3])
    if not isinstance(value, str):
        return (0, 0, 0)
    s = value.strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(ch * 2 for ch in s)
    if len(s) != 6:
        return (0, 0, 0)
    try:
        r = int(s[0:2], 16) / 255.0
        g = int(s[2:4], 16) / 255.0
        b = int(s[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return (0, 0, 0)


def _mix(a: tuple, b: tuple, t: float) -> tuple[float, float, float]:
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _lighten(rgb: tuple, amount: float) -> tuple[float, float, float]:
    return _mix(rgb, (1, 1, 1), amount)


def _darken(rgb: tuple, amount: float) -> tuple[float, float, float]:
    return _mix(rgb, (0, 0, 0), amount)


# ========================================================================
#  ТЕМЫ И СТИЛИ КАРТОЧЕК
# ========================================================================

THEMES: dict[str, dict] = {
    'vintage': {
        'bg_from': '#f7f0d9',
        'bg_to': '#e8e0c8',
        'paper': '#f9f4e3',
        'text_main': '#3f2e14',
        'text_sub': '#6b5630',
        'text_gray': '#8a7a54',
        'accent': '#96723d',
        'line': '#7a5d32',
        'border_out': '#96723d',
        'border_in': '#b89968',
        'role': '#3f7a4d',
        'decor': {'tree': True, 'leaves': True, 'corners': True, 'double_frame': True},
        'font_family': 'serif',
    },
    'modern': {
        'bg_from': '#ffffff',
        'bg_to': '#f3f4f6',
        'paper': '#ffffff',
        'text_main': '#111827',
        'text_sub': '#374151',
        'text_gray': '#6b7280',
        'accent': '#3b82f6',
        'line': '#93c5fd',
        'border_out': '#e5e7eb',
        'border_in': '#f3f4f6',
        'role': '#2563eb',
        'decor': {'tree': False, 'leaves': False, 'corners': False, 'double_frame': False},
        'font_family': 'sans',
    },
    'minimal': {
        'bg_from': '#fafafa',
        'bg_to': '#ffffff',
        'paper': '#ffffff',
        'text_main': '#111111',
        'text_sub': '#444444',
        'text_gray': '#888888',
        'accent': '#111111',
        'line': '#cccccc',
        'border_out': '#dddddd',
        'border_in': '#eeeeee',
        'role': '#555555',
        'decor': {'tree': False, 'leaves': False, 'corners': False, 'double_frame': False},
        'font_family': 'sans',
    },
    'dark': {
        'bg_from': '#0f172a',
        'bg_to': '#1e293b',
        'paper': '#1e293b',
        'text_main': '#f1f5f9',
        'text_sub': '#cbd5e1',
        'text_gray': '#94a3b8',
        'accent': '#60a5fa',
        'line': '#475569',
        'border_out': '#334155',
        'border_in': '#475569',
        'role': '#93c5fd',
        'decor': {'tree': False, 'leaves': False, 'corners': True, 'double_frame': False},
        'font_family': 'sans',
    },
    'sakura': {
        'bg_from': '#fff1f5',
        'bg_to': '#ffe4ec',
        'paper': '#fff7fa',
        'text_main': '#4a1d2e',
        'text_sub': '#7a3449',
        'text_gray': '#b07384',
        'accent': '#e11d74',
        'line': '#f0a5be',
        'border_out': '#e879a3',
        'border_in': '#f5bacf',
        'role': '#b91c5c',
        'decor': {'tree': False, 'leaves': True, 'corners': True, 'double_frame': True},
        'font_family': 'serif',
    },
    'forest': {
        'bg_from': '#f0f8f0',
        'bg_to': '#d9ead3',
        'paper': '#f4faf2',
        'text_main': '#1b3a1b',
        'text_sub': '#335a33',
        'text_gray': '#6a856a',
        'accent': '#2f7a3d',
        'line': '#4a8b52',
        'border_out': '#2f7a3d',
        'border_in': '#78a87a',
        'role': '#256b2a',
        'decor': {'tree': True, 'leaves': True, 'corners': True, 'double_frame': True},
        'font_family': 'serif',
    },
    'paper': {
        'bg_from': '#ffffff',
        'bg_to': '#ffffff',
        'paper': '#ffffff',
        'text_main': '#000000',
        'text_sub': '#222222',
        'text_gray': '#555555',
        'accent': '#000000',
        'line': '#000000',
        'border_out': '#000000',
        'border_in': '#333333',
        'role': '#000000',
        'decor': {'tree': False, 'leaves': False, 'corners': False, 'double_frame': False},
        'font_family': 'sans',
    },
}


CARD_STYLES = {
    'classic':  {'double_border': True,  'shadow': True,  'corners': True,  'bg_same': True,  'photo_frame': True},
    'modern':   {'double_border': False, 'shadow': True,  'corners': False, 'bg_same': False, 'photo_frame': False},
    'minimal':  {'double_border': False, 'shadow': False, 'corners': False, 'bg_same': False, 'photo_frame': False},
    'dark':     {'double_border': False, 'shadow': True,  'corners': False, 'bg_same': True,  'photo_frame': False},
    'photo':    {'double_border': False, 'shadow': True,  'corners': False, 'bg_same': True,  'photo_frame': True},
    'poster':   {'double_border': True,  'shadow': False, 'corners': True,  'bg_same': True,  'photo_frame': True},
}


# ========================================================================
#  КОНФИГУРАЦИЯ
# ========================================================================

@dataclass
class PdfV2Config:
    # Контент
    title: str = 'Семейное Древо'
    subtitle: str = '~ Семейное древо ~'
    page_format: str = 'A4_LANDSCAPE'

    # Отображение
    show_photos: bool = True
    show_dates: bool = True
    show_patronymic: bool = True
    show_social_roles: bool = True
    show_footer: bool = True
    show_subtitle: bool = True

    # Тема
    theme: str = 'vintage'
    card_style: str = 'classic'
    layout: str = 'generations'           # generations | compact | centered
    font_family: str | None = None        # None => берём из темы

    # Цвета (перекрывают тему)
    accent_color: str | None = None
    bg_from: str | None = None
    bg_to: str | None = None
    text_color: str | None = None
    border_color: str | None = None
    line_color: str | None = None
    card_bg: str | None = None

    # Декор
    show_tree: bool | None = None
    show_leaves: bool | None = None
    show_corners: bool | None = None
    double_frame: bool | None = None

    # Карточки
    photo_shape: str = 'circle'           # circle | rounded | square
    card_radius: float = 8.0
    card_padding: float = 12.0
    min_card_width: float = 90.0
    max_card_width: float = 160.0

    # Связи
    connection_style: str = 'orthogonal'  # orthogonal | curve | straight
    connection_width: float = 1.5

    # Пользовательский фон
    background: dict[str, Any] | None = None
    # Примеры:
    # {'type': 'color', 'color': '#fafafa'}
    # {'type': 'gradient', 'from': '#fef3c7', 'to': '#fde68a', 'direction': 'vertical'}
    # {'type': 'image', 'src': 'data:image/...', 'opacity': 0.3, 'fit': 'cover'}

    # Резолвенные значения (заполняются в __post_init__)
    resolved: dict = field(default_factory=dict)

    def __post_init__(self):
        theme = THEMES.get(self.theme, THEMES['vintage'])
        card = CARD_STYLES.get(self.card_style, CARD_STYLES['classic'])

        def pick(name, default):
            value = getattr(self, name, None)
            return value if value is not None else default

        accent = _hex_to_rgb(self.accent_color or theme['accent'])
        text_main = _hex_to_rgb(self.text_color or theme['text_main'])

        self.resolved = {
            'bg_from': _hex_to_rgb(self.bg_from or theme['bg_from']),
            'bg_to': _hex_to_rgb(self.bg_to or theme['bg_to']),
            'paper': _hex_to_rgb(self.card_bg or theme['paper']),
            'text_main': text_main,
            'text_sub': _hex_to_rgb(theme['text_sub']),
            'text_gray': _hex_to_rgb(theme['text_gray']),
            'accent': accent,
            'line': _hex_to_rgb(self.line_color or theme['line']),
            'border_out': _hex_to_rgb(self.border_color or theme['border_out']),
            'border_in': _hex_to_rgb(theme['border_in']),
            'role': _hex_to_rgb(theme['role']),
            'card': card,
            'decor': {
                'tree': pick('show_tree', theme['decor']['tree']),
                'leaves': pick('show_leaves', theme['decor']['leaves']),
                'corners': pick('show_corners', theme['decor']['corners']),
                'double_frame': pick('double_frame', theme['decor']['double_frame']),
            },
            'font_family': self.font_family or theme['font_family'],
        }

        reg, bold, italic = _fonts_for(self.resolved['font_family'])
        self.resolved['font_reg'] = reg
        self.resolved['font_bold'] = bold
        self.resolved['font_italic'] = italic


# ========================================================================
#  УТИЛИТЫ
# ========================================================================

ROLE_NAMES = {
    'GRANDFATHER': 'Дедушка', 'GRANDMOTHER': 'Бабушка',
    'FATHER': 'Отец', 'MOTHER': 'Мать',
    'SON': 'Сын', 'DAUGHTER': 'Дочь',
    'BROTHER': 'Брат', 'SISTER': 'Сестра',
    'UNCLE': 'Дядя', 'AUNT': 'Тётя',
    'NEPHEW': 'Племянник', 'NIECE': 'Племянница',
    'GRANDSON': 'Внук', 'GRANDDAUGHTER': 'Внучка',
    'OTHER': 'Родственник',
}

GEN_ORDER = [
    ('grandparents', 'Бабушки и Дедушки'),
    ('parents', 'Родители'),
    ('uncles', 'Дяди и Тёти'),
    ('children', 'Дети'),
    ('nephews', 'Племянники'),
    ('grandchildren', 'Внуки'),
    ('other', 'Другие'),
]

ROLE_TO_GEN = {
    'GRANDFATHER': 'grandparents', 'GRANDMOTHER': 'grandparents',
    'FATHER': 'parents', 'MOTHER': 'parents',
    'UNCLE': 'uncles', 'AUNT': 'uncles',
    'SON': 'children', 'DAUGHTER': 'children',
    'BROTHER': 'children', 'SISTER': 'children',
    'NEPHEW': 'nephews', 'NIECE': 'nephews',
    'GRANDSON': 'grandchildren', 'GRANDDAUGHTER': 'grandchildren',
    'OTHER': 'other',
}


def _group_by_generation(members: list[dict]) -> dict[str, list[dict]]:
    gens: dict[str, list[dict]] = {k: [] for k, _ in GEN_ORDER}
    for m in members:
        role = (m.get('role') or 'OTHER').upper()
        gens[ROLE_TO_GEN.get(role, 'other')].append(m)
    return gens


def _gender_order(role: str | None) -> int:
    role = (role or 'OTHER').upper()
    if role in {'GRANDFATHER', 'FATHER', 'SON', 'BROTHER', 'UNCLE', 'NEPHEW', 'GRANDSON'}:
        return 1
    if role in {'GRANDMOTHER', 'MOTHER', 'DAUGHTER', 'SISTER', 'AUNT', 'NIECE', 'GRANDDAUGHTER'}:
        return 2
    return 3


def _sort_as_couples(gen_members: list[dict], all_members: list[dict]) -> list[dict]:
    if len(gen_members) <= 1:
        return list(gen_members)
    ids_here = {m['id'] for m in gen_members}
    couples: list[tuple] = []
    for child in all_members:
        f, mo = child.get('fatherId'), child.get('motherId')
        if f and mo and f in ids_here and mo in ids_here and (f, mo) not in couples:
            couples.append((f, mo))
    if not couples:
        males = [m for m in gen_members if _gender_order(m.get('role')) == 1]
        females = [m for m in gen_members if _gender_order(m.get('role')) == 2]
        for i, ma in enumerate(males):
            if i < len(females):
                couples.append((ma['id'], females[i]['id']))

    out: list[dict] = []
    used: set = set()
    for mid, fid in couples:
        ma = next((m for m in gen_members if m['id'] == mid), None)
        fe = next((m for m in gen_members if m['id'] == fid), None)
        for x in (ma, fe):
            if x and x['id'] not in used:
                out.append(x); used.add(x['id'])
    remaining = [m for m in gen_members if m['id'] not in used]
    remaining.sort(key=lambda m: _gender_order(m.get('role')))
    out.extend(remaining)
    return out


def _format_social(member: dict) -> str:
    value = member.get('socialRoles')
    if not value:
        return ''
    if isinstance(value, list):
        return ', '.join(str(x).strip() for x in value if str(x).strip())
    return str(value).strip()


def _fit_text(c, text: str, font: str, size: float, max_w: float) -> str:
    text = text or ''
    if not text or c.stringWidth(text, font, size) <= max_w:
        return text
    suffix = '…'
    while len(text) > 1 and c.stringWidth(text + suffix, font, size) > max_w:
        text = text[:-1]
    return text + suffix


def _load_image(src: str) -> Image.Image | None:
    if not src:
        return None
    try:
        s = src.strip()
        if s.startswith('data:') and ',' in s:
            raw = base64.b64decode(s.split(',', 1)[1])
        elif s.startswith(('http://', 'https://')):
            if requests is None:
                return None
            resp = requests.get(s, timeout=5)
            resp.raise_for_status()
            raw = resp.content
        else:
            raw = base64.b64decode(s)
        return Image.open(io.BytesIO(raw)).convert('RGBA')
    except Exception as exc:
        logger.debug('PDF v2: image load failed: %s', exc)
        return None


# ========================================================================
#  ФОН
# ========================================================================

def _draw_background(c, w: float, h: float, cfg: PdfV2Config) -> None:
    bg = cfg.background or {}
    btype = bg.get('type')

    if btype == 'color':
        c.setFillColorRGB(*_hex_to_rgb(bg.get('color', '#ffffff')))
        c.rect(0, 0, w, h, stroke=0, fill=1)
    elif btype == 'gradient':
        _gradient_fill(c, w, h,
                       _hex_to_rgb(bg.get('from', '#ffffff')),
                       _hex_to_rgb(bg.get('to', '#eeeeee')),
                       bg.get('direction', 'vertical'))
    elif btype == 'image':
        img = _load_image(bg.get('src', ''))
        if img is not None:
            _draw_bg_image(c, w, h, img, opacity=float(bg.get('opacity', 1.0)),
                           fit=bg.get('fit', 'cover'))
        else:
            _gradient_fill(c, w, h, cfg.resolved['bg_from'], cfg.resolved['bg_to'])
    else:
        _gradient_fill(c, w, h, cfg.resolved['bg_from'], cfg.resolved['bg_to'])

    decor = cfg.resolved['decor']
    if decor['tree']:
        _draw_tree_decor(c, w, h, cfg)
    if decor['leaves']:
        _draw_leaves(c, w, h, cfg)
    if decor['double_frame']:
        _draw_double_frame(c, w, h, cfg)
    if decor['corners']:
        _draw_corner_accents(c, w, h, cfg)


def _gradient_fill(c, w, h, color_a, color_b, direction='vertical'):
    steps = 40
    if direction == 'horizontal':
        for i in range(steps):
            t = i / (steps - 1)
            c.setFillColorRGB(*_mix(color_a, color_b, t))
            c.rect(i * (w / steps), 0, w / steps + 1, h, stroke=0, fill=1)
    elif direction == 'diagonal':
        for i in range(steps):
            t = i / (steps - 1)
            c.setFillColorRGB(*_mix(color_a, color_b, t))
            c.rect(0, h - (i + 1) * (h / steps), w, h / steps + 1, stroke=0, fill=1)
    else:  # vertical (сверху -> вниз)
        for i in range(steps):
            t = i / (steps - 1)
            c.setFillColorRGB(*_mix(color_a, color_b, t))
            y = h - (i + 1) * (h / steps)
            c.rect(0, y, w, h / steps + 1, stroke=0, fill=1)


def _draw_bg_image(c, w, h, img: Image.Image, opacity: float = 1.0, fit: str = 'cover'):
    iw, ih = img.size
    if fit == 'contain':
        scale = min(w / iw, h / ih)
    elif fit == 'stretch':
        scale_x, scale_y = w / iw, h / ih
        new_w, new_h = int(iw * scale_x), int(ih * scale_y)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        if opacity < 1.0:
            alpha = img.split()[-1].point(lambda p: int(p * opacity))
            img.putalpha(alpha)
        buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
        c.drawImage(ImageReader(buf), 0, 0, w, h, mask='auto')
        return
    else:  # cover
        scale = max(w / iw, h / ih)
    new_w, new_h = int(iw * scale), int(ih * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    if opacity < 1.0:
        alpha = img.split()[-1].point(lambda p: int(p * opacity))
        img.putalpha(alpha)
    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    x = (w - new_w) / 2
    y = (h - new_h) / 2
    c.drawImage(ImageReader(buf), x, y, new_w, new_h, mask='auto')


def _draw_tree_decor(c, w, h, cfg: PdfV2Config):
    line = cfg.resolved['line']
    c.saveState()
    c.setStrokeColorRGB(*_darken(line, 0.2))
    c.setLineCap(1)
    tx = w / 2
    c.setLineWidth(8); c.line(tx, 0, tx, 60)
    c.line(tx - 15, 60, tx, 90); c.line(tx + 15, 60, tx, 90)
    c.setLineWidth(4)
    for x1, y1, x2, y2 in [(tx, 0, tx - 40, -10), (tx, 0, tx + 40, -10),
                            (tx - 20, 10, tx - 50, 0), (tx + 20, 10, tx + 50, 0)]:
        c.line(x1, y1, x2, y2)
    c.setLineWidth(4)
    for side in (0, w):
        sign = 1 if side == 0 else -1
        c.line(side, h, side + sign * 60, h - 40)
        c.line(side + sign * 60, h - 40, side + sign * 50, h - 80)
        c.line(side + sign * 60, h - 40, side + sign * 100, h - 60)
        c.line(side + sign * 100, h - 60, side + sign * 90, h - 100)
        c.line(side + sign * 100, h - 60, side + sign * 140, h - 75)
    c.restoreState()


def _draw_leaves(c, w, h, cfg: PdfV2Config):
    accent = cfg.resolved['accent']
    base_green = _mix(accent, (0.3, 0.6, 0.3), 0.5) if cfg.theme != 'sakura' else _hex_to_rgb('#ec4899')
    positions = [
        (55, h - 75, 10), (95, h - 55, 8), (45, h - 95, 7),
        (135, h - 70, 9), (85, h - 95, 6), (110, h - 85, 7),
        (w - 55, h - 75, 10), (w - 95, h - 55, 8), (w - 45, h - 95, 7),
        (w - 135, h - 70, 9), (w - 85, h - 95, 6), (w - 110, h - 85, 7),
        (35, 95, 7), (65, 80, 6), (25, 75, 5),
        (w - 35, 95, 7), (w - 65, 80, 6), (w - 25, 75, 5),
    ]
    for x, y, size in positions:
        shade = 0.8 + (hash((x, y)) % 20) / 100
        c.setFillColorRGB(*_darken(base_green, 1 - shade))
        c.circle(x, y, size, fill=1, stroke=0)


def _draw_double_frame(c, w, h, cfg: PdfV2Config):
    margin = 12
    c.setStrokeColorRGB(*cfg.resolved['border_out']); c.setLineWidth(3)
    c.roundRect(margin, margin, w - 2 * margin, h - 2 * margin, 15, fill=0, stroke=1)
    c.setStrokeColorRGB(*cfg.resolved['border_in']); c.setLineWidth(1.5)
    c.roundRect(margin + 6, margin + 6, w - 2 * margin - 12, h - 2 * margin - 12, 12, fill=0, stroke=1)


def _draw_corner_accents(c, w, h, cfg: PdfV2Config):
    c.setStrokeColorRGB(*cfg.resolved['accent']); c.setLineWidth(2)
    L = 25
    for cx, cy, dx, dy in [(20, h - 20, 1, -1), (w - 20, h - 20, -1, -1),
                            (20, 20, 1, 1), (w - 20, 20, -1, 1)]:
        c.line(cx, cy, cx + dx * L, cy); c.line(cx, cy, cx, cy + dy * L)


# ========================================================================
#  ЗАГОЛОВОК
# ========================================================================

def _draw_header(c, w, h, cfg: PdfV2Config) -> float:
    header_h = 80
    banner_y = h - header_h + 10
    banner_h = 60
    title = cfg.title or 'Семейное Древо'

    if cfg.resolved['decor']['double_frame']:
        title_w = c.stringWidth(title, cfg.resolved['font_bold'], 22) + 100
        banner_w = max(400, min(w - 80, title_w))
        bx = (w - banner_w) / 2

        c.setFillColorRGB(*cfg.resolved['paper'])
        c.roundRect(bx, banner_y, banner_w, banner_h, 10, fill=1, stroke=0)
        c.setStrokeColorRGB(*cfg.resolved['border_out']); c.setLineWidth(2)
        c.roundRect(bx, banner_y, banner_w, banner_h, 10, fill=0, stroke=1)

    c.setFillColorRGB(*cfg.resolved['text_main'])
    c.setFont(cfg.resolved['font_bold'], 24)
    c.drawCentredString(w / 2, banner_y + 28, title)

    if cfg.show_subtitle and cfg.subtitle:
        c.setFillColorRGB(*cfg.resolved['text_sub'])
        c.setFont(cfg.resolved['font_italic'], 11)
        c.drawCentredString(w / 2, banner_y + 10, cfg.subtitle)

    c.setStrokeColorRGB(*cfg.resolved['accent']); c.setLineWidth(1)
    c.line(w / 2 - 120, banner_y, w / 2 + 120, banner_y)

    return header_h


def _draw_gen_label(c, name: str, w: float, y: float, cfg: PdfV2Config):
    text_w = c.stringWidth(name, cfg.resolved['font_italic'], 13) + 40
    c.setFillColorRGB(*cfg.resolved['paper'])
    c.roundRect(w / 2 - text_w / 2, y - 10, text_w, 22, 6, fill=1, stroke=0)
    c.setStrokeColorRGB(*cfg.resolved['border_in']); c.setLineWidth(0.8)
    c.roundRect(w / 2 - text_w / 2, y - 10, text_w, 22, 6, fill=0, stroke=1)

    c.setStrokeColorRGB(*cfg.resolved['accent']); c.setLineWidth(1.2)
    for side in (-1, 1):
        xs = w / 2 + side * text_w / 2 + side * 8
        c.line(xs, y, xs + side * 60, y)
        c.circle(xs + side * 64, y, 2.5, fill=1, stroke=0)

    c.setFillColorRGB(*cfg.resolved['text_sub'])
    c.setFont(cfg.resolved['font_italic'], 13)
    c.drawCentredString(w / 2, y - 4, name)


def _draw_footer(c, w: float, cfg: PdfV2Config):
    if not cfg.show_footer:
        return
    c.setFillColorRGB(*cfg.resolved['text_gray'])
    c.setFont(cfg.resolved['font_reg'], 9)
    date_str = datetime.now().strftime('%d.%m.%Y')
    c.drawCentredString(w / 2, 18, f'Дата создания: {date_str}')


# ========================================================================
#  ФОТО
# ========================================================================

def _draw_photo(c, photo_src: str, x: float, y: float, size: float, cfg: PdfV2Config):
    img = _load_image(photo_src)
    if img is None:
        _draw_avatar(c, x, y, size, cfg)
        return

    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w - side) // 2 + side, (h - side) // 2 + side))
    img = img.resize((int(size * 3), int(size * 3)), Image.LANCZOS)

    shape = cfg.photo_shape
    if shape == 'circle':
        mask = Image.new('L', img.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, img.size[0], img.size[1]), fill=255)
    elif shape == 'rounded':
        mask = Image.new('L', img.size, 0)
        r = int(img.size[0] * 0.18)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, img.size[0], img.size[1]), radius=r, fill=255)
    else:
        mask = Image.new('L', img.size, 255)

    out = Image.new('RGBA', img.size, (255, 255, 255, 0))
    out.paste(img, (0, 0))
    out.putalpha(mask)
    buf = io.BytesIO(); out.save(buf, format='PNG'); buf.seek(0)

    if cfg.resolved['card'].get('photo_frame'):
        c.setFillColorRGB(*cfg.resolved['accent'])
        if shape == 'circle':
            c.circle(x + size / 2, y + size / 2, size / 2 + 2.5, fill=1, stroke=0)
        elif shape == 'rounded':
            c.roundRect(x - 2, y - 2, size + 4, size + 4, size * 0.18, fill=1, stroke=0)
        else:
            c.rect(x - 2, y - 2, size + 4, size + 4, fill=1, stroke=0)

    c.drawImage(ImageReader(buf), x, y, size, size, mask='auto')


def _draw_avatar(c, x, y, size, cfg: PdfV2Config):
    cx, cy = x + size / 2, y + size / 2
    shape = cfg.photo_shape
    if cfg.resolved['card'].get('photo_frame'):
        c.setFillColorRGB(*cfg.resolved['accent'])
        if shape == 'circle':
            c.circle(cx, cy, size / 2 + 2.5, fill=1, stroke=0)
        else:
            c.roundRect(x - 2, y - 2, size + 4, size + 4, size * 0.18, fill=1, stroke=0)

    c.setFillColorRGB(*_lighten(cfg.resolved['accent'], 0.75))
    if shape == 'circle':
        c.circle(cx, cy, size / 2, fill=1, stroke=0)
    else:
        c.roundRect(x, y, size, size, size * 0.18 if shape == 'rounded' else 0, fill=1, stroke=0)

    c.setFillColorRGB(*cfg.resolved['text_gray'])
    c.circle(cx, cy + size * 0.12, size * 0.18, fill=1, stroke=0)
    c.ellipse(cx - size * 0.28, cy - size * 0.40,
              cx + size * 0.28, cy - size * 0.05, fill=1, stroke=0)


# ========================================================================
#  КАРТОЧКА
# ========================================================================

def _draw_card(c, member: dict, x: float, y: float, w: float, h: float, cfg: PdfV2Config):
    card = cfg.resolved['card']
    s = w / 130.0
    inset = max(3, int(cfg.card_padding / 3 * s))
    radius = cfg.card_radius

    # Тень
    if card.get('shadow'):
        c.setFillColorRGB(*_darken(cfg.resolved['border_out'], 0.35))
        c.saveState()
        try:
            c.setFillAlpha(0.25)
        except Exception:
            pass
        c.roundRect(x + 3, y - 3, w, h, radius, fill=1, stroke=0)
        c.restoreState()

    # Фон
    c.setFillColorRGB(*cfg.resolved['paper'])
    c.roundRect(x, y, w, h, radius, fill=1, stroke=0)

    # Внешняя рамка
    c.setStrokeColorRGB(*cfg.resolved['border_out'])
    c.setLineWidth(max(1, 1.8 * s))
    c.roundRect(x, y, w, h, radius, fill=0, stroke=1)

    # Внутренняя рамка (для classic/poster)
    if card.get('double_border'):
        c.setStrokeColorRGB(*cfg.resolved['border_in']); c.setLineWidth(1)
        c.roundRect(x + inset, y + inset, w - 2 * inset, h - 2 * inset, max(2, radius - 3), fill=0, stroke=1)

    # Декоративные уголки на карточке
    if card.get('corners'):
        cs = max(6, int(10 * s)); edge = max(5, int(8 * s))
        c.setStrokeColorRGB(*cfg.resolved['accent']); c.setLineWidth(1)
        for cx, cy in [(x + edge, y + edge), (x + w - edge, y + edge),
                       (x + edge, y + h - edge), (x + w - edge, y + h - edge)]:
            # "уголок" из двух коротких линий
            dx = -1 if cx > x + w / 2 else 1
            dy = -1 if cy > y + h / 2 else 1
            c.line(cx, cy, cx + dx * cs, cy)
            c.line(cx, cy, cx, cy + dy * cs)

    # --- Содержимое ---
    curr_y = y + h - max(8, int(10 * s))
    max_text_w = w - 2 * inset - 4

    if cfg.show_photos:
        ps = max(28, int(w * (0.42 if cfg.card_style == 'photo' else 0.38)))
        px = x + (w - ps) / 2
        py = curr_y - ps
        src = member.get('photoBase64') or member.get('photoUri')
        try:
            _draw_photo(c, src, px, py, ps, cfg)
        except Exception as exc:
            logger.debug('photo fallback: %s', exc)
            _draw_avatar(c, px, py, ps, cfg)
        curr_y = py - max(4, int(5 * s))

    name_f = max(7, min(12, int(9.5 * s)))
    detail_f = max(6, min(10, int(8.5 * s)))
    role_f = max(7, min(12, int(10 * s)))

    # ФИО
    last = (member.get('lastName') or '').strip()
    first = (member.get('firstName') or '').strip()
    name = _fit_text(c, f'{last} {first}'.strip(),
                      cfg.resolved['font_bold'], name_f, max_text_w)
    c.setFillColorRGB(*cfg.resolved['text_main'])
    c.setFont(cfg.resolved['font_bold'], name_f)
    c.drawCentredString(x + w / 2, curr_y, name)
    curr_y -= name_f + 2

    if cfg.show_patronymic:
        patr = (member.get('patronymic') or '').strip()
        if patr:
            patr = _fit_text(c, patr, cfg.resolved['font_reg'], detail_f, max_text_w)
            c.setFillColorRGB(*cfg.resolved['text_sub'])
            c.setFont(cfg.resolved['font_reg'], detail_f)
            c.drawCentredString(x + w / 2, curr_y, patr)
            curr_y -= detail_f + 1

    role = ROLE_NAMES.get((member.get('role') or 'OTHER').upper(), 'Родственник')
    c.setFillColorRGB(*cfg.resolved['role'])
    c.setFont(cfg.resolved['font_italic'], role_f)
    c.drawCentredString(x + w / 2, curr_y, role)
    curr_y -= role_f + 1

    if cfg.show_social_roles:
        soc = _format_social(member)
        if soc and curr_y > y + inset + detail_f:
            soc = _fit_text(c, soc, cfg.resolved['font_reg'], detail_f, max_text_w)
            c.setFillColorRGB(*_darken(cfg.resolved['text_sub'], 0.1))
            c.setFont(cfg.resolved['font_reg'], detail_f)
            c.drawCentredString(x + w / 2, curr_y, soc)
            curr_y -= detail_f + 1

    if cfg.show_dates:
        birth = (member.get('birthDate') or '').strip()
        death = (member.get('deathDate') or '').strip()
        if birth or death:
            if birth and death:
                line = f'{birth} — {death}'
            elif birth:
                line = birth
            else:
                line = f'✝ {death}'
            line = _fit_text(c, line, cfg.resolved['font_reg'], detail_f, max_text_w)
            c.setFillColorRGB(*cfg.resolved['text_gray'])
            c.setFont(cfg.resolved['font_reg'], detail_f)
            c.drawCentredString(x + w / 2, curr_y, line)


# ========================================================================
#  СВЯЗИ
# ========================================================================

def _draw_connection(c, x1, y1, x2, y2, cfg: PdfV2Config):
    style = cfg.connection_style
    c.setStrokeColorRGB(*cfg.resolved['line'])
    c.setLineWidth(cfg.connection_width)

    if style == 'straight':
        c.line(x1, y1, x2, y2)
    elif style == 'curve':
        p = c.beginPath()
        p.moveTo(x1, y1)
        ctrl_y = (y1 + y2) / 2
        p.curveTo(x1, ctrl_y, x2, ctrl_y, x2, y2)
        c.drawPath(p, fill=0, stroke=1)
    else:  # orthogonal
        mid = (y1 + y2) / 2
        c.line(x1, y1, x1, mid)
        c.line(min(x1, x2), mid, max(x1, x2), mid)
        c.line(x2, mid, x2, y2)

    c.setFillColorRGB(*cfg.resolved['accent'])
    c.circle(x2, y2, 2.8, fill=1, stroke=0)


def _draw_all_connections(c, positions: dict, members: list[dict], cfg: PdfV2Config):
    drawn: set = set()
    for m in members:
        mid = m.get('id')
        if mid not in positions:
            continue
        child = positions[mid]
        for pid in (m.get('fatherId'), m.get('motherId')):
            if not pid or pid not in positions:
                continue
            pair = tuple(sorted((mid, pid)))
            if pair in drawn:
                continue
            parent = positions[pid]
            _draw_connection(c, parent['xcenter'], parent['ybottom'],
                              child['xcenter'], child['ytop'], cfg)
            drawn.add(pair)


# ========================================================================
#  РАСКЛАДКА (LAYOUT) + РЕНДЕР
# ========================================================================

def _layout_generations(c, members, w, h, active, gens, cfg: PdfV2Config) -> bool:
    margin_x = 40
    header_h = 80
    footer_h = 40
    gen_label_h = 28
    usable_w = w - 2 * margin_x
    usable_h = h - header_h - footer_h - 20

    max_in_row = max((len(gens[k]) for k, _ in active), default=1)
    min_gap = 12
    ideal = min(cfg.max_card_width,
                max(cfg.min_card_width, (usable_w - (max_in_row - 1) * min_gap) / max(1, max_in_row)))
    gap_x = min(22, max(min_gap, ideal * 0.12))
    max_per_row = max(1, int((usable_w + gap_x) / (cfg.min_card_width + gap_x)))
    needs_wrap = any(len(gens[k]) > max_per_row for k, _ in active)
    card_w = ideal if not needs_wrap else max(
        cfg.min_card_width,
        (usable_w - (min(max_in_row, max_per_row) - 1) * gap_x) / min(max_in_row, max_per_row),
    )

    s = card_w / 130.0
    top = max(8, int(10 * s)); bottom = max(6, int(8 * s))
    name_h = max(7, min(12, int(9.5 * s))) + 2
    role_h = max(7, min(12, int(10 * s))) + 1
    dh = max(6, min(10, int(8.5 * s))) + 1
    content_h = top + name_h + role_h + bottom
    if cfg.show_photos:
        content_h += max(28, int(card_w * (0.42 if cfg.card_style == 'photo' else 0.38))) + max(4, int(5 * s))
    if cfg.show_patronymic:
        content_h += dh
    if cfg.show_social_roles:
        content_h += dh
    if cfg.show_dates:
        content_h += dh
    card_h = int(content_h)

    def rows(k):
        n = len(gens[k])
        return 0 if n == 0 else (n + max_per_row - 1) // max_per_row

    total_rows = sum(rows(k) for k, _ in active)
    row_gap = 10
    gen_gap = 28
    total_h = (total_rows * card_h + max(0, total_rows - 1) * row_gap
               + len(active) * gen_label_h + max(0, len(active) - 1) * gen_gap)

    if total_h > usable_h:
        scale = usable_h / total_h
        if scale < 0.55:
            return False
        card_h = max(60, int(card_h * scale))
        card_w = max(80, int(card_w * scale))
        gap_x = max(8, int(gap_x * scale))
        gen_gap = max(10, int(gen_gap * scale))

    _draw_background(c, w, h, cfg)
    _draw_header(c, w, h, cfg)

    positions = {}
    cur_y = h - header_h - 8
    for gen_key, gen_name in active:
        gen_members = _sort_as_couples(gens[gen_key], members)
        cur_y -= gen_label_h
        _draw_gen_label(c, gen_name, w, cur_y + 10, cfg)
        cur_y -= 6

        batches = [gen_members[i:i + max_per_row]
                    for i in range(0, len(gen_members), max_per_row)]
        for row in batches:
            n = len(row)
            total_w = n * card_w + (n - 1) * gap_x
            sx = (w - total_w) / 2
            for i, m in enumerate(row):
                x = sx + i * (card_w + gap_x); y = cur_y - card_h
                _draw_card(c, m, x, y, card_w, card_h, cfg)
                positions[m['id']] = {'xcenter': x + card_w / 2,
                                      'ytop': y + card_h,
                                      'ybottom': y}
            cur_y -= card_h + row_gap
        cur_y -= gen_gap

    _draw_all_connections(c, positions, members, cfg)
    _draw_footer(c, w, cfg)
    return True


def _layout_compact(c, members, w, h, active, gens, cfg: PdfV2Config) -> bool:
    # Более плотная сетка: уменьшаем gap, высоту gen_label; остальное как generations
    saved = (cfg.min_card_width, cfg.max_card_width)
    cfg.min_card_width = max(70, cfg.min_card_width - 15)
    cfg.max_card_width = max(100, cfg.max_card_width - 20)
    try:
        ok = _layout_generations(c, members, w, h, active, gens, cfg)
    finally:
        cfg.min_card_width, cfg.max_card_width = saved
    return ok


def _layout_centered(c, members, w, h, active, gens, cfg: PdfV2Config) -> bool:
    # Карточки всегда центрированы в своих поколениях, пары рядом.
    # Визуально это то же, что generations (уже центрируем), но связи изогнутые.
    saved = cfg.connection_style
    if saved == 'orthogonal':
        cfg.connection_style = 'curve'
    try:
        return _layout_generations(c, members, w, h, active, gens, cfg)
    finally:
        cfg.connection_style = saved


LAYOUTS = {
    'generations': _layout_generations,
    'compact': _layout_compact,
    'centered': _layout_centered,
}


# ========================================================================
#  PUBLIC API
# ========================================================================

def draw_family_tree_v2(c, members: list[dict], width: float, height: float,
                        cfg: PdfV2Config | None = None) -> None:
    cfg = cfg or PdfV2Config()
    gens = _group_by_generation(members)
    active = [(k, name) for k, name in GEN_ORDER if gens.get(k)]
    if not active:
        _draw_background(c, width, height, cfg)
        _draw_header(c, width, height, cfg)
        _draw_footer(c, width, cfg)
        return

    renderer = LAYOUTS.get(cfg.layout, _layout_generations)
    ok = renderer(c, members, width, height, active, gens, cfg)
    if not ok:
        # fallback на generations c меньшим scale
        _layout_generations(c, members, width, height, active, gens, cfg)


def _resolve_page_size(page_format: str):
    return {
        'A4': A4,
        'A4_LANDSCAPE': landscape(A4),
        'A3': A3,
        'A3_LANDSCAPE': landscape(A3),
    }.get(page_format, landscape(A4))


def render_family_tree_pdf_v2(members: list[dict], filename: str,
                               theme: str = 'vintage',
                               card_style: str = 'classic',
                               layout: str = 'generations',
                               options: dict | None = None) -> None:
    """Генерирует PDF. options может содержать любые поля PdfV2Config."""
    options = dict(options or {})
    options.setdefault('theme', theme)
    options.setdefault('card_style', card_style)
    options.setdefault('layout', layout)

    # Отфильтруем только известные поля
    allowed = {f for f in PdfV2Config.__dataclass_fields__.keys()}
    cfg = PdfV2Config(**{k: v for k, v in options.items() if k in allowed})

    pagesize = _resolve_page_size(cfg.page_format)
    c = canvas.Canvas(filename, pagesize=pagesize)
    width, height = pagesize
    draw_family_tree_v2(c, members, width, height, cfg)
    c.save()


# ========================================================================
#  DEMO
# ========================================================================

if __name__ == '__main__':
    sample = [
        {'id': '1', 'firstName': 'Иван', 'lastName': 'Иванов', 'patronymic': 'Петрович',
         'role': 'GRANDFATHER', 'birthDate': '1940', 'socialRoles': ['ветеран', 'инженер']},
        {'id': '2', 'firstName': 'Мария', 'lastName': 'Иванова', 'patronymic': 'Сергеевна',
         'role': 'GRANDMOTHER', 'birthDate': '1945', 'socialRoles': ['учитель']},
        {'id': '3', 'firstName': 'Пётр', 'lastName': 'Иванов', 'patronymic': 'Иванович',
         'role': 'FATHER', 'birthDate': '1970', 'fatherId': '1', 'motherId': '2',
         'socialRoles': ['программист']},
        {'id': '4', 'firstName': 'Анна', 'lastName': 'Иванова', 'patronymic': 'Алексеевна',
         'role': 'MOTHER', 'birthDate': '1972'},
        {'id': '5', 'firstName': 'Дмитрий', 'lastName': 'Иванов', 'patronymic': 'Петрович',
         'role': 'SON', 'birthDate': '2000', 'fatherId': '3', 'motherId': '4'},
        {'id': '6', 'firstName': 'Ольга', 'lastName': 'Иванова', 'patronymic': 'Петровна',
         'role': 'DAUGHTER', 'birthDate': '2005', 'fatherId': '3', 'motherId': '4'},
    ]
    for theme in ('vintage', 'modern', 'minimal', 'dark', 'sakura', 'forest'):
        render_family_tree_pdf_v2(
            sample, f'demo_{theme}.pdf',
            theme=theme,
            card_style='classic' if theme in ('vintage', 'sakura', 'forest') else 'modern',
            options={'title': f'Древо семьи — {theme}'},
        )
        print(f'generated: demo_{theme}.pdf')
