"""Chồng các thẻ đã render lên video nền bằng một lượt ffmpeg duy nhất.

Mỗi thẻ chỉ được render dài `CARD_SECONDS` giây (đủ phần chuyển động vào). Ở đây
mới kéo nó ra cho vừa ô thời gian thật bằng `tpad` (nhân bản khung cuối), mờ dần
lúc kết bằng `fade:alpha=1`, rồi đẩy tới đúng mốc giây.

Hai điểm dễ sai, đều đã xử lý:

* `overlay` đọc hai nguồn theo cùng một đồng hồ. Nếu chỉ dùng `enable=` để bật
  thẻ ở giây thứ 12 thì lúc bật, thẻ đã chạy hết hiệu ứng vào từ đời nào. Phải
  đệm khoảng trong suốt vào ĐẦU thẻ để đẩy nó tới đúng chỗ.
* Làm một lượt cho tất cả thẻ thay vì chồng từng cái: mỗi lượt ffmpeg là một lần
  giải mã + mã hoá lại toàn bộ video, bốn thẻ sẽ thành bốn lần mất chất lượng.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import FFMPEG, RenderSettings
from app.motion.engine import CARD_SECONDS
from app.pipeline.ffmpeg_utils import run
from app.pipeline.render import VENC, run_encode

log = logging.getLogger(__name__)

FADE_IN_GUARD = 0.55   # phần đầu thẻ đang có hiệu ứng vào, đừng làm mờ đè lên
FADE_OUT = 0.45
TRANSPARENT = "#00000000"


def _card_chain(index: int, start: float, hold: float) -> str:
    """Chuỗi filter biến một thẻ thô thành lớp phủ đã đúng độ dài và đúng vị trí."""
    steps = [f"[{index}:v]format=yuva444p"]

    # 1. Kéo dài cho đủ ô thời gian bằng cách nhân bản khung cuối
    pad = hold - CARD_SECONDS
    if pad > 0.01:
        steps.append(f"tpad=stop_mode=clone:stop_duration={pad:.3f}")

    # 2. Cắt đúng độ dài rồi đưa mốc thời gian về 0
    steps.append(f"trim=0:{hold:.3f}")
    steps.append("setpts=PTS-STARTPTS")

    # 3. Mờ dần lúc kết. Chặn dưới để không đè lên hiệu ứng vào của thẻ ngắn.
    fade_at = max(hold - FADE_OUT, FADE_IN_GUARD)
    steps.append(f"fade=t=out:st={fade_at:.3f}:d={FADE_OUT}:alpha=1")

    # 4. Đệm khoảng trong suốt ở đầu để thẻ rơi đúng giây cần
    if start > 0.01:
        steps.append(
            f"tpad=start_duration={start:.3f}:start_mode=add:color={TRANSPARENT}"
        )

    return ",".join(steps) + f"[c{index}]"


def apply(
    base: Path,
    cards: list[dict],
    dest: Path,
    render: RenderSettings,
    base_duration: float,
) -> Path:
    """`cards`: [{clip: Path, start: float, duration: float}].

    Trả về `base` nguyên vẹn nếu không có thẻ nào dùng được — người gọi cứ dùng
    giá trị trả về, không cần tự kiểm tra.
    """
    usable = [
        c for c in cards
        if Path(c["clip"]).is_file()
        and float(c["duration"]) > 0.2
        and float(c["start"]) < base_duration - 0.2
    ]
    if not usable:
        return base

    usable.sort(key=lambda c: float(c["start"]))
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(base)]
    for card in usable:
        cmd += ["-i", str(card["clip"])]

    steps: list[str] = []
    current = "0:v"

    for i, card in enumerate(usable, start=1):
        start = max(float(card["start"]), 0.0)
        hold = min(float(card["duration"]), base_duration - start)

        steps.append(_card_chain(i, start, hold))
        out = f"v{i}"
        steps.append(f"[{current}][c{i}]overlay=0:0:eof_action=pass[{out}]")
        current = out

    cmd += [
        "-filter_complex", ";".join(steps),
        "-map", f"[{current}]",
        "-map", "0:a?",
        VENC,
        "-c:a", "copy",
        "-t", f"{base_duration:.3f}",
        "-movflags", "+faststart",
        str(dest),
    ]

    log.info("Chồng %d thẻ đồ hoạ lên video.", len(usable))
    run_encode(cmd, render)
    return dest


def contact_sheet(clips: list[Path], dest: Path, at: float = 2.0) -> Path | None:
    """Ghép ảnh xem trước các thẻ để hiện trong giao diện."""
    clips = [c for c in clips if Path(c).is_file()][:4]
    if not clips:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    for clip in clips:
        inputs += ["-ss", f"{at:.2f}", "-i", str(clip)]

    count = len(clips)
    # Thẻ có nền trong suốt, phải lót nền tối thì ảnh xem trước mới nhìn được
    chain = "".join(
        f"[{i}:v]scale=270:-1,format=yuva444p,"
        f"drawbox=t=fill:color=0x161b23@1:replace=0[s{i}];"
        for i in range(count)
    )
    chain += "".join(f"[s{i}]" for i in range(count)) + f"hstack=inputs={count}"

    try:
        run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs,
             "-filter_complex", chain, "-frames:v", "1", str(dest)])
        return dest
    except Exception:  # noqa: BLE001
        return None
