#!/usr/bin/env python3
"""Stage 4 · 拼页 + 对话气泡（PIL）

输入:
  $MANGA_ROOT/output/panels_passed/<panel_id>.png
  $MANGA_ROOT/script_json/<chapter>.json
输出:
  $MANGA_ROOT/output/pages/page_{NN}.png      # 2480 × 3508 @ 300dpi

支持 layout:
  6-panel-standard    2x3 格子
  4-panel-action      垂直条漫 (webtoon)
  8-panel-dense       4x2 密集
  splash              全页单图

用法:
  python scripts/04_layout_page.py --chapter chapter_01
  python scripts/04_layout_page.py --chapter chapter_01 --no-bubbles
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

try:
    from scripts._common import ROOT
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts._common import ROOT


PAGE_W, PAGE_H = 2480, 3508      # A4 300dpi
MARGIN = 60
GUTTER = 40

FONT_CANDIDATES = [
    ROOT / "fonts" / "SourceHanSansSC-Bold.otf",
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]


def find_font() -> Path:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("未找到中文字体，请把 SourceHanSansSC-Bold.otf 放到 $MANGA_ROOT/fonts/")


def layout_6_standard() -> list[tuple[int, int, int, int]]:
    """2x3 standard, middle row occasionally emphasizes one panel."""
    col_w = (PAGE_W - 2 * MARGIN - GUTTER) // 2
    row_h = (PAGE_H - 2 * MARGIN - 2 * GUTTER) // 3
    boxes = []
    for row in range(3):
        for col in range(2):
            x1 = MARGIN + col * (col_w + GUTTER)
            y1 = MARGIN + row * (row_h + GUTTER)
            boxes.append((x1, y1, x1 + col_w, y1 + row_h))
    return boxes


def layout_4_action() -> list[tuple[int, int, int, int]]:
    """Vertical webtoon: 4 stacked panels."""
    panel_h = (PAGE_H - 2 * MARGIN - 3 * GUTTER) // 4
    w = PAGE_W - 2 * MARGIN
    boxes = []
    for i in range(4):
        y1 = MARGIN + i * (panel_h + GUTTER)
        boxes.append((MARGIN, y1, MARGIN + w, y1 + panel_h))
    return boxes


def layout_8_dense() -> list[tuple[int, int, int, int]]:
    """4x2 dense grid."""
    col_w = (PAGE_W - 2 * MARGIN - 3 * GUTTER) // 4
    row_h = (PAGE_H - 2 * MARGIN - GUTTER) // 2
    boxes = []
    for row in range(2):
        for col in range(4):
            x1 = MARGIN + col * (col_w + GUTTER)
            y1 = MARGIN + row * (row_h + GUTTER)
            boxes.append((x1, y1, x1 + col_w, y1 + row_h))
    return boxes


def layout_splash() -> list[tuple[int, int, int, int]]:
    """Full-page single panel."""
    return [(MARGIN, MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN)]


LAYOUTS = {
    "6-panel-standard": layout_6_standard,
    "4-panel-action": layout_4_action,
    "8-panel-dense": layout_8_dense,
    "splash": layout_splash,
}


def wrap_text(text: str, max_per_line: int = 10) -> str:
    lines = []
    cur = ""
    for ch in text:
        cur += ch
        if len(cur) >= max_per_line:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def draw_bubble(canvas: Image.Image, panel_box: tuple, text: str,
                 font_path: Path, anchor: str = "top-right") -> None:
    if not text:
        return
    x1, y1, x2, y2 = panel_box
    pw, ph = x2 - x1, y2 - y1

    font_size = max(22, min(36, pw // 24))
    font = ImageFont.truetype(str(font_path), font_size)

    wrapped = wrap_text(text, max_per_line=10)
    lines = wrapped.count("\n") + 1
    line_h = font_size + 8
    text_w = min(font_size * 11, pw * 2 // 3)
    bubble_w = text_w + 60
    bubble_h = lines * line_h + 60

    pad = 30
    if "right" in anchor:
        bx1 = x2 - bubble_w - pad
    else:
        bx1 = x1 + pad
    if "bottom" in anchor:
        by1 = y2 - bubble_h - pad
    else:
        by1 = y1 + pad

    bx2, by2 = bx1 + bubble_w, by1 + bubble_h

    d = ImageDraw.Draw(canvas)
    # Slight shadow
    d.ellipse([bx1 + 4, by1 + 4, bx2 + 4, by2 + 4], fill=(0, 0, 0, 80))
    d.ellipse([bx1, by1, bx2, by2], fill="white", outline="black", width=4)

    # Tail (simple triangle pointing into the panel)
    if "right" in anchor:
        tail = [(bx1 + bubble_w * 0.3, by2 - 5),
                (bx1 + bubble_w * 0.2, by2 + 30),
                (bx1 + bubble_w * 0.45, by2 - 5)]
    else:
        tail = [(bx1 + bubble_w * 0.55, by2 - 5),
                (bx1 + bubble_w * 0.8, by2 + 30),
                (bx1 + bubble_w * 0.7, by2 - 5)]
    d.polygon(tail, fill="white", outline="black")

    d.multiline_text(
        (bx1 + 30, by1 + 25),
        wrapped,
        fill="black",
        font=font,
        spacing=6,
    )


def compose_page(page: dict, font_path: Path, draw_bubbles: bool = True) -> Image.Image:
    canvas = Image.new("RGB", (PAGE_W, PAGE_H), "white")

    layout_name = page.get("layout", "6-panel-standard")
    layout_fn = LAYOUTS.get(layout_name, layout_6_standard)
    boxes = layout_fn()
    panels = page["panels"][:len(boxes)]

    for panel, box in zip(panels, boxes):
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1

        img_path = ROOT / "output" / "panels_passed" / f"{panel['panel_id']}.png"
        if not img_path.exists():
            # Fallback to raw
            img_path = ROOT / "output" / "panels_raw" / f"{panel['panel_id']}.png"
        if not img_path.exists():
            # Placeholder
            placeholder = Image.new("RGB", (w, h), "#ffeeee")
            pd = ImageDraw.Draw(placeholder)
            pd.text((20, 20), f"MISSING\n{panel['panel_id']}", fill="red")
            canvas.paste(placeholder, (x1, y1))
            continue

        img = Image.open(img_path).convert("RGB")
        # Center-crop to aspect
        src_w, src_h = img.size
        target_ar = w / h
        src_ar = src_w / src_h
        if src_ar > target_ar:
            new_w = int(src_h * target_ar)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / target_ar)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))
        img = img.resize((w, h), Image.LANCZOS)
        canvas.paste(img, (x1, y1))

        # Panel border
        ImageDraw.Draw(canvas).rectangle(box, outline="black", width=6)

        # Speech bubble
        if draw_bubbles and panel.get("dialog"):
            anchor = panel.get("bubble_anchor", "top-right")
            draw_bubble(canvas, box, panel["dialog"], font_path, anchor=anchor)

    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter_01")
    ap.add_argument("--no-bubbles", action="store_true")
    args = ap.parse_args()

    script_path = ROOT / "script_json" / f"{args.chapter}.json"
    if not script_path.exists():
        sys.exit(f"✗ 分镜不存在: {script_path}")

    script = json.loads(script_path.read_text())
    font_path = find_font()
    pages_dir = ROOT / "output" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    for page in script["pages"]:
        canvas = compose_page(page, font_path, draw_bubbles=not args.no_bubbles)
        out = pages_dir / f"{args.chapter}_page_{page['page_id']:02d}.png"
        canvas.save(out, dpi=(300, 300))
        print(f"✓ {out}")

    print(f"\n完成 {len(script['pages'])} 页 → {pages_dir}")


if __name__ == "__main__":
    main()
