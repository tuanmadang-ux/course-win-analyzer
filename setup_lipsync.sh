#!/usr/bin/env bash
# Tải engine nhép môi về thư mục vendor/.
#
#   bash setup_lipsync.sh latentsync   # nét nhất, cần GPU >= 8GB VRAM
#   bash setup_lipsync.sh sadtalker    # có cử động đầu, nhẹ hơn
#   bash setup_lipsync.sh wav2lip      # nhẹ nhất, chạy được máy yếu
#
# Các repo này KHÔNG kèm trong dự án vì nặng vài GB và có giấy phép riêng.
# Script chỉ clone mã nguồn + tải trọng số về đúng chỗ mà phần mềm mong đợi.

set -euo pipefail

ENGINE="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="${LIPSYNC_HOME:-$ROOT/vendor}"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m!  %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m✗  %s\033[0m\n' "$1" >&2; exit 1; }

if [[ -z "$ENGINE" ]]; then
  cat <<'EOF'
Chọn một engine:

  latentsync   Nét nhất, khớp môi tốt nhất. Cần GPU NVIDIA >= 8GB VRAM.
               Tải về khoảng 5GB.

  sadtalker    Thêm cử động đầu và chớp mắt nên nhìn "sống" hơn, nhưng môi
               khớp kém hơn LatentSync một chút. Cần khoảng 4GB VRAM, tải 2GB.

  wav2lip      Cũ nhất, chỉ nhép môi chứ không cử động đầu. Đổi lại chạy được
               trên máy yếu, thậm chí CPU. Tải khoảng 500MB.

Ví dụ:  bash setup_lipsync.sh latentsync
EOF
  exit 0
fi

command -v git >/dev/null || die "Chưa cài git."
BASE_PY="${LIPSYNC_PYTHON:-python3}"
command -v "$BASE_PY" >/dev/null || die "Không tìm thấy $BASE_PY."

# Mỗi engine một môi trường Python RIÊNG, không đụng vào .venv của phần mềm.
#
# Bắt buộc phải vậy: cả ba repo đều ghim phiên bản đụng thẳng vào thư viện ta
# đang dùng — LatentSync đòi opencv-python==4.9.0.80 (ta cần
# opencv-python-headless>=4.10, hai gói khác nhau cùng cấp module cv2),
# SadTalker đòi numpy==1.23.4, Wav2Lip đòi numpy==1.17.1 và torch==1.1.0.
# Cài chung là hỏng phần dò mặt của phần mềm.
#
# Phần mềm tự tìm venv này khi chạy (xem engine_python trong app/avatar/lipsync.py),
# nên không phải khai báo gì thêm trong .env.
make_venv() {
  local dir="$1"
  if [[ ! -x "$dir/.venv/bin/python" ]]; then
    say "Tạo môi trường Python riêng cho engine"
    "$BASE_PY" -m venv "$dir/.venv" || die "Không tạo được venv ở $dir/.venv"
  fi
  PY="$dir/.venv/bin/python"
  "$PY" -m pip install -q --upgrade pip
  echo "  môi trường riêng: $dir/.venv"
}

mkdir -p "$VENDOR"

# Tải file: ưu tiên curl, không có thì dùng wget.
fetch() {
  local url="$1" dest="$2"
  [[ -f "$dest" ]] && { echo "  đã có: $(basename "$dest")"; return 0; }
  mkdir -p "$(dirname "$dest")"
  echo "  tải: $(basename "$dest")"
  if command -v curl >/dev/null; then
    curl -fL --progress-bar "$url" -o "$dest.part" && mv "$dest.part" "$dest"
  elif command -v wget >/dev/null; then
    wget -q --show-progress "$url" -O "$dest.part" && mv "$dest.part" "$dest"
  else
    die "Cần curl hoặc wget để tải trọng số."
  fi
}

clone() {
  local url="$1" dir="$2"
  if [[ -d "$dir/.git" ]]; then
    echo "  đã clone: $dir"
  else
    git clone --depth 1 "$url" "$dir"
  fi
}

case "$ENGINE" in
  latentsync)
    DIR="$VENDOR/LatentSync"
    say "Clone LatentSync"
    clone https://github.com/bytedance/LatentSync.git "$DIR"

    make_venv "$DIR"
    say "Cài thư viện Python (vào môi trường riêng)"
    "$PY" -m pip install -q -r "$DIR/requirements.txt" || \
      warn "Cài thư viện có lỗi — xem $DIR/requirements.txt và cài tay."

    say "Tải trọng số (~5GB, lâu đấy)"
    fetch "https://huggingface.co/ByteDance/LatentSync-1.5/resolve/main/latentsync_unet.pt" \
          "$DIR/checkpoints/latentsync_unet.pt"
    fetch "https://huggingface.co/ByteDance/LatentSync-1.5/resolve/main/whisper/tiny.pt" \
          "$DIR/checkpoints/whisper/tiny.pt"
    ;;

  sadtalker)
    DIR="$VENDOR/SadTalker"
    say "Clone SadTalker"
    clone https://github.com/OpenTalker/SadTalker.git "$DIR"

    make_venv "$DIR"
    say "Cài thư viện Python (vào môi trường riêng)"
    "$PY" -m pip install -q -r "$DIR/requirements.txt" || \
      warn "Cài thư viện có lỗi — xem $DIR/requirements.txt và cài tay."

    say "Tải trọng số (~2GB)"
    BASE="https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc"
    fetch "$BASE/mapping_00109-model.pth.tar"  "$DIR/checkpoints/mapping_00109-model.pth.tar"
    fetch "$BASE/mapping_00229-model.pth.tar"  "$DIR/checkpoints/mapping_00229-model.pth.tar"
    fetch "$BASE/SadTalker_V0.0.2_256.safetensors" "$DIR/checkpoints/SadTalker_V0.0.2_256.safetensors"
    fetch "$BASE/SadTalker_V0.0.2_512.safetensors" "$DIR/checkpoints/SadTalker_V0.0.2_512.safetensors"

    GFP="https://github.com/xinntao/facexlib/releases/download/v0.1.0"
    fetch "$GFP/alignment_WFLW_4HG.pth" "$DIR/gfpgan/weights/alignment_WFLW_4HG.pth"
    fetch "$GFP/detection_Resnet50_Final.pth" "$DIR/gfpgan/weights/detection_Resnet50_Final.pth"
    fetch "$GFP/parsing_parsenet.pth" "$DIR/gfpgan/weights/parsing_parsenet.pth"
    ;;

  wav2lip)
    DIR="$VENDOR/Wav2Lip"
    say "Clone Wav2Lip"
    clone https://github.com/Rudrabha/Wav2Lip.git "$DIR"

    make_venv "$DIR"
    say "Cài thư viện Python (vào môi trường riêng)"
    "$PY" -m pip install -q -r "$DIR/requirements.txt" || \
      warn "Cài thư viện có lỗi — xem $DIR/requirements.txt và cài tay."

    say "Tải trọng số (~500MB)"
    warn "Trọng số Wav2Lip yêu cầu tải tay do điều khoản của tác giả."
    cat <<EOF

  Vào trang này và tải 2 file:
    https://github.com/Rudrabha/Wav2Lip#getting-the-weights

  Đặt vào đúng chỗ:
    $DIR/checkpoints/wav2lip_gan.pth
    $DIR/face_detection/detection/sfd/s3fd.pth

EOF
    ;;

  *)
    die "Không biết engine '$ENGINE'. Chạy 'bash setup_lipsync.sh' để xem danh sách."
    ;;
esac

say "Kiểm tra"

# Kiểm tra bằng file trên đĩa, không import Python: thư viện nằm trong .venv nên
# `python3` hệ thống sẽ thiếu module trên máy sạch dù cài đã thành công.
case "$ENGINE" in
  latentsync) MARKER="$VENDOR/LatentSync/scripts/inference.py" ;;
  sadtalker)  MARKER="$VENDOR/SadTalker/inference.py" ;;
  wav2lip)    MARKER="$VENDOR/Wav2Lip/inference.py" ;;
esac

if [[ -f "$MARKER" ]]; then
  echo "  ✓ $ENGINE đã sẵn sàng"
  echo
  echo "Xong. Mở lại phần mềm và chọn '$ENGINE' ở mục Cách nhép môi."
  echo "Phần mềm tự tìm môi trường riêng ở $(dirname "$MARKER")/.venv — không cần sửa .env."
  echo "Muốn dùng mặc định luôn: đặt LIPSYNC_ENGINE=$ENGINE trong file .env"
else
  die "Thiếu file: $MARKER — xem lại các bước báo lỗi ở trên."
fi
