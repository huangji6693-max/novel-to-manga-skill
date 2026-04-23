#!/usr/bin/env python3
"""Stage 0 · LLM 分镜脚本生成

输入:
  $MANGA_ROOT/story/chapter_XX.txt
  $MANGA_ROOT/story/characters.json
输出:
  $MANGA_ROOT/script_json/chapter_XX.json

用法:
  export ANTHROPIC_API_KEY=sk-ant-xxx
  python scripts/00_script_gen.py --chapter chapter_01
  python scripts/00_script_gen.py --chapter chapter_01 --provider openai  # 备用
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

try:
    from scripts._common import ROOT, ensure_dirs
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts._common import ROOT, ensure_dirs


SYSTEM_PROMPT = """你是专业漫画分镜师。把小说章节拆成双跨页漫画脚本。

硬性规则：
1. 每页 4-8 格 panels · 双跨页按 page_id 奇偶排列
2. 每格必须给出完整字段（缺一视为错误输出）：
   - panel_id: "p{page}-{n}"
   - shot: establishing | wide | medium | close-up | extreme-close-up | over-shoulder
   - angle: eye-level | high-angle | low-angle | dutch | birds-eye | worms-eye
   - chars: [角色ID列表，引用 characters 段]
   - pose: 一句话描述动作姿态
   - emotion: 一个词的情绪
   - background: 场景要素（地点+环境物）
   - lighting: 光源方向 + 色温（必须和相邻格相关）
   - time: 具体时间（2:30 AM / 日出时分）
   - continuity: 与**前一格**的衔接线索（至少一项：相同光源方向 / 相同服装 / 动作连续 / 视线牵引 / 同一场景推拉）
   - dialog: null 或简洁对白（不超 15 字）
   - prompt_tail: 英文艺术风格尾巴（整章必须相同以保证风格一致）
3. 镜头节奏：连续 3 格不得同景别 · 每页至少 1 个特写 · 每页至少 1 个 establishing 或 wide
4. 对白：每格最多 1 条，超 15 字拆格
5. 开页（page_id=1）必须 establishing shot 建立氛围

输出严格 JSON，不加 markdown ```，不加解释，不加注释。
"""

USER_TEMPLATE = """【章节原文】
{story}

【角色设定】
{characters}

【风格提示】整章使用同一 prompt_tail：
"{style}"

【输出 JSON schema】
{{
  "chapter": "第N章 · 标题",
  "style_tail": "上面那个 style 字符串",
  "characters": [从 characters.json 复制并补全 description],
  "pages": [
    {{
      "page_id": 1,
      "layout": "6-panel-standard" | "4-panel-action" | "8-panel-dense" | "splash",
      "panels": [
        {{
          "panel_id": "p1-1",
          "shot": "establishing",
          "angle": "high-angle",
          "chars": ["lin_shu"],
          "pose": "...",
          "emotion": "...",
          "background": "...",
          "lighting": "...",
          "time": "...",
          "continuity": "opening shot",
          "dialog": null,
          "prompt_tail": "同 style_tail"
        }}
      ]
    }}
  ]
}}
"""


def gen_anthropic(story: str, characters: str, style: str, model: str = "claude-opus-4-7") -> dict:
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_TEMPLATE.format(story=story, characters=characters, style=style)
        }],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def gen_openai(story: str, characters: str, style: str, model: str = "gpt-5") -> dict:
    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(story=story, characters=characters, style=style)},
        ],
        response_format={"type": "json_object"},
        max_tokens=16000,
    )
    return json.loads(resp.choices[0].message.content)


def validate(data: dict) -> None:
    """Fail fast on malformed LLM output."""
    required = {"chapter", "style_tail", "characters", "pages"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"LLM output missing top-level keys: {missing}")
    if not data["pages"]:
        raise ValueError("No pages generated")
    panel_fields = {"panel_id", "shot", "angle", "chars", "pose", "emotion",
                    "background", "lighting", "continuity", "prompt_tail"}
    for page in data["pages"]:
        for panel in page["panels"]:
            miss = panel_fields - set(panel.keys())
            if miss:
                raise ValueError(f"Panel {panel.get('panel_id','?')} missing: {miss}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter_01")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--model", default=None)
    ap.add_argument("--style",
                    default="manga style, detailed linework, ink shading, cinematic composition, atmospheric lighting, 8k")
    args = ap.parse_args()

    ensure_dirs()
    story_path = ROOT / "story" / f"{args.chapter}.txt"
    char_path = ROOT / "story" / "characters.json"
    out_path = ROOT / "script_json" / f"{args.chapter}.json"

    if not story_path.exists():
        sys.exit(f"✗ 小说文件不存在: {story_path}")
    if not char_path.exists():
        sys.exit(f"✗ 角色文件不存在: {char_path}")

    story = story_path.read_text()
    characters = char_path.read_text()

    print(f"==> 调用 {args.provider} · {args.model or 'default'} 生成分镜...")
    if args.provider == "anthropic":
        data = gen_anthropic(story, characters, args.style,
                             model=args.model or "claude-opus-4-7")
    else:
        data = gen_openai(story, characters, args.style,
                          model=args.model or "gpt-5")

    validate(data)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    n_panels = sum(len(p["panels"]) for p in data["pages"])
    print(f"✓ 生成 {len(data['pages'])} 页 / {n_panels} 格 → {out_path}")


if __name__ == "__main__":
    main()
