#!/usr/bin/env python3
"""Stage 3b · 失败 Panel 重试（渐进式加码）

策略：
  尝试 1: 换 seed
  尝试 2: PuLID weight 0.85→0.95, end 0.7→0.85
  尝试 3: 切通道 B（ControlNet pose 强制）
  仍失败: 标记 manual_needed, 不再烧钱

用法:
  python scripts/03b_retry.py --chapter chapter_01
  python scripts/03b_retry.py --chapter chapter_01 --max-attempts 3
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from scripts._common import ROOT, panel_seed
    # Import the per-panel generator from Stage 2
    sys.path.insert(0, str(Path(__file__).parent))
    from importlib import import_module
    gen_mod = import_module("02_generate_panels")
    from importlib import import_module
    check_mod = import_module("03_coherence_check")
except Exception:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts._common import ROOT, panel_seed
    sys.path.insert(0, str(Path(__file__).parent))
    from importlib import import_module
    gen_mod = import_module("02_generate_panels")
    check_mod = import_module("03_coherence_check")


def retry_panel(panel: dict, char_map: dict, style_tail: str,
                attempt: int) -> bool:
    """Re-generate a single panel with escalating parameters."""
    if attempt == 1:
        # New seed only
        original_hash = panel_seed(panel["panel_id"])
        # Temporarily salt the panel_id for a different seed
        panel_salted = dict(panel, panel_id=f"{panel['panel_id']}_retry1")
        try:
            produced = gen_mod.generate_channel_a(panel_salted, char_map, style_tail)
        except Exception as e:
            print(f"    retry1 error: {e}")
            return False
        target = ROOT / "output" / "panels_raw" / f"{panel['panel_id']}.png"
        shutil.copy2(produced, target)
        return True

    if attempt == 2:
        # Boost PuLID influence
        panel_salted = dict(panel, panel_id=f"{panel['panel_id']}_retry2")
        try:
            produced = gen_mod.generate_channel_a(
                panel_salted, char_map, style_tail,
                pulid_weight=0.95, pulid_end=0.85,
            )
        except Exception as e:
            print(f"    retry2 error: {e}")
            return False
        target = ROOT / "output" / "panels_raw" / f"{panel['panel_id']}.png"
        shutil.copy2(produced, target)
        return True

    if attempt == 3:
        # Switch channel (or if unavailable, raise denoise to preserve ref)
        panel_salted = dict(panel, panel_id=f"{panel['panel_id']}_retry3")
        try:
            produced = gen_mod.generate_channel_b(
                panel_salted, char_map, style_tail,
                pulid_weight=0.92, pulid_end=0.8, denoise=0.75,
            )
        except Exception as e:
            print(f"    retry3 error: {e}")
            return False
        target = ROOT / "output" / "panels_raw" / f"{panel['panel_id']}.png"
        shutil.copy2(produced, target)
        return True

    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter_01")
    ap.add_argument("--max-attempts", type=int, default=3)
    args = ap.parse_args()

    report_path = ROOT / "output" / "gate_report.json"
    if not report_path.exists():
        sys.exit("✗ 请先跑 03_coherence_check.py 生成 gate_report.json")

    report = json.loads(report_path.read_text())
    script = json.loads((ROOT / "script_json" / f"{args.chapter}.json").read_text())
    char_map = {c["id"]: c for c in script["characters"]}
    panel_map = {p["panel_id"]: p for page in script["pages"] for p in page["panels"]}
    style_tail = script.get("style_tail", "")

    failed_panels = [r for r in report["panels"] if not r["pass"]]
    print(f"==> 重试 {len(failed_panels)} 个失败 panel · 最多 {args.max_attempts} 轮")

    manual_needed = []
    for fail in failed_panels:
        pid = fail["panel_id"]
        panel = panel_map.get(pid)
        if not panel:
            print(f"  ⚠ {pid} 在脚本中找不到")
            continue

        print(f"\n  [{pid}] 原因: {fail['reasons']}")
        recovered = False
        for attempt in range(1, args.max_attempts + 1):
            print(f"    尝试 {attempt}/{args.max_attempts}...")
            ok = retry_panel(panel, char_map, style_tail, attempt)
            if not ok:
                continue
            # Re-score this panel only
            img = ROOT / "output" / "panels_raw" / f"{pid}.png"
            chars = panel.get("chars", [])
            primary = chars[0] if chars else None
            ref_emb = None
            if primary:
                face_ref = ROOT / "refs" / primary / "face_ref.png"
                if face_ref.exists():
                    ref_emb = check_mod.face_embed(face_ref)

            # Find prev/first for context
            all_panels = [p for page in script["pages"] for p in page["panels"]]
            first_img = ROOT / "output" / "panels_raw" / f"{all_panels[0]['panel_id']}.png"
            idx = next((i for i, p in enumerate(all_panels) if p["panel_id"] == pid), 0)
            prev_img = None
            if idx > 0:
                prev_img = ROOT / "output" / "panels_raw" / f"{all_panels[idx-1]['panel_id']}.png"

            r = check_mod.check_panel(pid, img, ref_emb, prev_img, first_img, len(chars))
            print(f"      face={r['face_sim']} style_adj={r['style_adj']} pass={r['pass']}")
            if r["pass"]:
                target = ROOT / "output" / "panels_passed" / f"{pid}.png"
                if target.exists() or target.is_symlink():
                    target.unlink()
                target.symlink_to(img.resolve())
                recovered = True
                print(f"    ✓ {pid} 恢复于第 {attempt} 轮")
                break

        if not recovered:
            manual_needed.append(pid)
            print(f"    ✗ {pid} 3 轮失败 · 需人工介入")

    out = ROOT / "output" / "retry_report.json"
    out.write_text(json.dumps({
        "recovered": [r["panel_id"] for r in failed_panels
                      if r["panel_id"] not in manual_needed],
        "manual_needed": manual_needed,
    }, ensure_ascii=False, indent=2))

    print(f"\n✓ 重试完成")
    print(f"  恢复: {len(failed_panels) - len(manual_needed)}")
    print(f"  人工介入: {len(manual_needed)}")
    if manual_needed:
        print(f"  需处理: {manual_needed}")


if __name__ == "__main__":
    main()
