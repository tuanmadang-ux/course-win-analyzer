# Hướng dẫn — Xưởng làm video Shorts faceless

Nguồn: [hassancs91/claude-faceless-shorts-creator](https://github.com/hassancs91/claude-faceless-shorts-creator) (MIT).
Tài liệu gốc tiếng Anh: `README.md` · `CLAUDE.md` · `brand.md`.

Đây **không phải web app**. Nó là một *xưởng sản xuất* mà bạn điều khiển bằng Claude Code:
bạn mô tả video muốn làm, Claude viết animation bằng code (Remotion), lồng tiếng, khớp phụ đề
theo từng chữ, chèn âm thanh, rồi xuất file MP4 dọc 9:16.

---

## Ba kiểu video

| Bạn nói với Claude | Skill chạy | Hình ảnh đến từ đâu | Thư mục |
|---|---|---|---|
| "make a short about \<chủ đề\>" | `/make-short` | 100% code — animation TSX, không cần footage | `shorts/` |
| "make an AI video short about \<ý tưởng\>" | `/make-ai-short` | model video AI (fal.ai), nhân vật cố định | `ai-shorts/` |
| "make a vox-style short about \<câu chuyện\>" | `/make-vox` | collage giấy kiểu phóng sự Vox | `vox-shorts/` |

Cả ba đều dùng chung: hợp đồng nhịp `beats.json` → giọng ElevenLabs + phụ đề khớp **đúng từng chữ**
→ QA từng khung hình ở kích thước điện thoại → thư viện SFX dùng lại → kết thúc lặp liền mạch
(khung đầu = khung cuối), không có outro kêu gọi like/subscribe.

---

## Cài đặt

```bash
cd faceless-shorts
bash setup.sh          # lõi: TSX + generative
bash setup.sh --vox    # cài thêm pillow/rembg/playwright cho track collage
```

Script sẽ kiểm tra `node ≥18`, `python3 ≥3.10`, `ffmpeg`/`ffprobe`, tạo `.env`, chạy
`npm install` và `npm run gen`.

### Cần gì

| Thứ | Bắt buộc? | Dùng để |
|---|---|---|
| Node 18+, Python 3.10+, ffmpeg | **Có** | render, ghép tiếng |
| Claude Code | **Có** | chính là "biên tập viên" — nơi 5 skill sống |
| `ELEVENLABS_API_KEY` | Cho lồng tiếng | giọng đọc + tạo SFX + nhạc nền |
| `GEMINI_API_KEY` | Tùy | sinh ảnh (truyện tranh, layer collage) |
| `FAL_KEY` | Tùy | sinh clip video AI (track generative) |

Điền key vào `.env` ở thư mục `faceless-shorts/`. **Không commit `.env`** (đã có trong `.gitignore`).

Không có key nào vẫn **render được toàn bộ 14 composition mẫu** — chỉ là không có giọng đọc mới.

---

## Bảng điều khiển render (webapp)

Không thích gõ lệnh thì mở giao diện web:

```bash
cd faceless-shorts
pip install -r webapp/requirements.txt   # lần đầu
python3 run_webapp.py                    # -> http://127.0.0.1:8770
```

Trong đó bạn có thể: xem cả 14 composition kèm ảnh preview, lọc theo track
(TSX / AI video / Collage), bấm render ảnh hoặc video và **theo dõi tiến độ theo %**,
render vài khung hình QA để soi nhanh, đọc kịch bản, xem lại video ngay trên trang
và tải MP4 về. Huỷ giữa chừng được.

Đổi cổng: `FACELESS_PORT=9000 python3 run_webapp.py`.

**Chạy test:**

```bash
pip install -r webapp/requirements-dev.txt
pytest                    # ~2.5s, không render thật
```

Bộ test không gọi Remotion (một lần render mất 40s+). `tests/fake_render.py` in ra
đúng định dạng output của Remotion — kể cả những chỗ từng gây lỗi: tiến độ ghi bằng
`\r`, cảnh báo bộ nhớ chen ngang, và dòng `Downloading 50% of chrome` vốn hay bị đọc
nhầm thành tiến độ render.

> Webapp chỉ **render** những gì đã có. Việc *tạo video mới* vẫn qua Claude Code —
> xem mục "Làm video mới" bên dưới.

Ngoài ra Remotion có sẵn giao diện riêng để xem/tua timeline: `cd remotion && npm run studio`.

---

## Chạy thử bằng dòng lệnh

```bash
cd faceless-shorts/remotion

# 1. Xem 3 khung hình QA (nhanh, ~1 phút)
node scripts/frames.mjs Short2Math 0,300,700 --scale=0.5
#    -> out/qa/Short2Math-f0000.png ...

# 2. Xuất 1 video hoàn chỉnh
node scripts/render-all.mjs Short2Math --scale=1
#    -> out/Short2Math.mp4   (1080x1920, h264, 42s)

# 3. Xem trực quan tất cả composition trong trình duyệt
npm run studio
```

`--scale=1` cho ra 1080×1920. Bỏ `--scale` thì mặc định `scale=2` → xuất 4K (lâu hơn nhiều).

> **Lưu ý về registry:** thêm/đổi tên shot xong phải chạy lại `npm run gen`.
> `frames.mjs` và `render-all.mjs` **không** tự chạy nó.

---

## Máy bị chặn mạng ra ngoài? (sandbox / CI / mạng nội bộ)

Mặc định Remotion tự tải Chrome Headless Shell từ `remotion.media`. Nếu host đó bị chặn,
trỏ thẳng vào Chrome/Chromium có sẵn:

```bash
export REMOTION_BROWSER_EXECUTABLE=/đường/dẫn/tới/chrome
node scripts/frames.mjs Short2Math 0 --scale=0.5
```

`setup.sh` sẽ tự dò và in ra đường dẫn nếu tìm thấy. Bỏ trống biến này thì Remotion tải như bình thường.

Ngoài ra font lấy từ `fonts.gstatic.com` lúc render. Nếu chạy sau proxy tự ký chứng chỉ,
Chromium phải tin CA của proxy — nạp vào NSS store:

```bash
sudo apt-get install -y libnss3-tools
certutil -A -n proxy-ca -t "C,," -i /đường/dẫn/ca.crt -d sql:$HOME/.pki/nssdb
```

Thiếu bước này, render sẽ chết với `ERR_CERT_AUTHORITY_INVALID` / `NetworkError`.

---

## Làm video mới

Mở Claude Code **tại thư mục `faceless-shorts/`** (không phải gốc repo — các tool phân giải
đường dẫn dự án theo thư mục hiện hành):

```bash
cd faceless-shorts
claude
```

Rồi nói tự nhiên:

- *"make a short about lãi kép"*
- *"make an AI video short with blue-man"*
- *"re-render short-5 and regenerate its voice"*

Claude sẽ tự chọn skill phù hợp, viết `script.md` + `beats.json`, dựng composition TSX,
render khung hình ra **đọc lại bằng mắt** để kiểm tra, rồi mới xuất bản đầy đủ.

### Đổi sang phong cách của bạn

`brand.md` là hợp đồng phong cách: bảng màu, font, chuyển động, vùng an toàn của phụ đề,
gu âm thanh. Sửa file đó — mọi video sau đều đi theo.

---

## Cấu trúc

```
.claude/skills/   5 skill: make-short, make-ai-short, make-vox,
                  vidtsx-2d-generator, suggest-sfx  ← "tay nghề" nằm ở đây
webapp/           bảng điều khiển render (FastAPI) — chạy bằng run_webapp.py
tests/            test tự động cho webapp (pytest) — chạy: pytest
tools/            Python: gen_voice, gen_sfx, gen_music, mix_sfx, mix_music,
                  gen_image, gen_clip, bakeoff_clip, cutout, capture_web, gen_chords,
                  gen_chess_pieces
remotion/         dự án Remotion — src/lib/ (kit dùng chung), src/shots/ (1 thư mục / video)
media/library/    tài sản dùng lại nhiều video: 33 SFX + 6 nhạc nền (có catalog)
media/projects/   media riêng của 1 video (clip AI, layer collage) — có commit
shorts/           12 video mẫu track TSX
ai-shorts/        track generative: blue-man (nhân vật khóa cứng) + bảng chi phí
vox-shorts/       track collage: vox-1-coffee + DESIGN.md (ngôn ngữ hình ảnh)
brand.md          hợp đồng phong cách
IDEAS.md          ngân hàng ý tưởng + xếp hạng ngách
```

**Quy tắc media:** `media/library/` chỉ chứa thứ dùng lại được cho nhiều video.
Thứ sinh ra cho **một** video cụ thể thì để `media/projects/<tên>/`.
Kiểm tra catalog trước khi sinh mới — dùng lại rẻ hơn tạo mới.

---

## Chi phí

Track TSX gần như **miễn phí** (chỉ tốn ElevenLabs cho giọng đọc).
Track generative tốn tiền thật cho mỗi clip — xem bảng chi phí mỗi giây trong
`ai-shorts/IDEAS.md`. Skill `/make-ai-short` có quy tắc cứng: **báo giá trước khi tiêu**,
và không bao giờ sinh lại nhân vật đã khóa từ mô tả chữ.

---

## Đã kiểm chứng trên môi trường này

| Hạng mục | Kết quả |
|---|---|
| Node / npm | v22.22.2 / 10.9.7 |
| Python | 3.11.15 |
| ffmpeg / ffprobe | 6.1.1 |
| `npm install` | 197 gói |
| `npm run gen` | 14 composition |
| `npx tsc --noEmit` | ✅ không lỗi |
| Render still **cả 14** composition | ✅ 14/14 |
| Render video đầy đủ | ✅ `out/Short2Math.mp4` — 1080×1920, h264+aac, 42.05s, 5.0MB |
| Tools Python (11 file) | ✅ chạy hết (stdlib); `gen_sfx`/`gen_music`/`gen_chords` đọc đúng catalog |
| Deps track vox | ✅ pillow 12.3.0 + rembg 2.0.77 (CPU) + playwright |

### Một chỗ upstream thiếu — đã vá

`remotion/src/lib/chess.tsx` nạp quân cờ qua `staticFile('library/chess/<mã>.svg')`,
nhưng repo gốc **không commit** thư mục đó. Hậu quả: `Short1Chess` render ra bàn cờ
toàn ảnh vỡ, rồi crash (`CancelledError` sau 404 + `EncodingError`).

Đã thêm `tools/gen_chess_pieces.py` — **vẽ** đủ 12 quân (w/b × K Q R B N P) thành SVG
thay vì tải bộ có sẵn về, nên không kéo theo giấy phép của bên thứ ba vào repo MIT này.

```bash
python3 tools/gen_chess_pieces.py           # ghi media/library/chess/*.svg
python3 tools/gen_chess_pieces.py --force   # vẽ lại sau khi sửa style
```

Muốn đổi kiểu quân cờ thì sửa `THEMES` / `PIECES` trong file đó rồi chạy lại với `--force`.
