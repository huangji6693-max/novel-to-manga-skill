#!/usr/bin/env python3
"""Stage 3 · 一致性闸门（InsightFace arcface + CLIP ViT-L/14）

评分:
  face_sim  = arcface 余弦（与角色参考脸）    阈值 0.70
  style_adj = CLIP 余弦（与前一 panel）        阈值 0.65
  style_global = CLIP 余弦（与本章节首格）    阈值 0.55

输出:
  $MANGA_ROOT/output/panels_passed/<panel_id>.png   # 软链通过的
  $MANGA_ROOT/output/gate_report.json               # 打分明细

用法:
  python scripts/03_coherence_check.py --chapter chapter_01
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

try:
    from scripts._common import ROOT
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts._common import ROOT


THRESH_FACE = float(os.environ.get("THRESH_FACE", 0.70))
THRESH_STYLE_ADJ = float(os.environ.get("THRESH_STYLE_ADJ", 0.65))
THRESH_STYLE_GLOBAL = float(os.environ.get("THRESH_STYLE_GLOBAL", 0.55))


_face_app = None
_clip_model = None
_clip_proc = None
_device = "cuda"


def get_face_app():
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis
        _face_app = FaceAnalysis(
            name="antelopev2",
            root=str(ROOT / "models" / "insightface"),
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


def get_clip():
    global _clip_model, _clip_proc, _device
    if _clip_model is None:
        import torch
        from transformers import CLIPModel, CLIPProcessor
        _device = "cuda" if torch.cuda.is_available() else "cpu"
        _clip_model = CLIPModel.from_pretrained("openai/clip-vit-large-patch14").to(_device).eval()
        _clip_proc = CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14")
    return _clip_model, _clip_proc


def face_embed(img_path: Path) -> np.ndarray | None:
    app = get_face_app()
    img = np.array(Image.open(img_path).convert("RGB"))
    faces = app.get(img)
    if not faces:
        return None
    faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
               reverse=True)
    return faces[0].normed_embedding


def clip_embed(img_path: Path) -> np.ndarray:
    import torch
    model, proc = get_clip()
    img = Image.open(img_path).convert("RGB")
    with torch.no_grad():
        inputs = proc(images=img, return_tensors="pt").to(_device)
        emb = model.get_image_features(**inputs)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb.cpu().numpy()[0]


def cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def check_panel(panel_id: str, img_path: Path, ref_face_emb: np.ndarray | None,
                prev_img: Path | None, first_img: Path | None,
                char_count: int) -> dict:
    report = {
        "panel_id": panel_id,
        "pass": True,
        "face_sim": None,
        "style_adj": None,
        "style_global": None,
        "reasons": [],
    }

    # 1. Face identity
    if ref_face_emb is not None and char_count >= 1:
        cur = face_embed(img_path)
        if cur is None:
            # No face detected (might be wide shot / back view)
            report["face_sim"] = None
            report["reasons"].append("no_face_detected (acceptable for wide/back shot)")
        else:
            sim = cos(ref_face_emb, cur)
            report["face_sim"] = round(sim, 4)
            if sim < THRESH_FACE:
                report["pass"] = False
                report["reasons"].append(f"face_sim {sim:.3f} < {THRESH_FACE}")

    # 2. Adjacent style continuity
    if prev_img and prev_img.exists():
        s = cos(clip_embed(img_path), clip_embed(prev_img))
        report["style_adj"] = round(s, 4)
        if s < THRESH_STYLE_ADJ:
            report["pass"] = False
            report["reasons"].append(f"style_adj {s:.3f} < {THRESH_STYLE_ADJ}")

    # 3. Global style drift (against chapter opening panel)
    if first_img and first_img.exists() and first_img != img_path:
        s = cos(clip_embed(img_path), clip_embed(first_img))
        report["style_global"] = round(s, 4)
        if s < THRESH_STYLE_GLOBAL:
            report["pass"] = False
            report["reasons"].append(f"style_global {s:.3f} < {THRESH_STYLE_GLOBAL}")

    return report


def process_chapter(chapter: str) -> dict:
    script_path = ROOT / "script_json" / f"{chapter}.json"
    script = json.loads(script_path.read_text())
    char_map = {c["id"]: c for c in script["characters"]}

    # Precompute face embeddings for each character
    ref_embs = {}
    for cid in char_map:
        face_ref = ROOT / "refs" / cid / "face_ref.png"
        if face_ref.exists():
            emb = face_embed(face_ref)
            if emb is not None:
                ref_embs[cid] = emb
                print(f"✓ 角色 {cid} 人脸 embedding OK")
            else:
                print(f"⚠ 角色 {cid} face_ref.png 无法检测到脸")

    panels_dir = ROOT / "output" / "panels_raw"
    passed_dir = ROOT / "output" / "panels_passed"
    passed_dir.mkdir(parents=True, exist_ok=True)

    # First generated panel for style anchor
    all_panels = [p for page in script["pages"] for p in page["panels"]]
    first_img = panels_dir / f"{all_panels[0]['panel_id']}.png" if all_panels else None

    reports = []
    prev = None
    for panel in all_panels:
        pid = panel["panel_id"]
        img = panels_dir / f"{pid}.png"
        if not img.exists():
            reports.append({"panel_id": pid, "pass": False,
                           "reasons": ["file missing (Stage 2 失败)"]})
            continue

        # Choose the ref face of the primary (first listed) character
        chars = panel.get("chars", [])
        primary = chars[0] if chars else None
        ref_emb = ref_embs.get(primary) if primary else None

        r = check_panel(pid, img, ref_emb, prev, first_img, len(chars))
        reports.append(r)

        if r["pass"]:
            target = passed_dir / f"{pid}.png"
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(img.resolve())

        prev = img if r["pass"] else prev   # 失败的不作为"前一格"，防止漂移传染

    pass_n = sum(1 for r in reports if r["pass"])
    total = len(reports)
    summary = {
        "chapter": chapter,
        "total": total,
        "passed": pass_n,
        "pass_rate": round(pass_n / total, 4) if total else 0.0,
        "thresholds": {
            "face": THRESH_FACE,
            "style_adj": THRESH_STYLE_ADJ,
            "style_global": THRESH_STYLE_GLOBAL,
        },
        "panels": reports,
    }

    out = ROOT / "output" / "gate_report.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter_01")
    args = ap.parse_args()

    s = process_chapter(args.chapter)
    print(f"\n通过率: {s['passed']}/{s['total']} = {s['pass_rate']*100:.1f}%")
    failed = [r for r in s["panels"] if not r["pass"]]
    if failed:
        print(f"失败 {len(failed)} 格:")
        for r in failed[:10]:
            print(f"  ✗ {r['panel_id']}  {r['reasons']}")
        if len(failed) > 10:
            print(f"  ... 另 {len(failed)-10} 个（见 output/gate_report.json）")


if __name__ == "__main__":
    main()
