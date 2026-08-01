"""Test khâu ghép danh mục và dò công cụ."""

from __future__ import annotations

from webapp import catalog, config


def test_doc_du_14_composition():
    assert len(catalog.shots()) == 14


def test_moi_shot_deu_ghep_duoc_voi_du_an():
    """Mọi composition phải có beats.json tương ứng — thiếu là registry lệch."""
    khong_ghep = [s["id"] for s in catalog.shots() if not s["folder"]]
    assert not khong_ghep, f"không tìm thấy dự án cho: {khong_ghep}"


def test_thu_muc_du_an_ton_tai_that():
    for s in catalog.shots():
        assert (config.ROOT / s["folder"]).is_dir(), f"{s['id']} trỏ vào thư mục không có"


def test_shot_tra_ve_dung_cai_can_tim():
    s = catalog.shot("Short2Math")
    assert s is not None and s["id"] == "Short2Math"
    assert catalog.shot("KhongCoShotNay") is None


def test_script_text():
    assert "×11" in (catalog.script_text("Short2Math") or "")
    assert catalog.script_text("KhongCoShotNay") is None


def test_shot_trong_suot_dung_duoi_mov():
    """Shot transparent xuất .mov (ProRes), còn lại .mp4 — ảnh hưởng link tải."""
    for s in catalog.shots():
        if s["video"]:
            assert s["video"].endswith(".mov" if s["transparent"] else ".mp4")


def test_quan_co_day_du():
    """Bộ 12 quân do gen_chess_pieces.py vẽ — thiếu là Short1Chess render hỏng."""
    chess = config.ROOT / "media" / "library" / "chess"
    thieu = [
        f"{c}{k}.svg"
        for c in ("w", "b")
        for k in ("K", "Q", "R", "B", "N", "P")
        if not (chess / f"{c}{k}.svg").exists()
    ]
    assert not thieu, f"thiếu quân cờ: {thieu}"


def test_quan_co_la_svg_hop_le():
    import xml.etree.ElementTree as ET

    for p in (config.ROOT / "media" / "library" / "chess").glob("*.svg"):
        ET.parse(p)  # ném lỗi nếu XML hỏng


def test_dinh_dang_media_duoc_tham_chieu_deu_ton_tai():
    """Mọi staticFile('...') tĩnh trong TSX phải trỏ vào file có thật."""
    import re

    src = config.ROOT / "remotion" / "src"
    pattern = re.compile(r"""staticFile\(\s*['"]([^'"$]+)['"]""")
    thieu = []
    for f in src.rglob("*.tsx"):
        for ref in pattern.findall(f.read_text(encoding="utf-8")):
            if not (config.ROOT / "media" / ref).exists():
                thieu.append(f"{f.name}: {ref}")
    assert not thieu, f"tham chiếu media không tồn tại: {thieu}"


def test_find_browser_tra_ve_duong_dan_chay_duoc():
    import os

    b = config.find_browser()
    if b is not None:
        assert os.access(b, os.X_OK)


def test_render_env_gan_bien_trinh_duyet():
    env = config.render_env()
    if config.find_browser():
        assert env["REMOTION_BROWSER_EXECUTABLE"] == config.find_browser()
