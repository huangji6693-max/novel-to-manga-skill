# Novel → Manga 集成指南（给 Claude Code / 龙虾读）

本文件告诉 Claude Code 何时触发本 skill、如何搭配工具、以及质量要求。

---

## 触发表

| 用户说 | 触发 skill |
|---|---|
| 把这本小说转成漫画 | novel-to-manga |
| novel to manga / novel to comic | novel-to-manga |
| 小说转漫画 / 章节转漫画 / 改编成漫画 | novel-to-manga |
| 要生成分镜 / storyboard | novel-to-manga（Stage 0 可单独跑） |
| 我要做 webtoon / 条漫 | novel-to-manga（layout 换 `4-panel-webtoon`） |
| 角色不一致 / 脸不稳 | novel-to-manga（跳 Stage 1 + Stage 3 调参） |

### 不触发

- 单张插画 → 直接 FLUX prompt
- 现有漫画上色 → 其他 workflow
- 动图 / 动画 → 其他 workflow（但可用本 skill 先出关键帧）

---

## 工作流编排

### 场景 1 · 用户第一次跑（完整章节）

1. 读 `story/chapter_XX.txt` + `story/characters.json`
2. 跑 `scripts/orchestrate.py`（串起 Stage 0-4）
3. 每阶段完成后向用户汇报进度 + 通过率
4. Stage 3 失败 > 3 次的 panel 人工告诉用户：`要不要手动调 ComfyUI 参数`

### 场景 2 · 用户只想先验证（MVP）

1. 跳过 Stage 0，手写最小 JSON（1 页 4 格 1 角色）
2. 跑 Stage 1 → Stage 2 → Stage 3
3. 汇报通过率 + FaceID 均值
4. 让用户决定是否进入大章节

### 场景 3 · 用户只要分镜脚本

1. 只跑 `scripts/00_script_gen.py`
2. 产出 JSON 给用户 review
3. 用户改完 JSON 再跑后面

---

## 质量规则

### 必须

- [ ] 每 panel 有 `continuity` 字段，不能空
- [ ] 整章同一 `prompt_tail`（风格统一）
- [ ] `seed = hash(panel_id)` 保证可复现
- [ ] Stage 3 通过率 < 70% → 停下来报告，不要继续烧钱
- [ ] `output/` 每次新章节用子目录，不覆盖旧的

### 严禁

- 不要伪造 FaceID 分数 — 真实打分，低就是低
- 不要静默跳过失败 panel — 必须汇总 `gate_report.json`
- 不要把 HF 镜像站写死 — 环境变量 `HF_ENDPOINT` 可配
- 不要默认用 fp8 模型除非用户指定（bf16 质量更稳）
- 不要并发跑 > 4 个 panel（A100 显存刚好 40G）

---

## 文件操作安全

### 破坏性操作需确认

- 删除 `output/panels_raw/` 前问用户
- 覆盖 `script_json/*.json` 前 diff 给用户
- 重下载模型前检查 `models/` 是否已存在（setup.sh 幂等）

### 输出位置

- 所有产物在 `/root/manga/output/<chapter_id>/`
- 不要写到用户家目录或共享目录
- 最终 PNG 可通过 `python -m http.server 18080 -d /root/manga/output` 下载

### 密钥管理

- Claude API key 走环境变量 `ANTHROPIC_API_KEY`
- HF token 走 `HF_TOKEN`（`setup.sh` 里会检测）
- 永远不把 key 写进 JSON 或代码

---

## 集成其他 skill

| 搭配 | 用途 |
|---|---|
| `claude-api` | Stage 0 调 Claude Opus 4.7 · 分镜质量最高 |
| `ffmpeg-video` | 成品漫画导出 motion comic（panel 摇镜头） |
| `docx-pro` | 把对白整理成剧本 docx 交付 |
| `pdf-pro` | 整章多页合并成 PDF 交付 |

---

## 任务跟踪

对超过 30 分钟的任务（即 Stage 2 批量生成），用 TaskCreate 跟踪：

```
Task 1: Stage 0 LLM 分镜          [done]
Task 2: Stage 1 角色参考库          [done]
Task 3: Stage 2 Panel 生成 (96 格)  [in_progress 45/96]
Task 4: Stage 3 闸门                 [pending]
Task 5: Stage 4 拼页                 [pending]
```

每完成一格更新一次太啰嗦，每页完成（6-8 格）更新一次。

---

## 故障汇总

见 README.md `Troubleshooting` 表。出现任何 3 次重试仍失败 → 停下报告，不要继续。

---

## 版本

- v1.0.0 · 2026-04-23 · 初版（5 阶段 pipeline）

---

## 帮助

- Skill 源码：https://github.com/huangji6693-max/novel-to-manga-skill
- 主 README：本仓库 `README.md`
- 单阶段调试：`python scripts/0X_xxx.py --help`
