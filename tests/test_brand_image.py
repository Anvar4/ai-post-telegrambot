from io import BytesIO

from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw, ImageStat

from app.content.brand_image import FONT_BOLD, canvas_size, layout_title, render_cover

TITLE = "Chrome brauzerida jiddiy zaiflik: tezda yangilang"


def open_png(data: bytes) -> Image.Image:
    img = Image.open(BytesIO(data))
    assert img.format == "PNG"
    return img


def test_font_has_uz_glyphs() -> None:
    cmap = TTFont(str(FONT_BOLD)).getBestCmap()
    for ch in "ʻʼ‘’…oOgG":
        assert ord(ch) in cmap, f"shriftda {ch!r} yo'q"


def test_render_cover_png_size() -> None:
    img = open_png(render_cover(None, title=TITLE, category="KIBERXAVFSIZLIK", username="@it_dunyosi"))
    assert img.size == (1080, 1080)


def test_canvas_size_from_aspect() -> None:
    assert canvas_size("1024x1024") == (1080, 1080)
    assert canvas_size("1536x1024") == (1280, 720)


def test_render_with_base_image_crops_to_canvas() -> None:
    buf = BytesIO()
    Image.new("RGB", (1536, 1024), (200, 50, 50)).save(buf, format="PNG")
    img = open_png(
        render_cover(buf.getvalue(), title=TITLE, category="YANGILIK", username="@x", size=(1080, 1080))
    )
    assert img.size == (1080, 1080)
    # yuqori qismda asosiy rasm rangi saqlangan
    r, g, _b = img.convert("RGB").getpixel((540, 300))
    assert r > 150 and g < 100


def test_title_is_drawn_in_bottom_third() -> None:
    with_title = open_png(render_cover(None, title=TITLE, category="YANGILIK", username=""))
    without = open_png(render_cover(None, title="", category="YANGILIK", username=""))
    box = (0, 720, 1080, 1080)
    diff = ImageChops.difference(with_title.convert("RGB").crop(box), without.convert("RGB").crop(box))
    assert max(ImageStat.Stat(diff).extrema[0][1], ImageStat.Stat(diff).extrema[1][1]) > 100


def test_long_title_wraps_not_overflow() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1080)))
    long_title = "Oʻzbekistondagi foydalanuvchilar uchun juda muhim va uzun sarlavha " * 3
    size, lines = layout_title(draw, long_title, max_width=960, max_lines=3)
    assert 1 <= len(lines) <= 3
    from PIL import ImageFont

    font = ImageFont.truetype(str(FONT_BOLD), size)
    for line in lines:
        assert draw.textlength(line, font=font) <= 960
    assert lines[-1].endswith("…")


def test_short_title_single_line_large_font() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1080)))
    size, lines = layout_title(draw, "AI yangiligi", max_width=960, max_lines=3)
    assert lines == ["AI yangiligi"]
    assert size >= 60


def test_invalid_base_raises() -> None:
    try:
        render_cover(b"not an image", title=TITLE, category="X", username="")
    except Exception:
        return
    raise AssertionError("buzilgan rasm xato berishi kerak")
