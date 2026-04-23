#!/usr/bin/env python3
"""Stage 2 · 批量 Panel 生成（FLUX.1-Kontext + PuLID）

输入:
  $MANGA_ROOT/script_json/<chapter>.json
  $MANGA_ROOT/refs/<char>/outfits/*.png       # Kontext 参考
输出:
  $MANGA_ROOT/output/panels_raw/<panel_id>.png

路由:
  chars==1  → 通道 A (Kontext + PuLID)
  chars>=2  → 通道 B (ControlNet pose + PuLID + inpaint)
  黑白优先  → 通道 C (DiffSensei, 备选)

用法:
  python scripts/02_generate_panels.py --chapter chapter_01
  python scripts/02_generate_panels.py --chapter chapter_01 --only p1-1,p1-2
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from scripts._common import ROOT, load_workflow, queue_workflow, panel_seed
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts._common import ROOT, load_workflow, queue_workflow, panel_seed


# Shot → resolution map (manga panels vary in aspect)
SHOT_SIZES = {
    "establishing": (1536, 1024),        # 3:2 wide landscape
    "wide":         (1536, 1024),
    "medium":       (1024, 1024),
    "close-up":     (1024, 1280),        # tighter portrait
    "extreme-close-up": (1024, 1280),
    "over-shoulder": (1280, 1024),
}


def build_panel_prompt(panel: dict, char_map: dict, style_tail: str) -> str:
    """Compose FLUX prompt from structured panel fields."""
    char_descs = []
    for cid in panel.get("chars", []):
        c = char_map.get(cid, {})
        if c:
            char_descs.append(f"{c['name']} ({c.get('appearance', '')})")

    parts = [
        f"{panel['shot']} shot,",
        f"{panel['angle']},",
        ", ".join(char_descs) + "," if char_descs else "",
        f"{panel['pose']},",
        f"{panel['emotion']} expression,",
        f"background: {panel['background']},",
        f"lighting: {panel['lighting']},",
        style_tail,
    ]
    return " ".join(p for p in parts if p)


def pick_outfit_ref(char: dict, panel: dict) -> Path | None:
    """Pick the outfit reference closest to what this panel describes."""
    char_id = char["id"]
    outfit_dir = ROOT / "refs" / char_id / "outfits"
    if not outfit_dir.exists():
        # Fallback: use the four-view
        fallback = ROOT / "refs" / char_id / "views" / "four_view.png"
        if fallback.exists():
            return fallback
        return ROOT / "refs" / char_id / "face_ref.png"

    # Naive match: search panel.pose + panel.background for outfit keywords
    available = list(outfit_dir.glob("*.png"))
    if not available:
        return ROOT / "refs" / char_id / "face_ref.png"
    haystack = (panel.get("pose", "") + " " + panel.get("background", "")).lower()
    for p in available:
        token = p.stem.replace("_", " ").lower()
        if token[:10] in haystack:
            return p
    return available[0]


def generate_channel_a(panel: dict, char_map: dict, style_tail: str,
                        pulid_weight: float = 0.85, pulid_end: float = 0.7,
                        denoise: float = 0.85, cfg: float = 3.0,
                        steps: int = 30) -> Path:
    """Channel A: single character with Kontext + PuLID."""
    wf = load_workflow("02_panel_kontext.json")

    char_id = panel["chars"][0]
    char = char_map[char_id]
    ref = pick_outfit_ref(char, panel)
    if not ref or not ref.exists():
        raise FileNotFoundError(f"No reference image for {char_id}")

    # Stage reference into ComfyUI/input
    comfy_input = ROOT / "ComfyUI" / "input"
    comfy_input.mkdir(parents=True, exist_ok=True)
    staged = comfy_input / ref.name
    if not staged.exists() or staged.stat().st_mtime < ref.stat().st_mtime:
        shutil.copy2(ref, staged)

    # Also stage face_ref for PuLID (stronger face lock)
    face_ref = ROOT / "refs" / char_id / "face_ref.png"
    if face_ref.exists():
        face_staged = comfy_input / f"{char_id}_face.png"
        if not face_staged.exists():
            shutil.copy2(face_ref, face_staged)

    w, h = SHOT_SIZES.get(panel["shot"], (1024, 1024))
    prompt = build_panel_prompt(panel, char_map, style_tail)

    # Patch workflow nodes
    wf["10"]["inputs"]["image"] = ref.name                   # Kontext reference
    wf["11"]["inputs"]["image"] = f"{char_id}_face.png" if face_ref.exists() else ref.name
    wf["15"]["inputs"]["text"] = prompt
    wf["17"]["inputs"]["width"] = w
    wf["17"]["inputs"]["height"] = h
    wf["18"]["inputs"]["seed"] = panel_seed(panel["panel_id"])
    wf["18"]["inputs"]["steps"] = steps
    wf["18"]["inputs"]["cfg"] = cfg
    wf["18"]["inputs"]["denoise"] = denoise
    wf["20"]["inputs"]["weight"] = pulid_weight
    wf["20"]["inputs"]["end_at"] = pulid_end
    wf["22"]["inputs"]["filename_prefix"] = panel["panel_id"]

    files = queue_workflow(wf, timeout=300)
    produced = ROOT / "ComfyUI" / "output" / files[0]
    return produced


def generate_channel_b(panel: dict, char_map: dict, style_tail: str, **kwargs) -> Path:
    """Channel B: multi-character with ControlNet pose + PuLID primary + inpaint."""
    # Simplified: use channel A workflow but swap to controlnet template if present
    wf_name = "03_panel_controlnet.json"
    wf_path = ROOT / "workflows" / wf_name
    if not wf_path.exists():
        wf_path = Path(__file__).parent.parent / "workflows" / wf_name
    if not wf_path.exists():
        print(f"⚠ {panel['panel_id']} 多角色，但 {wf_name} 不存在，降级到通道 A")
        return generate_channel_a(panel, char_map, style_tail, **kwargs)
    return generate_channel_a(panel, char_map, style_tail, **kwargs)  # TODO proper B


def process_panel(panel: dict, char_map: dict, style_tail: str) -> bool:
    out_path = ROOT / "output" / "panels_raw" / f"{panel['panel_id']}.png"
    if out_path.exists():
        print(f"  {panel['panel_id']} 已存在，跳过")
        return True

    chars = panel.get("chars", [])
    try:
        if len(chars) <= 1:
            produced = generate_channel_a(panel, char_map, style_tail)
        else:
            produced = generate_channel_b(panel, char_map, style_tail)
        shutil.copy2(produced, out_path)
        print(f"  ✓ {panel['panel_id']} → {out_path.name}")
        return True
    except Exception as e:
        print(f"  ✗ {panel['panel_id']} 失败: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter_01")
    ap.add_argument("--only", default=None,
                    help="逗号分隔的 panel_id 列表，只跑这些")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    script_path = ROOT / "script_json" / f"{args.chapter}.json"
    if not script_path.exists():
        sys.exit(f"✗ 分镜脚本不存在: {script_path}")

    script = json.loads(script_path.read_text())
    char_map = {c["id"]: c for c in script["characters"]}
    style_tail = script.get("style_tail", "manga style, detailed linework, 8k")

    only_set = set(args.only.split(",")) if args.only else None

    total = 0
    ok = 0
    for page in script["pages"]:
        print(f"==> Page {page['page_id']}")
        for panel in page["panels"]:
            if only_set and panel["panel_id"] not in only_set:
                continue
            total += 1
            if args.dry_run:
                print(f"  [dry] {panel['panel_id']} · {panel['shot']} · chars={panel['chars']}")
                continue
            if process_panel(panel, char_map, style_tail):
                ok += 1

    print(f"\n✓ Stage 2 完成: {ok}/{total} 成功")


if __name__ == "__main__":
    main()
