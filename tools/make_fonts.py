#!/usr/bin/env python3
"""Generate LVGL 9 Chinese font with Montserrat fallback for Codex Passport."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def pack_4bpp(pixels: list[int], width: int, height: int) -> list[int]:
    # LVGL's plain format has no per-row padding (including odd widths).
    values = pixels[:width * height]
    return [((values[i] >> 4) << 4) |
            ((values[i + 1] >> 4) if i + 1 < len(values) else 0)
            for i in range(0, len(values), 2)]


def glyph_metrics(font: ImageFont.FreeTypeFont, ch: str) -> dict:
    left, top, right, bottom = font.getbbox(ch)
    box_w = max(0, right - left)
    box_h = max(0, bottom - top)
    image = Image.new("L", (max(box_w, 1), max(box_h, 1)), 0)
    draw = ImageDraw.Draw(image)
    draw.text((-left, -top), ch, font=font, fill=255)
    pixels = list(image.getdata())
    ascent, descent = font.getmetrics()
    return {
        "cp": ord(ch),
        "adv_w": int(round(font.getlength(ch) * 16)),
        "box_w": box_w,
        "box_h": box_h,
        "ofs_x": left,
        "ofs_y": ascent - bottom,
        "bitmap": pack_4bpp(pixels, box_w, box_h),
    }


def emit_font(name: str, size: int, chars: list[str], destination: Path, font_path: Path) -> None:
    font = ImageFont.truetype(str(font_path), size=size)
    ascent, descent = font.getmetrics()
    glyphs = [glyph_metrics(font, ch) for ch in sorted(chars, key=ord)]

    bitmap_bytes: list[int] = []
    glyph_records: list[str] = []
    offset = 0

    for g in glyphs:
        glyph_records.append(
            f"    {{.bitmap_index = {offset}, .adv_w = {g['adv_w']}, "
            f".box_w = {g['box_w']}, .box_h = {g['box_h']}, "
            f".ofs_x = {g['ofs_x']}, .ofs_y = {g['ofs_y']}}},"
        )
        bitmap_bytes.extend(g["bitmap"])
        offset += len(g["bitmap"])

    range_start = glyphs[0]["cp"]
    unicode_offsets = [g["cp"] - range_start for g in glyphs]
    if unicode_offsets != sorted(unicode_offsets) or unicode_offsets[-1] > 0xFFFF:
        raise ValueError(f"{name}: sparse cmap offsets must be sorted 16-bit values")

    unicode_list = ", ".join(f"0x{offset:x}" for offset in unicode_offsets)
    bitmap_lines = [
        "    " + ", ".join(f"0x{b:x}" for b in bitmap_bytes[i : i + 12]) + ","
        for i in range(0, len(bitmap_bytes), 12)
    ]
    guard = name.upper()

    body = f"""/*******************************************************************************
 * Size: {size} px
 * Bpp: 4
 * Characters: {len(glyphs)}
 ******************************************************************************/

#include "lvgl.h"

#if !LV_FONT_FMT_TXT_LARGE
#error "Passport font requires CONFIG_LV_FONT_FMT_TXT_LARGE=y"
#endif

#ifndef {guard}
#define {guard} 1
#endif

#if {guard}

static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap[] = {{
{chr(10).join(bitmap_lines)}
}};

static const lv_font_fmt_txt_glyph_dsc_t glyph_dsc[] = {{
    {{.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0}},
{chr(10).join(glyph_records)}
}};

static const uint16_t unicode_list_0[] = {{
    {unicode_list}
}};

static const lv_font_fmt_txt_cmap_t cmaps[] = {{
    {{
        .range_start = 0x{range_start:x},
        .range_length = {unicode_offsets[-1] + 1},
        .glyph_id_start = 1,
        .unicode_list = unicode_list_0,
        .glyph_id_ofs_list = NULL,
        .list_length = {len(glyphs)},
        .type = LV_FONT_FMT_TXT_CMAP_SPARSE_TINY
    }}
}};

static lv_font_fmt_txt_dsc_t font_dsc = {{
    .glyph_bitmap = glyph_bitmap,
    .glyph_dsc = glyph_dsc,
    .cmaps = cmaps,
    .kern_dsc = NULL,
    .kern_scale = 0,
    .cmap_num = 1,
    .bpp = 4,
    .kern_classes = 0,
    .bitmap_format = 0,
}};

const lv_font_t {name} = {{
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,
    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = 20,
    .base_line = 4,
    .subpx = LV_FONT_SUBPX_NONE,
    .underline_position = -2,
    .underline_thickness = 1,
    .dsc = &font_dsc,
    .fallback = &lv_font_montserrat_14,
    .user_data = NULL,
}};

#endif /* {guard} */
"""
    destination.write_text(body, encoding="utf-8")


def main() -> None:
    from fontTools.ttLib import TTFont
    font_path = Path(__file__).resolve().parent.parent / "assets/fonts/PassportSans.ttf"
    with TTFont(font_path) as source:
        # Fixed BMP coverage, independent of local task titles and private data.
        chars = [chr(cp) for cp in sorted(source.getBestCmap())
                 if 0x20 <= cp < 0xFFFF and chr(cp).isprintable()]

    (font_path.parent / "charset.txt").write_text("".join(chars), encoding="utf-8")
    dest = Path(__file__).resolve().parent.parent / "main" / "font_passport_16.c"
    print(f"Generating {len(chars)} Hanzi glyphs to {dest}...")
    emit_font("font_passport_16", 16, chars, dest, font_path)
    print("Done!")


if __name__ == "__main__":
    main()
