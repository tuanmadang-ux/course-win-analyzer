"""Test gen_voice.py — toàn bộ đường đi SAU khi ElevenLabs trả kết quả.

Không gọi API thật (tốn tiền, và nhiều môi trường chặn api.elevenlabs.io). Tận dụng
đúng cơ chế cache của chính tool: nó chỉ gọi TTS khi thiếu <raw>.mp3 hoặc
<raw>.words.json —

    if args.force or not exists(raw) or not exists(raw + ".words.json"): tts_line(...)

nên dựng sẵn hai file đó là mọi khâu còn lại chạy thật: đo thời lượng, co giãn
atempo cho vừa cửa sổ, ghép track, loudnorm, ghi timing ngược vào beats.json,
sinh vo.gen.ts, và mux vào video.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GEN_VOICE = ROOT / "tools" / "gen_voice.py"
VOICE_ID = "TX3LPaxmHKxFdv7VOQHJ"
MODEL = "eleven_multilingual_v2"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="cần ffmpeg/ffprobe",
)


def _volume_db(path: Path) -> float:
    """Âm lượng trung bình (dBFS). Im lặng tuyệt đối ~ -91 dB."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "/dev/null"],
        capture_output=True, text=True,
    ).stderr
    for line in out.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0].strip())
    pytest.fail(f"không đọc được âm lượng của {path}")


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


@pytest.fixture(scope="session")
def _mau_co_cache(tmp_path_factory):
    """Dựng audio tổng hợp MỘT lần cho cả phiên — ffmpeg là khâu chậm nhất.

    Các test đều ghi đè beats.json nên không dùng chung thư mục này được; mỗi
    test copy ra bản riêng (copy rẻ hơn sinh lại 11 file audio nhiều lần).
    """
    src = ROOT / "shorts" / "short-2-math"
    dst = tmp_path_factory.mktemp("mau") / "short-2-math"
    shutil.copytree(src, dst)

    beats = json.loads((dst / "beats.json").read_text(encoding="utf-8"))
    vdir = dst / "voice"
    vdir.mkdir(exist_ok=True)

    for i, line in enumerate(beats["vo"]):
        text = line.get("tts", line["text"])
        h = hashlib.sha1(f"{VOICE_ID}|{MODEL}|{text}".encode()).hexdigest()[:8]
        raw = vdir / f"line-{i:02d}-{h}.mp3"
        dur = round(float(line["end"]) - float(line["start"]), 3)

        # Sóng sin nghe được, KHÔNG phải im lặng — để phép đo âm lượng có ý nghĩa.
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"sine=frequency=140:duration={dur}",
             "-filter:a", "volume=0.35", "-ar", "44100", "-ac", "1", str(raw)],
            check=True,
        )

        # Word map giống hệt dạng API trả về: thời gian tính từ đầu clip.
        start = float(line["start"])
        words = [
            {"w": w["w"], "start": round(w["start"] - start, 3), "end": round(w["end"] - start, 3)}
            for w in line.get("words", [])
        ]
        (vdir / f"{raw.name}.words.json").write_text(json.dumps(words), encoding="utf-8")

    return dst


@pytest.fixture
def short_voi_cache(_mau_co_cache, tmp_path):
    """Bản sao riêng cho từng test — gen_voice.py ghi đè beats.json."""
    dst = tmp_path / "short-2-math"
    shutil.copytree(_mau_co_cache, dst)
    return dst


@pytest.fixture(scope="session")
def da_chay(_mau_co_cache, tmp_path_factory):
    """Chạy gen_voice.py MỘT lần, cho mọi test chỉ cần soi kết quả.

    Mỗi lần chạy tốn ~6s (11 lượt atempo + amix + loudnorm), nên gọi lại cho
    từng phép khẳng định là phí. Test nào cần cờ riêng (--mux, --dry-run) thì
    tự chạy bản của nó.
    """
    work = tmp_path_factory.mktemp("dachay") / "short-2-math"
    shutil.copytree(_mau_co_cache, work)
    ts = work.parent / "vo.gen.ts"
    stdout = _run_gen_voice(work / "beats.json", "--emit-ts", str(ts))
    beats = json.loads((work / "beats.json").read_text(encoding="utf-8"))
    return {"dir": work, "ts": ts, "stdout": stdout, "beats": beats}


def _run_gen_voice(beats: Path, *extra: str):
    r = subprocess.run(
        [sys.executable, str(GEN_VOICE), "--beats", str(beats), *extra],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, f"gen_voice.py hỏng:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def test_khong_goi_api_khi_da_co_cache(da_chay):
    """Cốt lõi của library-first: có cache thì không đụng tới mạng."""
    out = da_chay["stdout"]
    assert "Tunnel connection failed" not in out
    assert "TTS failed" not in out
    assert "with-timestamps not available" not in out


def test_track_giong_dung_do_dai_va_nghe_duoc(da_chay):
    wav = da_chay["dir"] / "voice" / "voice.wav"
    assert wav.exists()
    total = float(da_chay["beats"]["format"]["durationSec"])
    assert _duration(wav) == pytest.approx(total, abs=0.15)
    # loudnorm nhắm I=-16; miễn là không phải im lặng (-91 dB).
    assert _volume_db(wav) > -40, "track giọng không được im lặng"


def test_timing_that_duoc_ghi_nguoc_vao_beats(da_chay):
    after = da_chay["beats"]
    assert after["voiceStatus"] == f"elevenlabs:{VOICE_ID}"
    for line in after["vo"]:
        assert line["end"] > line["start"]
        assert line["words"], "mỗi câu phải có word map"
        times = [w["start"] for w in line["words"]]
        assert times == sorted(times), "thời gian các từ phải tăng dần"
        assert line["words"][0]["start"] >= line["start"] - 0.01


def test_cau_khong_chong_len_nhau(da_chay):
    """Khâu ghép track cộng thẳng các clip — chồng nhau là tiếng đè lên tiếng."""
    vo = da_chay["beats"]["vo"]
    for a, b in zip(vo, vo[1:]):
        assert a["end"] <= b["start"] + 0.01, f"câu đè lên nhau: {a['text'][:30]!r}"


def test_sinh_vo_gen_ts_hop_le(da_chay):
    text = da_chay["ts"].read_text(encoding="utf-8")
    assert text.startswith("// AUTO-GENERATED")
    assert "import type { VoLine }" in text
    assert "export const VO: VoLine[] = [" in text
    assert text.count("{ text:") == len(da_chay["beats"]["vo"])
    assert text.rstrip().endswith("];")


def test_dau_nhay_trong_loi_thoai_duoc_escape(da_chay):
    """Câu "Here's the trick…" có dấu nháy đơn — không escape là vỡ cú pháp TS."""
    text = da_chay["ts"].read_text(encoding="utf-8")
    assert "\\'" in text, "dấu nháy đơn phải được escape"


def test_mux_lam_video_cam_thanh_co_tieng(short_voi_cache, tmp_path):
    """Video render ra vốn câm (-91 dB); mux xong phải nghe được."""
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=black:s=320x568:d=42",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(silent)],
        check=True,
    )
    assert _volume_db(silent) < -80, "video mẫu phải đang câm"

    _run_gen_voice(short_voi_cache / "beats.json", "--mux", str(silent))
    voiced = silent.with_name("silent-voiced.mp4")
    assert voiced.exists(), "phải sinh ra bản -voiced.mp4"
    assert _volume_db(voiced) > -40, "bản đã mux phải có tiếng"


def test_dry_run_khong_dong_vao_gi(short_voi_cache):
    beats_path = short_voi_cache / "beats.json"
    before = beats_path.read_text(encoding="utf-8")
    out = _run_gen_voice(beats_path, "--dry-run")
    assert beats_path.read_text(encoding="utf-8") == before, "--dry-run không được sửa beats.json"
    assert not (short_voi_cache / "voice" / "voice.wav").exists()
    assert "line" in out and "window" in out
