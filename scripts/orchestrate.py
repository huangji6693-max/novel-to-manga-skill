#!/usr/bin/env python3
"""Orchestrator · 串起 Stage 0-4 全流程。

用法:
  python scripts/orchestrate.py                            # 全流程 chapter_01
  python scripts/orchestrate.py --chapter chapter_02
  python scripts/orchestrate.py --from 2                   # 从 Stage 2 开始
  python scripts/orchestrate.py --skip 0                   # 跳过 Stage 0（已有 script.json）
  python scripts/orchestrate.py --min-pass-rate 0.70       # 通过率低于此值停止
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from scripts._common import ROOT
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts._common import ROOT


SCRIPT_DIR = Path(__file__).parent

STAGES = [
    ("Stage 0 · LLM 分镜", "00_script_gen.py"),
    ("Stage 1 · 角色参考库", "01_build_refs.py"),
    ("Stage 2 · Panel 批量生成", "02_generate_panels.py"),
    ("Stage 3 · 一致性闸门", "03_coherence_check.py"),
    ("Stage 3b · 失败重试", "03b_retry.py"),
    ("Stage 4 · 拼页 + 气泡", "04_layout_page.py"),
]


def run(script: str, chapter: str, extra: list[str] = None) -> int:
    cmd = [sys.executable, str(SCRIPT_DIR / script), "--chapter", chapter]
    if extra:
        cmd.extend(extra)
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def gate_pass_rate() -> float:
    rp = ROOT / "output" / "gate_report.json"
    if not rp.exists():
        return 0.0
    return json.loads(rp.read_text()).get("pass_rate", 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter_01")
    ap.add_argument("--from", dest="from_stage", type=int, default=0)
    ap.add_argument("--to", dest="to_stage", type=int, default=5)
    ap.add_argument("--skip", type=int, action="append", default=[])
    ap.add_argument("--min-pass-rate", type=float, default=0.70,
                    help="Stage 3 通过率低于此值则停止 (默认 0.70)")
    args = ap.parse_args()

    for idx, (name, script) in enumerate(STAGES):
        if idx < args.from_stage:
            continue
        if idx > args.to_stage:
            break
        if idx in args.skip:
            print(f"⊘ 跳过 {name}")
            continue

        print(f"\n{'='*70}\n{name}\n{'='*70}")
        rc = run(script, args.chapter)
        if rc != 0:
            print(f"\n✗ {name} 失败 (exit {rc})，停止流水线")
            sys.exit(rc)

        # Quality gate: check pass rate after Stage 3
        if idx == 3:
            pr = gate_pass_rate()
            print(f"\n▶ Stage 3 通过率: {pr*100:.1f}%")
            if pr < args.min_pass_rate:
                print(f"  ⚠ 低于阈值 {args.min_pass_rate*100:.0f}% · 触发重试")
                # let Stage 3b handle it
            else:
                print(f"  ✓ 达标，跳过 Stage 3b")
                args.skip.append(4)

        # After Stage 3b, re-check
        if idx == 4:
            # Re-run gate on new panels
            print("  ↳ 重新运行闸门...")
            run("03_coherence_check.py", args.chapter)
            pr = gate_pass_rate()
            print(f"  最终通过率: {pr*100:.1f}%")
            if pr < args.min_pass_rate:
                print(f"  ✗ 仍低于阈值 {args.min_pass_rate*100:.0f}% · 建议人工介入后再跑 Stage 4")
                # don't hard-fail, let user decide

    print(f"\n{'='*70}")
    print("✓ 全流水线完成")
    pages = list((ROOT / "output" / "pages").glob("*.png"))
    print(f"  最终产物: {len(pages)} 页 @ {ROOT / 'output' / 'pages'}")
    print(f"  打分报告: {ROOT / 'output' / 'gate_report.json'}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
