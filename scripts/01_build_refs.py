#!/usr/bin/env python3
"""Stage 1 · 角色参考库构建（FLUX.1-dev + PuLID）

输入:
  $MANGA_ROOT/refs/<char_id>/face_ref.png   # 正脸照片
  $MANGA_ROOT/story/characters.json         # 角色设定
输出:
  $MANGA_ROOT/refs/<char_id>/views/         # 四视图
  $MANGA_ROOT/refs/<char_id>/expressions/   # 8 表情
  $MANGA_ROOT/refs/<char_id>/outfits/       # N 服装

用法:
  python scripts/01_build_refs.py                         # 所有角色
  python scripts/01_build_refs.py --char lin_shu          # 单角色
  python scripts/01_build_refs.py --char lin_shu --only expressions
"""
from __future__ import annotations
import argparse
import json
import sys
import shutil
from pathlib import Path

try:
    from scripts._common import ROOT, load_workflow, queue_workflow, panel_seed
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts._common import ROOT, load_workflow, queue_workflow, panel_seed


EXPRESSIONS = [
    "neutral calm expression",
    "smiling warmly",
    "surprised with wide eyes",
    "angry frowning",
    "melancholic downcast eyes",
    "laughing out loud",
    "crying with tears",
    "closed eyes peaceful",
]

VIEW_ANGLES = [
    ("front_view", "front view, facing camera directly"),
    ("three_quarter_left", "3/4 left turn, head slightly turned right"),
    ("side_profile", "full side profile, facing left"),
    ("back_view", "back view, facing away from camera"),
]


def build_prompt(char: dict, variant_desc: str, style: str, is_fullbody: bool = False) -> str:
    appearance = char.get("appearance", "")
    parts = [
        "character reference sheet,",
        f"{char['name']}, {char.get('age','')} years old {char.get('gender','')}",
        appearance,
        variant_desc,
        "full body, T-pose neutral stance," if is_fullbody else "bust shot,",
        "studio white background, soft even lighting,",
        style,
    ]
    return " ".join(p for p in parts if p)


def gen_with_pulid(ref_image: Path, prompt: str, out_name: str,
                   width: int = 1024, height: int = 1536,
                   pulid_weight: float = 0.95) -> Path:
    """Build & submit a ComfyUI PuLID workflow for a single reference image."""
    wf = load_workflow("01_char_ref_pulid.json")

    # Patch workflow parameters (node IDs match the JSON template)
    # Upload the ref image first by copying to ComfyUI/input/
    comfy_input = ROOT / "ComfyUI" / "input"
    comfy_input.mkdir(parents=True, exist_ok=True)
    staged = comfy_input / ref_image.name
    if not staged.exists() or staged.stat().st_mtime < ref_image.stat().st_mtime:
        shutil.copy2(ref_image, staged)

    wf["10"]["inputs"]["image"] = ref_image.name                # LoadImage
    wf["15"]["inputs"]["text"] = prompt                          # positive prompt
    wf["17"]["inputs"]["width"] = width
    wf["17"]["inputs"]["height"] = height
    wf["18"]["inputs"]["seed"] = panel_seed(out_name)
    wf["20"]["inputs"]["weight"] = pulid_weight
    wf["22"]["inputs"]["filename_prefix"] = out_name

    files = queue_workflow(wf, timeout=300)
    if not files:
        raise RuntimeError(f"No output for {out_name}")

    produced = ROOT / "ComfyUI" / "output" / files[0]
    return produced


def build_char_refs(char: dict, style: str, only: str | None = None) -> None:
    char_id = char["id"]
    char_dir = ROOT / "refs" / char_id
    face_ref = char_dir / "face_ref.png"

    if not face_ref.exists():
        print(f"✗ 跳过 {char_id}: 缺 face_ref.png")
        return

    (char_dir / "views").mkdir(exist_ok=True)
    (char_dir / "expressions").mkdir(exist_ok=True)
    (char_dir / "outfits").mkdir(exist_ok=True)

    # 1. 四视图（最重要，作为后续 Kontext 基础参考）
    if not only or only == "views":
        print(f"==> [{char_id}] 四视图")
        combined_prompt = build_prompt(
            char,
            "four-view turnaround: front, 3/4 left, full side profile, back view, "
            "displayed side by side in one image",
            style, is_fullbody=True,
        )
        out = gen_with_pulid(face_ref, combined_prompt,
                             f"{char_id}_views_fourview", width=2048, height=1024)
        shutil.copy2(out, char_dir / "views" / "four_view.png")

    # 2. 8 表情
    if not only or only == "expressions":
        for expr in EXPRESSIONS:
            name = expr.split(",")[0].replace(" ", "_")
            out_file = char_dir / "expressions" / f"{name}.png"
            if out_file.exists():
                continue
            print(f"==> [{char_id}] 表情: {expr}")
            prompt = build_prompt(char, expr, style)
            out = gen_with_pulid(face_ref, prompt, f"{char_id}_expr_{name}",
                                 width=1024, height=1024)
            shutil.copy2(out, out_file)

    # 3. N 套服装（从 characters.json 读 outfits 字段）
    if not only or only == "outfits":
        outfits = char.get("outfits", [])
        for outfit in outfits:
            name = "".join(c if c.isalnum() else "_" for c in outfit)[:32]
            out_file = char_dir / "outfits" / f"{name}.png"
            if out_file.exists():
                continue
            print(f"==> [{char_id}] 服装: {outfit}")
            prompt = build_prompt(char, f"wearing {outfit}", style, is_fullbody=True)
            out = gen_with_pulid(face_ref, prompt, f"{char_id}_outfit_{name}",
                                 width=1024, height=1536)
            shutil.copy2(out, out_file)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", default=None, help="只跑这一个角色 ID")
    ap.add_argument("--only", choices=["views", "expressions", "outfits"],
                    default=None, help="只跑这一个环节")
    ap.add_argument("--chapter", default="chapter_01")
    args = ap.parse_args()

    script_path = ROOT / "script_json" / f"{args.chapter}.json"
    if script_path.exists():
        script = json.loads(script_path.read_text())
        characters = script["characters"]
        style = script.get("style_tail", "manga style, detailed linework, ink shading, 8k")
    else:
        char_file = ROOT / "story" / "characters.json"
        if not char_file.exists():
            sys.exit("✗ 缺 script_json 且 story/characters.json 不存在")
        characters = json.loads(char_file.read_text())
        style = "manga style, detailed linework, ink shading, cinematic, 8k"

    for char in characters:
        if args.char and char["id"] != args.char:
            continue
        build_char_refs(char, style, only=args.only)
    print("✓ 角色参考库完成")


if __name__ == "__main__":
    main()
