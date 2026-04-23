#!/usr/bin/env bash
# Novel → Manga · 一键装机脚本
# 目标环境：AutoDL / RunPod / 自建 Ubuntu 22.04 + CUDA 12.1+
# 幂等：重跑不会破坏已有环境
#
# 用法：
#   bash setup.sh                    # 完整装机
#   bash setup.sh --skip-models      # 只装 ComfyUI + 节点，不下模型
#   bash setup.sh --fp8              # 低显存模式（省一半显存）

set -euo pipefail

SKIP_MODELS=0
USE_FP8=0
for arg in "$@"; do
  case "$arg" in
    --skip-models) SKIP_MODELS=1 ;;
    --fp8) USE_FP8=1 ;;
  esac
done

# -------- 0. 环境变量 --------
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"    # 国内镜像，境外删除此行
export HF_HUB_ENABLE_HF_TRANSFER=1
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"

ROOT="${MANGA_ROOT:-/root/manga}"
echo "==> 使用 ROOT=$ROOT"

# -------- 1. 目录骨架 --------
mkdir -p "$ROOT"/{models/{flux,pulid,insightface,controlnet,loras},workflows,scripts,story,script_json,refs,output/{panels_raw,panels_passed,pages},fonts}
cd "$ROOT"

# -------- 2. 基础依赖 --------
echo "==> 安装系统依赖"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl wget unzip build-essential python3-dev python3-pip \
    libgl1-mesa-glx libglib2.0-0 ffmpeg fonts-noto-cjk \
    || echo "⚠ apt 部分包失败（非致命）"
fi

pip install --upgrade pip wheel setuptools

# -------- 3. ComfyUI --------
echo "==> ComfyUI"
if [ ! -d "$ROOT/ComfyUI" ]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$ROOT/ComfyUI"
else
  (cd "$ROOT/ComfyUI" && git pull --ff-only || true)
fi

cd "$ROOT/ComfyUI"
pip install -r requirements.txt
pip install hf_transfer huggingface_hub insightface onnxruntime-gpu facexlib

# -------- 4. 自定义节点 --------
echo "==> ComfyUI 自定义节点"
cd "$ROOT/ComfyUI/custom_nodes"

NODES=(
  "https://github.com/ltdrdata/ComfyUI-Manager"
  "https://github.com/balazik/ComfyUI-PuLID-Flux"
  "https://github.com/cubiq/ComfyUI_essentials"
  "https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet"
  "https://github.com/Fannovel16/comfyui_controlnet_aux"
  "https://github.com/WASasquatch/was-node-suite-comfyui"
  "https://github.com/rgthree/rgthree-comfy"
  "https://github.com/city96/ComfyUI-GGUF"
  "https://github.com/XLabs-AI/x-flux-comfyui"
)

for repo in "${NODES[@]}"; do
  name=$(basename "$repo" .git)
  if [ ! -d "$name" ]; then
    git clone --depth 1 "$repo" "$name" || echo "⚠ 跳过 $name"
  fi
  [ -f "$name/requirements.txt" ] && pip install -r "$name/requirements.txt" || true
done

# -------- 5. 评分 & 排版依赖 --------
echo "==> 评分 + 排版依赖"
pip install \
  torch torchvision --index-url https://download.pytorch.org/whl/cu124 \
  || true   # 已装不覆盖
pip install \
  transformers accelerate Pillow numpy scipy \
  anthropic openai \
  pilmoji fontTools \
  opencv-python-headless

# -------- 6. 模型下载 --------
if [ "$SKIP_MODELS" -eq 0 ]; then
  echo "==> 下载模型（约 120 GB · 45-60 分钟）"

  # 6a. FLUX 基础
  cd "$ROOT/models/flux"
  if [ "$USE_FP8" -eq 1 ]; then
    huggingface-cli download Kijai/flux-fp8 flux1-dev-fp8.safetensors --local-dir .
    huggingface-cli download comfyanonymous/flux_text_encoders t5xxl_fp8_e4m3fn.safetensors clip_l.safetensors --local-dir .
  else
    huggingface-cli download black-forest-labs/FLUX.1-dev flux1-dev.safetensors --local-dir .
    huggingface-cli download comfyanonymous/flux_text_encoders t5xxl_fp16.safetensors clip_l.safetensors --local-dir .
  fi
  huggingface-cli download black-forest-labs/FLUX.1-dev ae.safetensors --local-dir .
  huggingface-cli download black-forest-labs/FLUX.1-Kontext-dev flux1-kontext-dev.safetensors --local-dir . || \
    echo "⚠ Kontext 下载失败（gated repo，需 HF_TOKEN 申请访问）"

  # 6b. PuLID
  cd "$ROOT/models/pulid"
  huggingface-cli download guozinan/PuLID pulid_flux_v0.9.1.safetensors --local-dir .

  # 6c. InsightFace antelopev2
  cd "$ROOT/models/insightface"
  if [ ! -d antelopev2 ]; then
    huggingface-cli download DIAMONIK7777/antelopev2 --local-dir antelopev2 || true
    # 备用：直接 onnx
    if [ ! -f antelopev2/glintr100.onnx ]; then
      mkdir -p antelopev2
      wget -q -O antelopev2.zip "https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip"
      unzip -o antelopev2.zip -d . && rm antelopev2.zip
    fi
  fi

  # 6d. ControlNet for Flux (XLabs)
  cd "$ROOT/models/controlnet"
  huggingface-cli download XLabs-AI/flux-controlnet-collections \
    flux-canny-controlnet-v3.safetensors \
    flux-depth-controlnet-v3.safetensors \
    --local-dir . || echo "⚠ ControlNet 部分失败"

  huggingface-cli download XLabs-AI/flux-controlnet-canny-v3 \
    flux-canny-controlnet-v3.safetensors --local-dir . || true
fi

# -------- 7. 软链到 ComfyUI --------
echo "==> 软链模型到 ComfyUI"
cd "$ROOT/ComfyUI"
mkdir -p models/{unet,vae,clip,pulid,insightface,controlnet,loras}

ln -sfn "$ROOT"/models/flux/*.safetensors models/unet/ 2>/dev/null || true
[ -f "$ROOT/models/flux/ae.safetensors" ] && ln -sfn "$ROOT/models/flux/ae.safetensors" models/vae/ae.safetensors
[ -f "$ROOT/models/flux/clip_l.safetensors" ] && ln -sfn "$ROOT/models/flux/clip_l.safetensors" models/clip/clip_l.safetensors
[ -f "$ROOT/models/flux/t5xxl_fp16.safetensors" ] && ln -sfn "$ROOT/models/flux/t5xxl_fp16.safetensors" models/clip/t5xxl_fp16.safetensors
[ -f "$ROOT/models/flux/t5xxl_fp8_e4m3fn.safetensors" ] && ln -sfn "$ROOT/models/flux/t5xxl_fp8_e4m3fn.safetensors" models/clip/t5xxl_fp8_e4m3fn.safetensors
ln -sfn "$ROOT"/models/pulid/*.safetensors models/pulid/ 2>/dev/null || true
ln -sfn "$ROOT"/models/insightface models/insightface 2>/dev/null || true
ln -sfn "$ROOT"/models/controlnet/*.safetensors models/controlnet/ 2>/dev/null || true

# unet 和 clip 对齐 ComfyUI 新版路径（diffusion_models / text_encoders）
mkdir -p models/{diffusion_models,text_encoders}
ln -sfn "$ROOT"/models/flux/*.safetensors models/diffusion_models/ 2>/dev/null || true
[ -f "$ROOT/models/flux/clip_l.safetensors" ] && ln -sfn "$ROOT/models/flux/clip_l.safetensors" models/text_encoders/clip_l.safetensors
[ -f "$ROOT/models/flux/t5xxl_fp16.safetensors" ] && ln -sfn "$ROOT/models/flux/t5xxl_fp16.safetensors" models/text_encoders/t5xxl_fp16.safetensors

# -------- 8. 字体 --------
echo "==> 字体"
cd "$ROOT/fonts"
if [ ! -f SourceHanSansSC-Bold.otf ]; then
  wget -q -O SourceHanSansSC-Bold.otf \
    "https://github.com/adobe-fonts/source-han-sans/raw/release/OTF/SimplifiedChinese/SourceHanSansSC-Bold.otf" \
    || echo "⚠ 字体下载失败，拼页时请手动放入 $ROOT/fonts/"
fi

# -------- 9. 拷贝本项目脚本 --------
echo "==> 拷贝本项目脚本"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$SKILL_DIR/scripts/"*.py "$ROOT/scripts/" 2>/dev/null || true
cp -r "$SKILL_DIR/workflows/"*.json "$ROOT/workflows/" 2>/dev/null || true
cp -r "$SKILL_DIR/story_template/"* "$ROOT/story/" 2>/dev/null || true

# -------- 10. 启动提示 --------
cat <<EOF

======================================================================
✓ 安装完成

启动 ComfyUI 后台：
    cd $ROOT/ComfyUI && python main.py --listen 0.0.0.0 --port 8188 &

放入输入：
    $ROOT/story/chapter_01.txt           # 小说章节
    $ROOT/story/characters.json          # 角色设定
    $ROOT/refs/<char_id>/face_ref.png    # 每个角色的正脸照片

配置 API Key：
    export ANTHROPIC_API_KEY="sk-ant-..."  # Stage 0 用

跑整条流水线：
    cd $ROOT && python scripts/orchestrate.py

单阶段：
    python scripts/00_script_gen.py      # LLM 分镜
    python scripts/01_build_refs.py      # 角色参考库
    python scripts/02_generate_panels.py # Panel 生成
    python scripts/03_coherence_check.py # 一致性闸门
    python scripts/04_layout_page.py     # 拼页 + 气泡

产物：$ROOT/output/pages/*.png
======================================================================
EOF
