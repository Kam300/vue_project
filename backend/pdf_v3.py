"""
pdf_v3.py — Визуальный конструктор (как draw.io): рендер PDF по абсолютным
координатам карточек и рёбер, собранных пользователем в редакторе.

Все координаты во входе — в точках PDF (1pt = 1/72 дюйма), уже в системе
«origin = верх-лево» (как в DOM). Y-инверсия выполняется внутри.
"""

from __future__ import annotations

import io
import os
import base64
import logging
from datetime import datetime
from typing import Any

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw

from pdf_v2 import (
    _fonts_for, _hex_to_rgb, _lighten, _darken, _mix,
    _draw_background, _draw_header, _draw_footer, _load_image,
    PdfV2Config, ROLE_NAMES,
)

logger = logging.getLogger(__name__)


def _page_size(page_format: str):
    return {
        'A4': A4, 'A4_LANDSCAPE': landscape(A4),
        'A3': A3, 'A3_LANDSCAPE': landscape(A3),
    }.get(page_format, landscape(A4))


def _flip_y(y: float, node_h: float, page_h: float) -> float:
    """Преобразует top-left координату DOM в bottom-left PDF."""
    return page_h - y - node_h


def _clip_text(c, text: str, font: str, size: float, max_w: float) -> str:
    if not text:
        return ''
    if c.stringWidth(text, font, size) <= max_w:
        return text
    suffix = '…'
    while len(text) > 1 and c.stringWidth(text + suffix, font, size) > max_w:
        text = text[:-1]
    return text + suffix


def _draw_photo(c, src: str, x: float, y: float, size: float, shape: str,
                accent: tuple[float, float, float]) -> None:
    img = _load_image(src)
    if img is None:
        _draw_avatar(c, x, y, size, shape, accent)
        return
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w - side) // 2 + side, (h - side) // 2 + side))
    img = img.resize((int(size * 3), int(size * 3)), Image.LANCZOS)

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

    c.setFillColorRGB(*accent)
    if shape == 'circle':
        c.circle(x + size / 2, y + size / 2, size / 2 + 1.8, fill=1, stroke=0)
    elif shape == 'rounded':
        c.roundRect(x - 1.5, y - 1.5, size + 3, size + 3, size * 0.18, fill=1, stroke=0)
    else:
        c.rect(x - 1.5, y - 1.5, size + 3, size + 3, fill=1, stroke=0)

    c.drawImage(ImageReader(buf), x, y, size, size, mask='auto')


def _draw_avatar(c, x, y, size, shape, accent):
    cx, cy = x + size / 2, y + size / 2
    c.setFillColorRGB(*accent)
    if shape == 'circle':
        c.circle(cx, cy, size / 2 + 1.8, fill=1, stroke=0)
    else:
        c.roundRect(x - 1.5, y - 1.5, size + 3, size + 3, size * 0.18, fill=1, stroke=0)
    c.setFillColorRGB(*_lighten(accent, 0.75))
    if shape == 'circle':
        c.circle(cx, cy, size / 2, fill=1, stroke=0)
    else:
        c.roundRect(x, y, size, size, size * 0.18 if shape == 'rounded' else 0,
                    fill=1, stroke=0)
    c.setFillColorRGB(0.45, 0.42, 0.40)
    c.circle(cx, cy + size * 0.10, size * 0.18, fill=1, stroke=0)
    c.ellipse(cx - size * 0.28, cy - size * 0.40,
              cx + size * 0.28, cy - size * 0.05, fill=1, stroke=0)


def _autofit_font_size(c, text: str, font: str, max_w: float,
                       target: float, min_size: float, max_size: float) -> float:
    """Подбирает размер шрифта чтобы text занимал ~target ширины (но не шире max_w)."""
    if not text:
        return target
    w_at_1 = c.stringWidth(text, font, 1.0)
    if w_at_1 <= 0:
        return target
    ideal = target / w_at_1
    return max(min_size, min(max_size, ideal))


def _draw_node(c, node: dict, members_map: dict, fonts: dict,
               page_h: float, defaults: dict) -> None:
    x = float(node['x'])
    y_top = float(node['y'])
    w = float(node['width'])
    h = float(node['height'])
    y = _flip_y(y_top, h, page_h)

    style = {**defaults, **(node.get('style') or {})}
    member = members_map.get(str(node.get('memberId'))) if node.get('memberId') is not None else None
    member = member or node.get('member') or {}

    bg = _hex_to_rgb(style.get('bg_color', '#fdf9ec'))
    border = _hex_to_rgb(style.get('border_color', '#96723d'))
    text_main = _hex_to_rgb(style.get('text_color', '#3f2e14'))
    role_color = _hex_to_rgb(style.get('role_color', '#3f7a4d'))
    accent = _hex_to_rgb(style.get('accent_color', style.get('border_color', '#96723d')))
    radius = float(style.get('radius', 8))
    border_w = float(style.get('border_width', 1.4))
    font_scale = float(style.get('font_scale', 1.0))
    font_family = style.get('font_family') or defaults.get('font_family', 'serif')
    reg, bold, italic = _fonts_for(font_family)

    if style.get('shadow', True):
        c.saveState()
        try: c.setFillAlpha(0.22)
        except Exception: pass
        c.setFillColorRGB(*_darken(border, 0.3))
        c.roundRect(x + 2, y - 2, w, h, radius, fill=1, stroke=0)
        c.restoreState()

    c.setFillColorRGB(*bg)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=0)
    c.setStrokeColorRGB(*border)
    c.setLineWidth(border_w)
    c.roundRect(x, y, w, h, radius, fill=0, stroke=1)

    pad = max(6, min(14, radius * 0.8 + w * 0.04))
    inner_w = w - 2 * pad
    inner_h = h - 2 * pad

    show_photo = style.get('show_photo', True)
    show_dates = style.get('show_dates', True)
    show_patr = style.get('show_patronymic', True)
    show_role = style.get('show_role', True)

    # --- Подготавливаем строки текста ---
    name = ((member.get('lastName') or '') + ' ' + (member.get('firstName') or '')).strip()
    patr = (member.get('patronymic') or '').strip() if show_patr else ''
    role = ROLE_NAMES.get((member.get('role') or 'OTHER').upper(), 'Родственник') if show_role else ''
    birth = (member.get('birthDate') or '').strip() if show_dates else ''
    death = (member.get('deathDate') or '').strip() if show_dates else ''
    date_line = ''
    if show_dates and (birth or death):
        date_line = f'{birth} — {death}' if birth and death else birth or f'✝ {death}'

    text_lines = [(t, 'name') for t in ([name] if name else [])]
    if patr: text_lines.append((patr, 'patr'))
    if role: text_lines.append((role, 'role'))
    if date_line: text_lines.append((date_line, 'date'))

    # --- Распределение: фото vs текст ---
    # Количество строк -> минимальная доля для текста
    n_lines = len(text_lines)
    if show_photo:
        # чем меньше строк, тем крупнее фото; иначе — разумный баланс
        if n_lines <= 1: photo_frac = 0.72
        elif n_lines == 2: photo_frac = 0.62
        elif n_lines == 3: photo_frac = 0.55
        else: photo_frac = 0.48
        photo_frac = float(style.get('photo_frac', photo_frac))
        photo_area_h = inner_h * photo_frac
        text_area_h = inner_h - photo_area_h - 6
    else:
        photo_area_h = 0
        text_area_h = inner_h

    cur_y = y + h - pad

    # Рисуем фото квадратом в отведённой зоне
    if show_photo and photo_area_h > 12:
        ps = min(photo_area_h, inner_w)  # квадрат
        px = x + (w - ps) / 2
        py = cur_y - ps
        _draw_photo(c, member.get('photoBase64') or member.get('photoUri') or '',
                    px, py, ps, style.get('photo_shape', 'circle'), accent)
        cur_y = py - 4

    if n_lines == 0 or text_area_h <= 8:
        return

    # Распределяем текст по оставшейся высоте, подбирая размеры шрифтов.
    # Базовые размеры, масштабированные общим font_scale.
    base = 10 * font_scale
    weights = {
        'name': max(10, base + 2),
        'patr': max(7, base - 1),
        'role': max(8, base),
        'date': max(7, base - 1.5),
    }

    # Сумма «естественных» высот + межстрочные
    def line_gap(kind): return 2 if kind == 'name' else 1
    natural_total = sum(weights[k] for _, k in text_lines) + sum(line_gap(k) for _, k in text_lines)

    # Если не помещается — уменьшаем все размеры пропорционально
    if natural_total > text_area_h:
        k = text_area_h / natural_total
        for key in weights:
            weights[key] = max(6, weights[key] * k)

    # Отрисовка, авто-подгонка ширины имени
    for text, kind in text_lines:
        size = weights[kind]
        font = bold if kind == 'name' else (italic if kind == 'role' else reg)
        if kind == 'name':
            # Масштабируем имя так, чтобы оно заняло 90% ширины (но ограничено size + 50%)
            size = _autofit_font_size(c, text, font, inner_w * 0.92,
                                       target=inner_w * 0.92,
                                       min_size=max(7, size * 0.7),
                                       max_size=min(size * 1.6, inner_h * 0.28))
        display = _clip_text(c, text, font, size, inner_w)
        if kind == 'name': color = text_main
        elif kind == 'role': color = role_color
        elif kind == 'patr': color = _mix(text_main, (1, 1, 1), 0.25)
        else: color = _mix(text_main, (1, 1, 1), 0.4)
        c.setFillColorRGB(*color)
        c.setFont(font, size)
        c.drawCentredString(x + w / 2, cur_y - size, display)
        cur_y -= size + line_gap(kind)


def _anchor(node: dict, side: str, page_h: float) -> tuple[float, float]:
    x = float(node['x']); y = float(node['y'])
    w = float(node['width']); h = float(node['height'])
    cx = x + w / 2
    if side == 'top': px, py = cx, y
    elif side == 'bottom': px, py = cx, y + h
    elif side == 'left': px, py = x, y + h / 2
    elif side == 'right': px, py = x + w, y + h / 2
    else: px, py = cx, y + h / 2
    return px, page_h - py


def _best_sides(a: dict, b: dict) -> tuple[str, str]:
    ax = float(a['x']) + float(a['width']) / 2
    ay = float(a['y']) + float(a['height']) / 2
    bx = float(b['x']) + float(b['width']) / 2
    by = float(b['y']) + float(b['height']) / 2
    dx, dy = bx - ax, by - ay
    if abs(dy) >= abs(dx):
        return ('bottom' if dy > 0 else 'top',
                'top' if dy > 0 else 'bottom')
    return ('right' if dx > 0 else 'left',
            'left' if dx > 0 else 'right')


def _draw_edge(c, edge: dict, nodes_by_id: dict, page_h: float, defaults: dict):
    a = nodes_by_id.get(edge.get('from'))
    b = nodes_by_id.get(edge.get('to'))
    if not a or not b:
        return
    style = {**defaults, **(edge.get('style') or {})}
    color = _hex_to_rgb(style.get('color', '#7a5d32'))
    width = float(style.get('width', 1.4))
    kind = style.get('kind', 'orthogonal')

    side_a = edge.get('from_side')
    side_b = edge.get('to_side')
    if not side_a or not side_b:
        side_a, side_b = _best_sides(a, b)

    x1, y1 = _anchor(a, side_a, page_h)
    x2, y2 = _anchor(b, side_b, page_h)
    c.setStrokeColorRGB(*color)
    c.setLineWidth(width)

    if kind == 'straight':
        c.line(x1, y1, x2, y2)
    elif kind == 'curve':
        p = c.beginPath()
        p.moveTo(x1, y1)
        if side_a in ('top', 'bottom'):
            cy = (y1 + y2) / 2
            p.curveTo(x1, cy, x2, cy, x2, y2)
        else:
            cx = (x1 + x2) / 2
            p.curveTo(cx, y1, cx, y2, x2, y2)
        c.drawPath(p, fill=0, stroke=1)
    else:  # orthogonal
        if side_a in ('top', 'bottom') and side_b in ('top', 'bottom'):
            mid = (y1 + y2) / 2
            c.line(x1, y1, x1, mid); c.line(x1, mid, x2, mid); c.line(x2, mid, x2, y2)
        elif side_a in ('left', 'right') and side_b in ('left', 'right'):
            mid = (x1 + x2) / 2
            c.line(x1, y1, mid, y1); c.line(mid, y1, mid, y2); c.line(mid, y2, x2, y2)
        else:
            c.line(x1, y1, x2, y1); c.line(x2, y1, x2, y2)

    if style.get('marker', True):
        c.setFillColorRGB(*color)
        c.circle(x2, y2, 2.4, fill=1, stroke=0)


def render_family_tree_pdf_v3(
    *,
    nodes: list[dict],
    edges: list[dict] | None,
    members_map: dict[str, dict],
    filename: str,
    page_format: str = 'A4_LANDSCAPE',
    background: dict | None = None,
    title: str | None = None,
    show_header: bool = False,
    show_footer: bool = True,
    theme: str = 'paper',
    font_family: str = 'serif',
    defaults: dict | None = None,
) -> None:
    pagesize = _page_size(page_format)
    width, height = pagesize
    c = canvas.Canvas(filename, pagesize=pagesize)

    cfg = PdfV2Config(
        theme=theme, font_family=font_family,
        title=title or 'Семейное Древо',
        show_footer=show_footer, show_subtitle=False,
        show_tree=False, show_leaves=False, show_corners=False, double_frame=False,
        background=background,
        page_format=page_format,
    )
    _draw_background(c, width, height, cfg)

    # Если хотим заголовок поверх и пользовательские карточки наезжают — сдвинем их.
    header_reserve = 90 if (show_header and title) else 0
    if show_header and title:
        _draw_header(c, width, height, cfg)

    node_defaults = {
        'font_family': font_family,
        'shadow': True, 'show_photo': True, 'show_dates': True,
        'show_patronymic': True, 'show_role': True, 'radius': 8,
        'border_width': 1.4, 'font_scale': 1.0,
        'photo_shape': 'circle',
        'bg_color': '#fdf9ec', 'border_color': '#96723d',
        'text_color': '#3f2e14', 'role_color': '#3f7a4d',
        'accent_color': '#96723d',
        **(defaults or {}),
    }
    edge_defaults = {'kind': 'orthogonal', 'color': '#7a5d32', 'width': 1.4, 'marker': True}

    nodes_by_id = {n.get('id'): n for n in nodes if n.get('id')}

    # Если задан header_reserve, сдвигаем узлы которые попадают в зону заголовка.
    shifted_nodes = nodes
    if header_reserve > 0:
        # найти минимальный y среди узлов
        min_y = min((float(n.get('y', 0)) for n in nodes), default=0)
        if min_y < header_reserve:
            dy = header_reserve - min_y
            shifted_nodes = []
            for n in nodes:
                nn = dict(n)
                nn['y'] = float(n.get('y', 0)) + dy
                shifted_nodes.append(nn)
            nodes_by_id = {n.get('id'): n for n in shifted_nodes if n.get('id')}

    for e in (edges or []):
        _draw_edge(c, e, nodes_by_id, height, edge_defaults)

    fonts = {f: _fonts_for(f) for f in {font_family, 'sans', 'serif', 'mono'}}
    for n in shifted_nodes:
        _draw_node(c, n, members_map, fonts, height, node_defaults)

    if show_footer:
        _draw_footer(c, width, cfg)

    c.save()
