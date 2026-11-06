"""Pillow brend shabloni: AI rasm (yoki brend fon) + o'zbekcha sarlavha + kategoriya + suv belgisi."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.ai.types import aspect_ratio

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = ROOT / "assets" / "fonts"
FONT_BOLD = FONT_DIR / "Inter-Bold.ttf"
FONT_SEMI = FONT_DIR / "Inter-SemiBold.ttf"

NAVY = (11, 31, 58)
NAVY_LIGHT = (20, 52, 92)
CYAN = (0, 194, 255)
WHITE = (255, 255, 255)
BRAND = {"navy": "#0B1F3A", "cyan": "#00C2FF", "white": "#FFFFFF"}

_SIZES = {"1:1": (1080, 1080), "16:9": (1280, 720), "9:16": (720, 1280)}


def canvas_size(image_size: str) -> tuple[int, int]:
    return _SIZES.get(aspect_ratio(image_size), (1080, 1080))


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _brand_background(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (*NAVY, 255))
    draw = ImageDraw.Draw(img)
    for y in range(h):  # yuqoridan pastga yengil gradient
        t = y / max(h - 1, 1)
        color = tuple(int(NAVY_LIGHT[i] * (1 - t) + NAVY[i] * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=(*color, 255))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    step = max(w // 18, 24)
    for x in range(step // 2, w, step):  # nuqtali texnologik to'r
        for y in range(step // 2, int(h * 0.62), step):
            ld.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(*CYAN, 40))
    cx, cy = int(w * 0.78), int(h * 0.22)
    for i, r in enumerate((int(h * 0.12), int(h * 0.2), int(h * 0.3))):
        ld.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*CYAN, 110 - i * 30), width=max(2, w // 360))
    ld.line([(int(w * 0.08), int(h * 0.55)), (int(w * 0.5), int(h * 0.12))], fill=(*CYAN, 60), width=3)
    return Image.alpha_composite(img, layer)


def _wrap(
    draw: ImageDraw.ImageDraw, words: list[str], font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in words:
        while draw.textlength(word, font=font) > max_width and len(word) > 1:  # juda uzun so'z
            cut = len(word)
            while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                cut -= 1
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:cut])
            word = word[cut:]
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def layout_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int = 3,
    max_size: int = 72,
    min_size: int = 36,
    font_path: Path = FONT_BOLD,
) -> tuple[int, list[str]]:
    """Sarlavhani eng katta mos shrift o'lchami bilan qatorlarga bo'ladi; sig'masa '…' bilan qisqartiradi."""
    words = text.split()
    if not words:
        return max_size, []
    for size in range(max_size, min_size - 1, -2):
        lines = _wrap(draw, words, _font(font_path, size), max_width)
        if len(lines) <= max_lines:
            return size, lines
    font = _font(font_path, min_size)
    lines = _wrap(draw, words, font, max_width)[:max_lines]
    last = lines[-1]
    while last and draw.textlength(last + "…", font=font) > max_width:
        last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
    lines[-1] = last.rstrip(" ,.:;—-") + "…"
    return min_size, lines


def render_cover(
    base: bytes | None,
    *,
    title: str,
    category: str,
    username: str,
    size: tuple[int, int] = (1080, 1080),
) -> bytes:
    w, h = size
    if base is not None:
        src = Image.open(BytesIO(base))
        src.load()
        canvas = ImageOps.fit(src.convert("RGB"), size, Image.Resampling.LANCZOS, centering=(0.5, 0.4))
        canvas = canvas.convert("RGBA")
    else:
        canvas = _brand_background(size)
    margin = int(min(w, h) * 0.06)

    # Pastki qismda o'qilishi uchun to'q gradient
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    start = int(h * 0.42)
    for y in range(start, h):
        alpha = int(235 * ((y - start) / max(h - start, 1)) ** 1.2)
        od.line([(0, y), (w, y)], fill=(*NAVY, alpha))

    # Kategoriya belgisi
    if category:
        font = _font(FONT_SEMI, max(int(h * 0.028), 18))
        pad_x, pad_y = int(font.size * 0.8), int(font.size * 0.45)
        tw = int(od.textlength(category, font=font))
        box = [margin, margin, margin + tw + 2 * pad_x, margin + font.size + 2 * pad_y]
        od.rounded_rectangle(box, radius=font.size // 2 + pad_y, fill=(*CYAN, 240))
        od.text(
            (margin + pad_x, margin + pad_y - int(font.size * 0.12)), category, font=font, fill=(*NAVY, 255)
        )

    # Suv belgisi (kanal username)
    if username:
        font = _font(FONT_SEMI, max(int(h * 0.026), 16))
        tw = int(od.textlength(username, font=font))
        od.text((w - margin - tw, h - margin - font.size), username, font=font, fill=(*WHITE, 200))

    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    # Sarlavha
    if title.strip():
        size_px, lines = layout_title(
            draw,
            title.strip(),
            max_width=w - 2 * margin,
            max_lines=3,
            max_size=max(int(h * 0.068), 28),
            min_size=max(int(h * 0.036), 20),
        )
        font = _font(FONT_BOLD, size_px)
        line_h = int(size_px * 1.2)
        bottom = h - margin - int(h * 0.06)
        y = bottom - line_h * len(lines)
        bar_top = y - int(size_px * 0.55)
        draw.rectangle([margin, bar_top, margin + int(w * 0.075), y - int(size_px * 0.42)], fill=(*CYAN, 255))
        for line in lines:
            draw.text((margin, y), line, font=font, fill=(*WHITE, 255))
            y += line_h

    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
