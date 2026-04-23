---
name: novel-to-manga
description: Use this skill whenever the user wants to convert a novel, short story, chapter, or any prose text into manga/comic pages with AI. Triggers include "novel to manga", "novel to comic", "小说转漫画", "writing to comic", "chapter to manga", or requests to generate storyboard panels, character reference sheets, panel-by-panel comics, manga pages with consistent characters across panels. This skill orchestrates a 5-stage local GPU pipeline (LLM storyboard → PuLID character refs → FLUX.1-Kontext panel generation → InsightFace+CLIP coherence gate → layout+speech bubbles) to produce publication-quality manga with character identity consistency (arcface ≥ 0.70) and scene continuity (CLIP ≥ 0.60). Requires a rented GPU (A100 40G recommended). Use for: novel adaptation, webtoon prototyping, storyboard generation, graphic novel pipelines.
license: MIT
metadata:
  version: 1.0.0
  category: generative-media
  stack: ComfyUI, FLUX.1-dev, FLUX.1-Kontext, PuLID, InsightFace, CLIP, manga-panel-layout
---

# Novel → Manga Local Pipeline

Convert prose chapters into manga pages on a rented GPU (A100 40G), solving the two hardest problems: **panel-to-panel coherence** and **character identity consistency** across all generated panels.

## When to Use

- User provides a novel / short story / chapter and wants manga pages out
- User asks about storyboarding, paneling, or webtoon generation
- User mentions consistent characters across panels, reference sheets, or FaceID
- User wants a local pipeline (not Midjourney/SaaS)

## When NOT to Use

- Single illustration request (use FLUX directly)
- Already-drawn manga needing only colorization (use different workflow)
- User has no GPU access (recommend SaaS instead)

## 5-Stage Pipeline

```
Stage 0  Novel (.txt)       → scripts/00_script_gen.py     → script.json (per-panel shot/angle/lighting/continuity)
Stage 1  Character photo     → scripts/01_build_refs.py     → refs/{char}/ (four-view + 8 expressions + N outfits)
Stage 2  script + refs       → scripts/02_generate_panels.py → panels_raw/*.png (FLUX-Kontext + PuLID)
Stage 3  panels_raw          → scripts/03_coherence_check.py → panels_passed/ + gate_report.json
Stage 3b retry failed        → scripts/03b_retry.py          → re-roll with adjusted weights
Stage 4  panels_passed       → scripts/04_layout_page.py     → pages/*.png (wrapped, bubbled, 300dpi)
```

## Environment

**GPU**: A100 40G (recommended) · RTX 4090 24G (minimum, fp8) · H100 80G (batch)
**Host**: AutoDL (CN) / RunPod (intl) / local
**Models**: ~120 GB total (see `setup.sh`)

## Quick Start on a Fresh GPU Instance

```bash
# 1. SSH in, clone this skill
git clone https://github.com/huangji6693-max/novel-to-manga-skill.git
cd novel-to-manga-skill

# 2. One-shot setup (60 min: ComfyUI + nodes + 120G of weights)
bash setup.sh

# 3. Launch ComfyUI backend
cd /root/manga/ComfyUI && python main.py --listen 0.0.0.0 --port 8188 &

# 4. Put your novel into story/ and character photos into refs/{char_id}/face_ref.png
# 5. Full pipeline
python scripts/orchestrate.py --story story/chapter_01.txt --characters story/characters.json
```

## Tuning Reference

| Parameter | File | Default | Effect |
|---|---|---|---|
| `pulid_weight` | `02_generate_panels.py` | 0.85 | Face identity strength (0.7 loose → 0.95 strict) |
| `pulid_end` | `02_generate_panels.py` | 0.7 | PuLID stop fraction (0.7 = last 30% free for style) |
| `denoise` | `02_generate_panels.py` | 0.85 | Keep 15% of ref structure |
| `cfg` | `02_generate_panels.py` | 3.0 | FLUX guidance (2.5 loose → 4.0 strict) |
| `THRESH_FACE` | `03_coherence_check.py` | 0.70 | arcface pass threshold |
| `THRESH_STYLE_ADJ` | `03_coherence_check.py` | 0.65 | Adjacent-panel CLIP threshold |
| `seed=hash(panel_id)` | `02_generate_panels.py` | reproducible | Same panel → same seed on retry |

## Cost (one 5k-word chapter, 16 pages, 96 panels)

| Stage | Time | Cost on A100 @ ¥7.8/h |
|---|---|---|
| 0 LLM | 30s (Claude API) | ¥2 |
| 1 Refs (2 chars) | 15 min | ¥1.95 |
| 2 Panels | 55 min | ¥7.15 |
| 3 Gate + retry | 13 min | ¥1.7 |
| 4 Layout | 1 min | ¥0.13 |
| **Total** | **~2 h** | **¥18.8 / chapter** |

Per-page ≈ ¥1.2. Per-panel ≈ ¥0.2.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| OOM on 4090 | FLUX bf16 too big | Use `flux1-dev-fp8.safetensors` + t5xxl fp8 |
| Face drift | PuLID weight too low | Raise to 0.92, extend `end=0.85` |
| Style chaos | `prompt_tail` inconsistent | Enforce same `prompt_tail` across chapter |
| Same pose repeated | seed not panel-hashed | Check `seed=hash(panel_id)` is active |
| Gate pass rate < 60% | Ref image quality bad | Use 1024×1024+ frontal face, good lighting |
| Characters swap faces (multi-char) | Single PuLID can't lock 2 faces | Use Channel B: ControlNet pose + inpaint 2nd face |

## Related Skills

- Prefer `claude-api` skill when calling Claude Opus for Stage 0
- Use `ffmpeg-video` skill if exporting motion comics afterwards
