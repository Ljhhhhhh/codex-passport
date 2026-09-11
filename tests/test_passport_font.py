import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from passport_protocol import encode_text, supported_chars


class FontTests(unittest.TestCase):
    def test_packing_and_coverage(self):
        # Execute the pure packing function without requiring Pillow in the host gate.
        tree = ast.parse((ROOT / "tools/make_fonts.py").read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pack_4bpp")
        scope = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "pack", "exec"), scope)
        self.assertEqual(scope["pack_4bpp"]([0x10, 0x20, 0x30, 0x40, 0x50, 0x60], 3, 2), [0x12, 0x34, 0x56])
        self.assertTrue(set("社区中有已经把它改造成好的现在创建技能龘繁體同步异常") <= supported_chars())
        source = (ROOT / "main/font_passport_16.c").read_text()
        offsets = re.search(r"unicode_list_0\[\] = \{(.*?)\};", source, re.S).group(1)
        start = int(re.search(r"\.range_start = (0x[0-9a-f]+)", source).group(1), 16)
        actual = {chr(start + int(x, 16)) for x in re.findall(r"0x[0-9a-f]+", offsets)}
        self.assertEqual(actual, supported_chars())
        records = [tuple(map(int, m)) for m in re.findall(
            r"\.bitmap_index = (\d+), \.adv_w = \d+, \.box_w = (\d+), \.box_h = (\d+)", source)]
        offset = 0
        for index, width, height in records[1:]:
            self.assertEqual(index, offset)
            offset += (width * height + 1) // 2
        bitmap = source.split("glyph_bitmap[] = {")[1].split("};")[0]
        self.assertEqual(len(re.findall(r"0x[0-9a-f]+", bitmap)), offset)
        self.assertIn("CONFIG_LV_FONT_FMT_TXT_LARGE=y", (ROOT / "sdkconfig.defaults").read_text())
        self.assertEqual(encode_text("你好世界", 7).decode(), "你好")
        self.assertEqual(encode_text("好\x00的😀", 30).decode(), "好 的?")


if __name__ == "__main__":
    unittest.main()
