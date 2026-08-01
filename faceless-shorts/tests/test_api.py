"""Test tầng HTTP: định tuyến, kiểm tra đầu vào, chặn trùng, phục vụ file."""

from __future__ import annotations

import pytest

from webapp import jobs


# ------------------------------------------------------------- trạng thái

def test_status_tra_ve_du_truong(client):
    d = client.get("/api/status").json()
    assert set(d) >= {"node", "ffmpeg", "deps", "browser", "browser_auto", "shots"}
    assert d["shots"] == 14, "registry phải có đủ 14 composition"


def test_trang_chu_va_tai_nguyen_tinh(client):
    assert client.get("/").status_code == 200
    assert client.get("/style.css").status_code == 200
    assert client.get("/app.js").status_code == 200


# ---------------------------------------------------------------- danh mục

def test_danh_sach_shot_du_va_dung_cau_truc(client):
    shots = client.get("/api/shots").json()["shots"]
    assert len(shots) == 14
    for s in shots:
        assert set(s) >= {"id", "title", "track", "width", "height", "fps", "duration_s", "frames"}
        assert s["track"] in ("tsx", "ai", "vox")
        assert s["width"] == 1080 and s["height"] == 1920, "shorts phải là dọc 9:16"
        assert s["frames"] == round(s["duration_s"] * s["fps"])


def test_metadata_duoc_ghep_tu_beats_json(client):
    shots = {s["id"]: s for s in client.get("/api/shots").json()["shots"]}
    # Tiêu đề lấy từ beats.json chứ không phải tên composition.
    assert shots["Short2Math"]["title"] == "The ×11 Trick"
    assert shots["Short2Math"]["track"] == "tsx"
    assert shots["Short2Math"]["vo_lines"] > 0
    assert shots["Vox1Coffee"]["track"] == "vox"
    assert shots["Ai1Door"]["track"] == "ai"


def test_doc_duoc_kich_ban(client):
    d = client.get("/api/shots/Short2Math/script").json()
    assert "×11" in d["script"]


def test_shot_khong_ton_tai_tra_404(client):
    assert client.get("/api/shots/KhongCoShotNay/script").status_code == 404


# ------------------------------------------------------- kiểm tra đầu vào

@pytest.mark.parametrize(
    "path",
    [
        "/api/still/..%2f..%2fetc%2fpasswd.png",
        "/api/qa/..%2f..%2fpackage.json",
        "/api/video/..%2f..%2f.env",
        "/api/shots/..%2f..%2fetc/script",
    ],
)
def test_chan_di_nguoc_thu_muc(client, path):
    assert client.get(path).status_code in (400, 404)


@pytest.mark.parametrize(
    "comp_id", ["Short2Math; rm -rf /", "Short2Math&&ls", "../Short2Math", "Short-2-Math", ""]
)
def test_id_khong_hop_le_bi_tu_choi(client, comp_id):
    r = client.post("/api/render", json={"id": comp_id, "kind": "still"})
    assert r.status_code in (400, 404, 422)
    assert not client.started, "không được chạy tiến trình nào"


@pytest.mark.parametrize("scale", [0, 0.1, 3, 99, -1])
def test_scale_ngoai_khoang_bi_tu_choi(client, scale):
    r = client.post("/api/render", json={"id": "Short2Math", "kind": "video", "scale": scale})
    assert r.status_code == 422


@pytest.mark.parametrize("kind", ["rm -rf", "mp4", "", "STILL"])
def test_kind_la_bi_tu_choi(client, kind):
    r = client.post("/api/render", json={"id": "Short2Math", "kind": kind})
    assert r.status_code == 422


@pytest.mark.parametrize("frames", ["abc", "1;2", "-5", "", "1.5", "1 2", "$(ls)"])
def test_danh_sach_khung_hinh_khong_hop_le_bi_tu_choi(client, frames):
    r = client.post("/api/frames", json={"id": "Short2Math", "frames": frames})
    assert r.status_code == 400
    assert not client.started


@pytest.mark.parametrize(
    "frames, expect",
    [("1,,2", "1,2"), (" 0 , 10 ", "0,10"), ("5,", "5")],
)
def test_dau_phay_thua_va_khoang_trang_duoc_bo_qua(client, frames, expect):
    """Gõ thừa dấu phẩy là lỗi đánh máy chứ không phải ý đồ — chuẩn hoá, đừng chặn."""
    r = client.post("/api/frames", json={"id": "Short2Math", "frames": frames})
    assert r.status_code == 200
    assert client.started[0]["argv"][3] == expect


def test_gioi_han_so_khung_hinh(client):
    r = client.post("/api/frames", json={"id": "Short2Math", "frames": ",".join("1" * 20)})
    assert r.status_code == 400


# ------------------------------------------------------------ chạy render

def test_render_video_dung_lenh(client):
    r = client.post("/api/render", json={"id": "Short2Math", "kind": "video", "scale": 1})
    assert r.status_code == 200
    call = client.started[0]
    assert call["argv"] == ["node", "scripts/render-all.mjs", "Short2Math", "--scale=1.0"]
    assert "--still" not in call["argv"]


def test_render_anh_them_co_still(client):
    client.post("/api/render", json={"id": "Short2Math", "kind": "still", "scale": 0.5})
    assert "--still" in client.started[0]["argv"]


def test_render_khung_hinh_dung_lenh(client):
    client.post("/api/frames", json={"id": "Short2Math", "frames": "0, 10 ,20", "scale": 0.5})
    argv = client.started[0]["argv"]
    assert argv[:4] == ["node", "scripts/frames.mjs", "Short2Math", "0,10,20"]


# ------------------------------------------------------------ chặn trùng

def _dat_job_dang_chay(shot: str, kind: str) -> None:
    from webapp.main import manager

    j = jobs.Job(id="busy0001", kind=kind, shot=shot, status="running")
    manager._jobs[j.id] = j


def test_chan_render_trung_cung_shot_cung_kind(client):
    _dat_job_dang_chay("Short2Math", "video")
    r = client.post("/api/render", json={"id": "Short2Math", "kind": "video"})
    assert r.status_code == 409
    assert "busy0001" in r.json()["detail"]


def test_cho_phep_render_shot_khac(client):
    _dat_job_dang_chay("Short2Math", "video")
    assert client.post("/api/render", json={"id": "Short9Chords", "kind": "video"}).status_code == 200


def test_cho_phep_cung_shot_khac_kind(client):
    """Ghi ra file khác nhau nên không đụng nhau."""
    _dat_job_dang_chay("Short2Math", "video")
    assert client.post("/api/render", json={"id": "Short2Math", "kind": "still"}).status_code == 200
    assert client.post("/api/frames", json={"id": "Short2Math", "frames": "0"}).status_code == 200


def test_chan_gen_registry_trung(client):
    assert client.post("/api/gen").status_code == 200
    _dat_job_dang_chay("", "gen")
    assert client.post("/api/gen").status_code == 409


# ----------------------------------------------------------------- tác vụ

def test_job_khong_ton_tai_tra_404(client):
    assert client.get("/api/jobs/khongcojobnay").status_code == 404
    assert client.post("/api/jobs/khongcojobnay/cancel").status_code == 409


def test_liet_ke_tac_vu(client):
    client.post("/api/render", json={"id": "Short2Math", "kind": "still"})
    assert len(client.get("/api/jobs").json()["jobs"]) == 1


# -------------------------------------------------------------- file ra

def test_video_chua_render_tra_404(client):
    r = client.get("/api/video/Short11Map")
    assert r.status_code in (200, 404)  # tuỳ máy đã render hay chưa
    if r.status_code == 404:
        assert "chưa render" in r.json()["detail"]


def test_qa_frames_tra_ve_danh_sach(client):
    d = client.get("/api/qa-frames/Short2Math").json()
    assert isinstance(d["frames"], list)
    assert all(n.startswith("Short2Math-f") for n in d["frames"])


@pytest.mark.parametrize("name", ["x.txt", "../x.png", "x.png; ls", "x"])
def test_ten_file_qa_khong_hop_le_bi_tu_choi(client, name):
    assert client.get(f"/api/qa/{name}").status_code in (400, 404)
