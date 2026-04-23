#!/usr/bin/env bash
# 把 novel-to-manga skill 安装到 Claude Code (龙虾)
#
# 用法:
#   bash install.sh                       # 默认安装到 ~/.claude/skills/
#   CLAUDE_SKILLS_DIR=/custom bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

echo "==> 安装 novel-to-manga skill 到 $TARGET"
mkdir -p "$TARGET/novel-to-manga"

# 复制 SKILL.md（必须）
cp "$SCRIPT_DIR/SKILL.md" "$TARGET/novel-to-manga/"

# 复制辅助资源（可选但推荐）
for dir in scripts workflows story_template examples; do
  if [ -d "$SCRIPT_DIR/$dir" ]; then
    cp -r "$SCRIPT_DIR/$dir" "$TARGET/novel-to-manga/"
  fi
done

for f in README.md CLAUDE.md LICENSE setup.sh requirements.txt; do
  [ -f "$SCRIPT_DIR/$f" ] && cp "$SCRIPT_DIR/$f" "$TARGET/novel-to-manga/"
done

echo "✓ 安装完成"
echo
echo "下一步（在一台带 GPU 的机器上跑）:"
echo "  1. SSH 到 GPU 实例（AutoDL A100 40G 推荐）"
echo "  2. git clone <this-repo>"
echo "  3. cd novel-to-manga-skill && bash setup.sh"
echo "  4. 启动 ComfyUI: cd /root/manga/ComfyUI && python main.py --listen 0.0.0.0 &"
echo "  5. python scripts/orchestrate.py"
echo
echo "在 Claude Code 里只需说: \"把这本小说转成漫画\" 即触发本 skill"
