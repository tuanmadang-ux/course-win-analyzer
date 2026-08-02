"""Test khâu chạy tiến trình render: đọc tiến độ, dọn job, chặn trùng, huỷ."""

from __future__ import annotations

import time

import pytest

from webapp.jobs import MAX_FINISHED_JOBS, Job, JobManager, _PROGRESS_RE


def wait_for(manager: JobManager, job_id: str, *, timeout: float = 20.0) -> Job:
    """Đợi job kết thúc, trả về trạng thái cuối."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        assert job is not None
        if job.status in ("done", "error"):
            return job
        time.sleep(0.05)
    pytest.fail(f"job {job_id} không kết thúc trong {timeout}s")


# --------------------------------------------------------------- đọc tiến độ

@pytest.mark.parametrize(
    "line, expect_id, expect_pct",
    [
        ("  Short2Math: 45%   ", "Short2Math", 45),
        # Dòng tiến độ bị cảnh báo bộ nhớ dính vào đuôi — xảy ra thật.
        ("  Short2Math: 0%   Detected differing memory amounts:", "Short2Math", 0),
        ("  Ai1Door: 100%", "Ai1Door", 100),
    ],
)
def test_progress_regex_bat_dung_dong_tien_do(line, expect_id, expect_pct):
    m = _PROGRESS_RE.match(line)
    assert m is not None
    assert m.group(1) == expect_id
    assert int(m.group(2)) == expect_pct


@pytest.mark.parametrize(
    "line",
    [
        "Downloading 50% of chrome",          # Remotion tải trình duyệt
        "Memory reported by Node: 14902.10 MB",
        "  -> out/Short2Math.mp4",
        "bundling...",
        "npm warn deprecated source-map@0.8.0-beta.0",
    ],
)
def test_progress_regex_bo_qua_dong_khong_phai_tien_do(line):
    m = _PROGRESS_RE.match(line)
    # Hoặc không khớp, hoặc khớp nhưng id không phải composition đang render.
    assert m is None or m.group(1) != "Short2Math"


def test_tien_do_chay_tang_dan_va_ket_thuc_o_100(fresh_manager, fake_argv):
    job = fresh_manager.start("video", fake_argv("Short2Math"), shot="Short2Math")
    done = wait_for(fresh_manager, job.id)
    assert done.status == "done"
    assert done.progress == 1.0
    assert done.outputs == ["out/Short2Math.mp4"]


def test_dong_tai_trinh_duyet_khong_lam_tut_tien_do(fresh_manager, fake_argv):
    """Lỗi đã sửa: 'Downloading 50% of chrome' từng bị đọc thành tiến độ render."""
    job = fresh_manager.start(
        "video", fake_argv("Short2Math", "--browser-noise"), shot="Short2Math"
    )
    done = wait_for(fresh_manager, job.id)
    assert done.status == "done"
    # Nếu bắt bừa '%', dòng nhiễu sau mốc 92% sẽ kéo tiến độ xuống 0.5.
    assert done.progress == 1.0
    assert any("Downloading 50%" in line for line in fresh_manager.logs(job.id)), (
        "dòng nhiễu phải vẫn được ghi vào log, chỉ là không tính vào tiến độ"
    )


def test_tien_do_cua_shot_khac_khong_duoc_tinh(fresh_manager, fake_argv):
    """fake_render in tiến độ của 'OtherShot' nhưng job khai là 'Short2Math'."""
    job = fresh_manager.start("video", fake_argv("OtherShot"), shot="Short2Math")
    done = wait_for(fresh_manager, job.id)
    assert done.status == "done"
    # Không mốc tiến độ nào được nhận; chỉ có bước kết thúc đẩy lên 1.0.
    assert done.progress == 1.0


def test_tien_trinh_loi_thi_job_bao_loi(fresh_manager, fake_argv):
    job = fresh_manager.start("video", fake_argv("Short2Math", "--fail"), shot="Short2Math")
    done = wait_for(fresh_manager, job.id)
    assert done.status == "error"
    assert "thoát mã 1" in done.error


def test_lenh_khong_ton_tai_thi_bao_loi_chu_khong_treo(fresh_manager):
    job = fresh_manager.start("video", ["/khong/co/lenh/nay"], shot="X")
    done = wait_for(fresh_manager, job.id, timeout=10)
    assert done.status == "error"
    assert "không chạy được" in done.error


# --------------------------------------------------------------------- huỷ

def test_huy_job_dang_chay(fresh_manager, fake_argv):
    job = fresh_manager.start("video", fake_argv("Short2Math", "--hang"), shot="Short2Math")
    deadline = time.time() + 10
    while time.time() < deadline and fresh_manager.get(job.id).status != "running":
        time.sleep(0.05)

    assert fresh_manager.cancel(job.id) is True
    done = wait_for(fresh_manager, job.id, timeout=20)
    assert done.status == "error"
    assert "đã huỷ" in done.error


def test_khong_huy_duoc_job_da_xong(fresh_manager, fake_argv):
    job = fresh_manager.start("video", fake_argv("Short2Math"), shot="Short2Math")
    wait_for(fresh_manager, job.id)
    assert fresh_manager.cancel(job.id) is False


def test_huy_ngay_lap_tuc_van_an_thua(fresh_manager, fake_argv):
    """Lỗi đã sửa: huỷ ngay sau khi bấm render từng trượt.

    Trạng thái được đặt 'running' trước khi tiến trình kịp vào _procs, nên
    cancel() không thấy gì để giết — báo không huỷ được mà render vẫn chạy.
    Không sleep ở đây chính là điểm mấu chốt của bài test.
    """
    job = fresh_manager.start("video", fake_argv("Short2Math", "--hang"), shot="Short2Math")
    assert fresh_manager.cancel(job.id) is True
    done = wait_for(fresh_manager, job.id, timeout=20)
    assert done.status == "error"
    assert "đã huỷ" in done.error


def test_huy_som_thi_tien_trinh_con_khong_song_sot(fresh_manager, fake_argv):
    """Huỷ sớm phải thật sự giết tiến trình, không để nó chạy mồ côi."""
    job = fresh_manager.start("video", fake_argv("Short2Math", "--hang"), shot="Short2Math")
    fresh_manager.cancel(job.id)
    wait_for(fresh_manager, job.id, timeout=20)

    time.sleep(0.5)
    proc = fresh_manager._procs.get(job.id)
    assert proc is None or proc.poll() is not None, "tiến trình con phải đã chết"
    assert fresh_manager.busy_with("Short2Math", "video") is None


# ----------------------------------------------------------------- dọn job

def test_don_bot_job_da_xong_giu_lai_moi_nhat(fresh_manager):
    for i in range(MAX_FINISHED_JOBS + 40):
        j = Job(id=f"j{i:04d}", kind="video", shot=f"S{i}", status="done")
        j.updated_at = time.time() + i
        fresh_manager._jobs[j.id] = j
        fresh_manager._logs[j.id] = ["x"] * 100
    fresh_manager._prune()

    assert len(fresh_manager._jobs) == MAX_FINISHED_JOBS
    assert len(fresh_manager._logs) == MAX_FINISHED_JOBS
    kept = sorted(fresh_manager._jobs)
    assert kept[-1] == f"j{MAX_FINISHED_JOBS + 39:04d}", "phải giữ cái mới nhất"


def test_khong_don_job_dang_chay_du_cu(fresh_manager):
    old = Job(id="dangchay", kind="video", shot="X", status="running")
    old.updated_at = 0  # cũ nhất
    fresh_manager._jobs["dangchay"] = old
    for i in range(MAX_FINISHED_JOBS + 20):
        j = Job(id=f"d{i:04d}", kind="video", shot="Y", status="done")
        j.updated_at = time.time() + i
        fresh_manager._jobs[j.id] = j
    fresh_manager._prune()

    assert "dangchay" in fresh_manager._jobs


def test_log_bi_gioi_han_do_dai(fresh_manager):
    from webapp.jobs import MAX_LOG_LINES

    for i in range(MAX_LOG_LINES + 250):
        fresh_manager._append_log("j1", f"dòng {i}")
    logs = fresh_manager.logs("j1")
    assert len(logs) == MAX_LOG_LINES
    assert logs[-1] == f"dòng {MAX_LOG_LINES + 249}", "phải giữ dòng mới nhất"


# ------------------------------------------------------------- chặn trùng

def test_busy_with_nhan_dien_job_dang_chay(fresh_manager, fake_argv):
    job = fresh_manager.start("video", fake_argv("X", "--hang"), shot="Short2Math")
    try:
        assert fresh_manager.busy_with("Short2Math", "video") is not None
        assert fresh_manager.busy_with("Short2Math", "still") is None, "khác kind thì không tính"
        assert fresh_manager.busy_with("Short9Chords", "video") is None, "khác shot thì không tính"
    finally:
        fresh_manager.cancel(job.id)


def test_busy_with_bo_qua_job_da_xong(fresh_manager, fake_argv):
    job = fresh_manager.start("video", fake_argv("Short2Math"), shot="Short2Math")
    wait_for(fresh_manager, job.id)
    assert fresh_manager.busy_with("Short2Math", "video") is None
