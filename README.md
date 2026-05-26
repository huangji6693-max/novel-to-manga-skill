# Novel → Manga 本地工作流

> 把小说章节转成漫画页的**本地可跑**全流程 skill。租张 A100 40G，一键装机 60 分钟，后面全自动。

解决业界最难的两个痛点：
1. **分镜衔接** — 相邻画格的光线/服装/场景不突变
2. **角色一致性** — 同一人在 96 格里脸不变（arcface ≥ 0.70）

---

## 适用场景

- 小说改编成漫画 / webtoon 原型验证
- 长文本结构化拆分镜头 + 批量生图
- 需要角色 ID 稳定的系列插画
- 自动化稿件（条漫/四格/双跨页均可）

**不适合**：单张插画（直接用 FLUX 即可）· 无 GPU 访问（建议用 Midjourney 替代）

---

## 5 阶段流水线

```
Stage 0 · LLM 分镜脚本（Claude / Qwen）
           ↓ 每格给出：shot / angle / chars / pose / emotion / background / lighting / continuity / dialog / prompt_tail
Stage 1 · 角色参考库（FLUX.1-dev + PuLID）
           ↓ 一张脸照 → 四视图 + 8 表情 + N 套服装（共 16-24 张/角色）
Stage 2 · 批量 Panel 生成（FLUX.1-Kontext + PuLID）
           ↓ 通道 A 单人 · 通道 B 多人+ControlNet · 通道 C DiffSensei
Stage 3 · 一致性闸门（InsightFace + CLIP）
           ↓ arcface ≥ 0.70 · 相邻 CLIP ≥ 0.65 · 失败 3 次重试
Stage 4 · 拼页 + 对话气泡（PIL + manga-panel-layout）
           ↓ 2480×3508 @ 300dpi
成品 PNG
```

---

## 硬件选型

| 等级 | 显卡 | VRAM | 能跑 | 价格（2026-04） | 适合 |
|---|---|---|---|---|---|
| 低 | RTX 4090 | 24G | FLUX fp8 + PuLID | AutoDL ¥2.2/h | MVP 验证 |
| **中 ⭐** | **A100 40G** | **40G** | **FLUX bf16 + Kontext + 多 ControlNet** | **¥7.8/h** | **主力** |
| 高 | H100 80G | 80G | 并行 4 路 + 72B LLM | ¥19/h | 批量生产 |

**推荐 AutoDL + A100 40G**（国内带宽、HF 镜像预装）。

---

## 一键上手

```bash
# 1. 租 A100 实例，SSH 进去
ssh root@<autodl-host>

# 2. 克隆本仓库
git clone https://github.com/huangji6693-max/novel-to-manga-skill.git
cd novel-to-manga-skill

# 3. 一键装机（ComfyUI + 节点 + 120G 模型 · 约 60 分钟）
bash setup.sh

# 4. 启动 ComfyUI 后台
cd /root/manga/ComfyUI && python main.py --listen 0.0.0.0 --port 8188 &

# 5. 放入你的小说和角色正脸照
cp your_chapter.txt /root/manga/story/chapter_01.txt
cp your_character.png /root/manga/refs/lin_shu/face_ref.png
cp characters.json /root/manga/story/characters.json

# 6. 全流程跑
python scripts/orchestrate.py
```

---

## 目录结构

```
/root/manga/
├── models/                     # 120G+ 模型
│   ├── flux/                   # flux1-dev.safetensors (23G) + Kontext (23G) + VAE + CLIP + T5
│   ├── pulid/                  # pulid_flux_v0.9.1 (1.1G)
│   ├── insightface/antelopev2/ # 人脸 embedding
│   ├── controlnet/             # canny / depth / openpose
│   └── loras/
├── ComfyUI/                    # 主引擎
├── workflows/                  # 节点图 JSON
├── scripts/                    # 本项目脚本
├── story/                      # 输入小说 + characters.json
├── script_json/                # LLM 产出分镜
├── refs/<char_id>/             # 角色参考库
└── output/
    ├── panels_raw/             # 原始生成
    ├── panels_passed/          # 过闸门
    └── pages/                  # 最终成品
```

---

## 调参速查

### 角色识别漂移
- `pulid_weight` 0.85 → 0.92（脸不像时）
- `pulid_end` 0.7 → 0.85（让 PuLID 作用更久）

### 风格不连续
- 整章强制同一 `prompt_tail`（在 characters.json 里设）
- `cfg` 3.0 → 3.5（更听 prompt）

### 多人场景脸混乱
- 切换到**通道 B**：ControlNet openpose + PuLID 主角 + inpaint 次要角色
- 或者拆成两格：特写单人 → 特写单人 → 再合成

### OOM
- 把 `t5xxl_fp16` 换成 `t5xxl_fp8_e4m3fn`（省 5G）
- FLUX 主体换 `flux1-dev-fp8`
- ComfyUI 启动加 `--lowvram`

---

## 成本参考（单章 5000 字 / 16 页 / 96 panels）

| 环节 | 时长 | A100 @ ¥7.8/h |
|---|---|---|
| 装机（一次性） | 45 min | ¥5.9 |
| Stage 0 LLM | 30s | ¥2（Claude API） |
| Stage 1 角色库（2 角色） | 15 min | ¥1.95 |
| Stage 2 Panel 生成 | 55 min | ¥7.15 |
| Stage 3 闸门 + 重试 | 13 min | ¥1.7 |
| Stage 4 拼页 | 1 min | ¥0.13 |
| **合计** | **~2 h** | **¥18.8 / 章** |

单页 ¥1.2 · 单 panel ¥0.2。

---

## 安装到 Claude Code（龙虾）

```bash
# 安装脚本把 SKILL.md 放到 ~/.claude/skills/
bash install.sh

# 之后在 Claude Code 里直接说：
# "把这本小说转成漫画" / "novel to manga" / "小说转漫画"
# 会自动触发本 skill
```

---

## 核心技术栈

| 组件 | 版本 | 作用 |
|---|---|---|
| ComfyUI | latest | 主引擎 |
| FLUX.1-dev | black-forest-labs | 基础生成模型 |
| FLUX.1-Kontext-dev | black-forest-labs | 多图参考 + 文本控制 |
| PuLID for FLUX | v0.9.1 | 角色 FaceID 注入 |
| InsightFace antelopev2 | latest | 人脸 embedding / 打分 |
| CLIP ViT-L/14 | OpenAI | 风格相似度 |
| ControlNet (Flux) | XLabs | pose / canny / depth 约束 |
| DiffSensei | CVPR 2025 | 专业漫画模型（备选通道） |
| Claude Opus 4.7 | Anthropic | LLM 分镜脚本生成 |

---

## Troubleshooting

| 症状 | 原因 | 解法 |
|---|---|---|
| OOM | FLUX bf16 过大 | 换 fp8 权重，加 `--lowvram` |
| 脸漂 | PuLID 权重过低 | `weight=0.92`, `end=0.85` |
| 风格乱跳 | prompt_tail 每格不同 | 强制整章统一 |
| 同姿势重复 | seed 没 panel 哈希 | 检查 `seed=hash(panel_id)` |
| 通过率 <60% | 参考图脸太糊 | 换 1024×1024 以上正脸 |
| 多人脸互换 | 单 PuLID 只锁一张脸 | 用通道 B (ControlNet + inpaint) |

---

## License

MIT · 见 [LICENSE](LICENSE)

本项目使用的模型有各自 license：
- FLUX.1-dev / Kontext-dev: [non-commercial](https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md)（非商用）
- PuLID: Apache 2.0
- InsightFace: MIT
- CLIP: MIT

**商用需购买 FLUX.1-dev commercial license**。

---

## 致谢

- ComfyUI / comfyanonymous
- FLUX / Black Forest Labs
- PuLID / guozinan
- DiffSensei / jianzongwu
- InsightFace / deepinsight
- XLabs-AI ControlNet collection

欢迎 issue / PR。


---

## 相关项目

- **[claude-code-dna](https://github.com/huangji6693-max/claude-code-dna)** —— Claude Code 的行为操作系统。Karpathy 4 律 + 15 条操作直觉 + 记忆架构 + 194 skill + 99 agent 精选目录。drop-in 到 `~/.claude/`。
