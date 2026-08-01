#!/usr/bin/env bash
# Cài đặt faceless-shorts: kiểm tra công cụ, cài thư viện, sinh registry Remotion.
#   bash setup.sh          # cài phần lõi (TSX + generative track)
#   bash setup.sh --vox    # cài thêm pillow/rembg/playwright cho track collage
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$PWD"
WITH_VOX=0
[[ "${1:-}" == "--vox" ]] && WITH_VOX=1

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m[!] %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 1. công cụ
say "Kiểm tra công cụ bắt buộc"
MISSING=()
for cmd in node npm python3 ffmpeg ffprobe; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '  ok   %-8s %s\n' "$cmd" "$(command -v "$cmd")"
  else
    printf '  MISS %-8s\n' "$cmd"; MISSING+=("$cmd")
  fi
done
if ((${#MISSING[@]})); then
  warn "Thiếu: ${MISSING[*]}"
  echo "     Ubuntu/Debian : sudo apt-get update && sudo apt-get install -y ffmpeg nodejs npm python3"
  echo "     macOS         : brew install ffmpeg node python"
  exit 1
fi

NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
(( NODE_MAJOR >= 18 )) || { warn "Cần Node 18+, đang có $(node -v)"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || { warn "Cần Python 3.10+, đang có $(python3 -V)"; exit 1; }

# ---------------------------------------------------------------- 2. .env
say "Chuẩn bị .env"
if [[ -f .env ]]; then
  echo "  .env đã có — giữ nguyên."
else
  cp .env.example .env
  echo "  Đã tạo .env từ .env.example — nhớ điền API key."
fi

# ---------------------------------------------------------------- 3. node deps
say "Cài thư viện Remotion (npm install)"
( cd remotion && npm install --no-fund --no-audit )

say "Sinh registry Remotion (npm run gen)"
( cd remotion && npm run gen )

# ---------------------------------------------------------------- 4. browser
# Remotion tự tải Chrome Headless Shell từ remotion.media. Máy nào chặn egress
# (sandbox, CI, mạng nội bộ) thì trỏ REMOTION_BROWSER_EXECUTABLE vào Chrome sẵn có.
say "Kiểm tra trình duyệt để render"
FOUND_BROWSER=""
for p in \
  "${REMOTION_BROWSER_EXECUTABLE:-}" \
  /opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell \
  /opt/pw-browsers/chromium-*/chrome-linux/chrome \
  /usr/bin/chromium /usr/bin/chromium-browser /usr/bin/google-chrome \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
do
  [[ -n "$p" && -x "$p" ]] && { FOUND_BROWSER="$p"; break; }
done

if [[ -n "$FOUND_BROWSER" ]]; then
  echo "  Tìm thấy: $FOUND_BROWSER"
  echo "  Nếu máy bạn chặn mạng ra ngoài, export biến này trước khi render:"
  echo "      export REMOTION_BROWSER_EXECUTABLE=\"$FOUND_BROWSER\""
else
  echo "  Không thấy Chrome cài sẵn — Remotion sẽ tự tải khi render lần đầu (~150MB)."
fi

# ---------------------------------------------------------------- 5. vox deps
if (( WITH_VOX )); then
  say "Cài thư viện cho track collage (vox)"
  pip install pillow "rembg[cpu]" playwright
  playwright install chromium
else
  echo
  echo "  (Bỏ qua deps track vox. Cần thì chạy: bash setup.sh --vox)"
fi

# ---------------------------------------------------------------- xong
say "Xong"
cat <<EOF
Kiểm tra nhanh — render 3 khung hình QA:
    cd "$ROOT/remotion"
    node scripts/frames.mjs Short2Math 0,300,700 --scale=0.5
    # -> remotion/out/qa/*.png

Xem toàn bộ composition bằng giao diện:
    cd "$ROOT/remotion" && npm run studio

Làm video mới: mở Claude Code tại "$ROOT" rồi nói
    "make a short about <chủ đề>"

Đọc thêm: HUONG-DAN.md
EOF
