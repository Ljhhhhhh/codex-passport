#!/usr/bin/env python3
"""Generate LVGL 9 Chinese font with Montserrat fallback for Codex Passport."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PASSPORT_HANZI = (
    # Personal profile
    "姓名兴趣签名主页读书开发运动难是幸福的开始持之以恒知行合一追求卓越热爱生活"
    "签发日期机器可读区身份认证个人资料数字护照机主凭证"
    # Mileage & stats
    "里程数据统计总消耗今日用量本周活跃连续天数峰值活跃度历史累计总用量"
    # 13-week heatmap
    "活跃热力图日历周一二三四五六日低中高极度贡献"
    # Footprints & topics
    "开发足迹技术主题首次涉足首次出现累计消耗嵌入式硬件前端后端架构系统网络服务数据库组件智能体模型代码新建文件夹"
   # Focus directions
   "近三十天活跃方向项目名称占比排名进度最活跃"
   # Realtime states & status bar
    "状态空闲运行中等待操作完成异常电量充放电蓝牙已连接未连接断开重连正在同步按键翻页二维码暂无消息待回复失败"
   # Numbers & common Chinese characters
   "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就会可也你对能而子那得于着下自之年过发后"
    "方道行所然家种事成多么如前面起实日意样理手情法所去各见本高无意此向合现月文已明感公制它应机走各十点使通三"
    "两二四五六七八九十百千万亿元第问想实者正新反由分间重更外特头直表总最加主老经长题开已解等受关目部建安化政"
)


def is_cjk_or_punct(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF or      # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or      # CJK Extension A
        0x3000 <= cp <= 0x303F or      # CJK Symbols and Punctuation (、，。etc)
        0xFF00 <= cp <= 0xFFEF or      # Halfwidth and Fullwidth Forms (！：；（）etc)
        0x2000 <= cp <= 0x206F or      # General Punctuation (—…“”‘’• etc)
        cp in (0xB7, 0x223C)           # Middle dot, tilde
    )


def unique_hanzi(text: str) -> list[str]:
    seen: set[str] = set()
    chars: list[str] = []
    puncts = "、，。？！：；“”‘’（）—…《》【】·•～"
    for ch in puncts:
        if ch not in seen:
            seen.add(ch)
            chars.append(ch)
    for ch in text:
        if is_cjk_or_punct(ch) and ch not in seen:
            seen.add(ch)
            chars.append(ch)
    return sorted(chars, key=ord)


def pack_4bpp(pixels: list[int], width: int, height: int) -> list[int]:
    row_bytes = (width + 1) // 2
    data: list[int] = []
    for y in range(height):
        for x in range(0, row_bytes * 2, 2):
            hi = pixels[y * width + x] if x < width else 0
            lo = pixels[y * width + x + 1] if x + 1 < width else 0
            data.append(((hi >> 4) << 4) | (lo >> 4))
    return data


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
    .line_height = {ascent + descent},
    .base_line = {descent},
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
    title_chars = ""
    try:
        import os
        import json
        state_path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / ".codex-global-state.json"
        if state_path.is_file():
            data = json.loads(state_path.read_text())
            desc = data.get("electron-persisted-atom-state", {}).get("thread-descriptions-v1", {})
            title_chars = "".join(c for t in desc.values() if isinstance(t, str) for c in t if is_cjk_or_punct(c))
    except Exception:
        pass
    chars = unique_hanzi(PASSPORT_HANZI + title_chars)
    font_path = Path("/System/Library/Fonts/STHeiti Medium.ttc")
    if not font_path.exists():
        font_path = Path("/Library/Fonts/Arial Unicode.ttf")

    dest = Path(__file__).resolve().parent.parent / "main" / "font_passport_16.c"
    print(f"Generating {len(chars)} Hanzi glyphs to {dest}...")
    emit_font("font_passport_16", 16, chars, dest, font_path)
    print("Done!")


if __name__ == "__main__":
    main()
