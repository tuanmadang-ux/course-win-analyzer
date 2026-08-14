#!/usr/bin/env bash
# Cài engine dựng thẻ đồ hoạ B-roll.
#
#   bash setup_motion.sh hyperframes   # Apache 2.0 — khuyên dùng
#   bash setup_motion.sh remotion      # xem kỹ phần giấy phép bên dưới
#   bash setup_motion.sh both
#
# Cả hai đều là công cụ Node dựng HTML/React thành video, chạy bằng Chrome không
# giao diện. Chúng KHÔNG thay thế B-roll stock — chúng làm loại B-roll khác: thẻ
# đồ hoạ mang đúng nội dung đang được nói.

set -euo pipefail

WHAT="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m!  %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m✗  %s\033[0m\n' "$1" >&2; exit 1; }

if [[ -z "$WHAT" ]]; then
  cat <<'EOF'
Chọn engine dựng thẻ đồ hoạ:

  hyperframes   Của HeyGen. Thẻ viết bằng HTML thường.
                Giấy phép Apache 2.0 — MIỄN PHÍ cho mọi quy mô, kể cả công ty lớn,
                kể cả dùng thương mại. Tải về ~150MB.
                >>> Khuyên dùng cái này.

  remotion      Thẻ viết bằng React. Hệ sinh thái lớn hơn, nhiều hiệu ứng sẵn hơn.
                ⚠ GIẤY PHÉP: miễn phí cho cá nhân và công ty CÓ TỐI ĐA 3 NGƯỜI.
                  Công ty từ 4 người trở lên PHẢI mua license ở remotion.pro.
                  Tải về ~400MB.

  both          Cài cả hai để so sánh.

Cả hai cần Node.js 22 trở lên.
EOF
  exit 0
fi

command -v node >/dev/null || die "Chưa cài Node.js. Tải ở https://nodejs.org (bản 22 trở lên)."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" -ge 22 ]] || die "Cần Node.js 22 trở lên, máy đang có $(node --version)."
command -v ffmpeg >/dev/null || warn "Chưa thấy ffmpeg — cả hai engine đều cần nó để xuất video."

install_hyperframes() {
  say "Cài HyperFrames (Apache 2.0)"
  (cd "$ROOT/app/motion/project" && npm install --no-audit --no-fund)

  # HyperFrames gửi số liệu dùng ẩn danh. Video của bạn là việc của bạn, nên tắt.
  (cd "$ROOT/app/motion/project" && npx --yes hyperframes telemetry disable >/dev/null 2>&1) || true

  if [[ -f "$ROOT/app/motion/project/node_modules/gsap/dist/gsap.min.js" ]]; then
    echo "  ✓ HyperFrames sẵn sàng"
  else
    die "Cài HyperFrames chưa xong — thiếu gsap."
  fi
}

install_remotion() {
  say "Cài Remotion"
  cat <<'EOF'
  ⚠ NHẮC LẠI VỀ GIẤY PHÉP
     Remotion miễn phí cho cá nhân và công ty tối đa 3 người.
     Công ty từ 4 người trở lên phải mua Company License tại remotion.pro.
     Chi tiết: https://github.com/remotion-dev/remotion/blob/main/LICENSE.md

EOF
  (cd "$ROOT/app/motion/remotion" && npm install --no-audit --no-fund)

  if [[ -f "$ROOT/app/motion/remotion/node_modules/remotion/package.json" ]]; then
    echo "  ✓ Remotion sẵn sàng"
    echo "    Lần render đầu, Remotion sẽ tự tải Chromium riêng (~150MB)."
    echo "    Máy có proxy chặn tải: đặt REMOTION_BROWSER=/duong/dan/chrome-headless-shell trong .env"
  else
    die "Cài Remotion chưa xong."
  fi
}

case "$WHAT" in
  hyperframes) install_hyperframes ;;
  remotion)    install_remotion ;;
  both)        install_hyperframes; install_remotion ;;
  *)           die "Không biết '$WHAT'. Chạy 'bash setup_motion.sh' để xem danh sách." ;;
esac

say "Kiểm tra"

# Kiểm tra bằng chính file trên đĩa, KHÔNG import Python. Trước đây bước này gọi
# `python3` hệ thống để hỏi app.motion.engine — nhưng thư viện lại nằm trong
# .venv, nên trên máy sạch nó báo lỗi thiếu module dù cài hoàn toàn thành công.
READY=0
if [[ -f "$ROOT/app/motion/project/node_modules/gsap/dist/gsap.min.js" ]]; then
  echo "  ✓ HyperFrames sẵn sàng"; READY=1
fi
if [[ -f "$ROOT/app/motion/remotion/node_modules/remotion/package.json" ]]; then
  echo "  ✓ Remotion sẵn sàng"; READY=1
fi
[[ "$READY" -eq 1 ]] || die "Chưa engine nào sẵn sàng — xem lại lỗi ở trên."

echo
echo "Xong. Mở trang 🎬 Tạo video, bật 'Chèn thẻ đồ hoạ' là dùng được."
echo "Muốn ép dùng một engine cụ thể: đặt MOTION_ENGINE=hyperframes (hoặc remotion) trong .env"
