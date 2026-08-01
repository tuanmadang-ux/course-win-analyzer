# ✂️ Trợ lý cắt video

Phần mềm chạy trên máy bạn (web app local). Thả video vào → nó tự bóc lời, tìm chỗ
im lặng / từ đệm / câu vấp / đoạn lạc đề, gợi ý B-roll **đúng ngữ cảnh câu đang nói**,
cho bạn duyệt lại, rồi xuất bản dọc 9:16 cho TikTok / Reels / Shorts.

---

## Nó làm được gì

| Việc | Cách làm | Cần key? |
|---|---|---|
| Bóc lời tiếng Việt (timestamp từng chữ) | Whisper `large-v3` chạy local trên GPU của bạn | Không |
| Cắt khoảng im lặng | ffmpeg `silencedetect`, có chừa đệm hai đầu cho tự nhiên | Không |
| Cắt từ đệm (ừ, à, ờ, kiểu như…) | Đối chiếu timestamp từng chữ với danh sách từ đệm tiếng Việt | Không |
| Cắt câu vấp / nói lại | AI đọc transcript. Không có key thì dùng thuật toán so trùng câu | Không (có key thì chuẩn hơn nhiều) |
| Cắt đoạn lạc đề, dài dòng | AI chấm theo chủ đề chính, mặc định **chỉ đề xuất** chứ không tự cắt | Có |
| B-roll đúng ngữ cảnh | AI chọn vị trí + viết từ khoá tiếng Anh → tìm Pexels/Pixabay → AI chấm điểm độ khớp rồi mới tải | Có |
| Xuất 9:16 tự bám mặt người nói | Dò mặt bằng OpenCV, làm mượt quỹ đạo, crop theo từng đoạn | Không |
| Phụ đề .srt (và nướng lên video) | Sinh từ transcript, khớp lại thời gian sau khi cắt | Không |

**Không có API key vẫn dùng được ngay**: cắt im lặng + từ đệm + vấp + xuất 9:16 + phụ đề
đều chạy hoàn toàn offline.

---

## Cài đặt

```bash
git clone <repo> && cd course-win-analyzer
bash setup.sh
```

Script sẽ cài ffmpeg, tạo `.venv`, cài thư viện Python, và tạo file `.env`.

<details>
<summary>Cài tay (hoặc trên Windows)</summary>

```bash
# 1. ffmpeg
#    Windows : winget install Gyan.FFmpeg
#    macOS   : brew install ffmpeg
#    Ubuntu  : sudo apt install ffmpeg

# 2. Python
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# 3. Cấu hình
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux
```
</details>

### Bật GPU NVIDIA cho Whisper

`faster-whisper` cần cuBLAS + cuDNN. Cách dễ nhất:

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

Nếu vẫn lỗi, phần mềm **tự chuyển sang CPU** (chậm hơn nhưng vẫn chạy) — không cần làm gì.
Muốn ép CPU: đặt `WHISPER_DEVICE=cpu` trong `.env`.

---

## Chạy

```bash
source .venv/bin/activate    # Windows: .venv\Scripts\activate
python run.py
```

Trình duyệt tự mở `http://127.0.0.1:8000`.

> Lần chạy đầu tiên Whisper tải model về (~3GB với `large-v3`). Từ lần sau là tức thì.

---

## API key (tuỳ chọn — điền vào file `.env`)

| Key | Lấy ở đâu | Mở khoá tính năng gì |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → Settings → API Keys | Hiểu ngữ cảnh: phát hiện vấp/lạc đề, chọn vị trí B-roll, chấm điểm độ khớp của clip |
| `PEXELS_API_KEY` | [pexels.com/api/new](https://www.pexels.com/api/new/) — **miễn phí, 1 phút** | Kho video stock |
| `PIXABAY_API_KEY` | [pixabay.com/api/docs](https://pixabay.com/api/docs/) — **miễn phí** | Kho video stock dự phòng |

Chi phí Claude rất nhỏ: mỗi video ~10–20 phút chỉ tốn vài xu (chỉ gửi transcript dạng chữ,
không gửi video).

---

## Quy trình dùng

1. **Thả video vào** — hỗ trợ MP4, MOV, MKV, WebM, AVI…
2. **Tick thứ cần cắt** — mặc định đã hợp lý. Vào *Tinh chỉnh nâng cao* nếu muốn siết
   ngưỡng im lặng hoặc thêm từ đệm của riêng bạn.
3. Bấm một trong hai:
   - **Phân tích & để tôi duyệt** — xem từng đề xuất, bỏ tick cái nào không ưng.
   - **⚡ Auto** — chạy thẳng một mạch tới file thành phẩm.
4. **Duyệt** — 3 tab:
   - *Đoạn cắt*: mỗi dòng có lý do; bấm vào để tua video tới đúng chỗ.
   - *B-roll*: xem ảnh thumbnail + điểm khớp ngữ cảnh; sửa từ khoá rồi bấm **Tìm lại**
     nếu muốn hình khác.
   - *Lời thoại*: toàn bộ transcript, dòng bị cắt hiện gạch ngang.
   - Thanh timeline: vạch đỏ = sẽ cắt, vạch xanh = có B-roll. Bấm để tua.
5. **Xuất** — chọn 9:16 / tỉ lệ gốc / .srt / nướng phụ đề, rồi **Render ngay**.

---

## Cấu trúc mã nguồn

```
run.py                     khởi động server + mở trình duyệt
app/
  config.py                đường dẫn, key, các ngưỡng cắt mặc định
  main.py                  các route API của FastAPI
  jobs.py                  chạy tác vụ nền + báo tiến độ
  service.py               điều phối: phân tích → duyệt → render
  models.py                khai báo dữ liệu vào/ra
  pipeline/
    ffmpeg_utils.py        gọi ffmpeg/ffprobe, đọc metadata, tách audio
    transcribe.py          Whisper, trả timestamp từng chữ
    silence.py             dò khoảng im lặng
    fillers.py             từ đệm tiếng Việt
    analyze.py             gọi Claude: vấp / lạc đề / kế hoạch B-roll / chấm điểm
    broll.py               tìm & tải clip từ Pexels, Pixabay
    reframe.py             bám mặt người nói cho khung 9:16
    timeline.py            biến danh sách cắt thành danh sách clip để render
    subtitles.py           sinh .srt đã khớp lại thời gian
    render.py              cắt từng clip → ghép → nướng phụ đề
  static/                  giao diện web (không dùng thư viện ngoài)
data/                      video tải lên, kết quả, cache B-roll (đã .gitignore)
```

---

## Cách hoạt động (phần đáng chú ý)

**Timeline không phải là "overlay".** Mỗi đoạn B-roll được cắt thành một clip riêng
lấy **hình từ clip stock, tiếng từ video gốc**, rồi ghép nối tiếp với các clip A-roll.
Nhờ vậy tiếng nói không bao giờ bị lệch khỏi hình dù cắt bao nhiêu chỗ.

**B-roll "đúng ngữ cảnh" đi qua 3 lớp lọc:**
1. AI đọc transcript, chỉ chọn câu nào *nhìn được* (sự vật, hành động, địa điểm) — bỏ qua
   câu chào hỏi, chuyển ý.
2. AI viết từ khoá tiếng Anh **cụ thể** (`"hands typing on laptop keyboard"`), không phải
   từ chung chung (`"business"`).
3. Tải về 6 ứng viên (mới chỉ metadata), AI chấm điểm 0–100 độ khớp với đúng câu đang nói.
   Dưới 55 điểm thì mặc định **không tick** — thà không chèn còn hơn chèn hình sai.

**Auto-reframe 9:16** dùng crop cố định cho từng đoạn clip (lấy trung vị vị trí mặt trong
đoạn đó, đã làm mượt EMA) thay vì pan liên tục — ổn định, không rung, không cần model nặng.

---

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| `CHƯA CÀI FFMPEG` | Cài ffmpeg rồi mở terminal mới |
| Whisper báo lỗi CUDA / cuDNN | `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`, hoặc đặt `WHISPER_DEVICE=cpu` |
| Render lỗi codec | Đặt `USE_NVENC=0` trong `.env` để dùng CPU (libx264) |
| Tab B-roll trống | Cần **cả** `ANTHROPIC_API_KEY` lẫn key stock. Thiếu một trong hai là không có B-roll |
| Cắt quá tay | Kéo *Ngưỡng im lặng* xuống thấp hơn (-40), tăng *Im lặng dài hơn* lên 0.9s, tăng *Chừa lại mỗi đầu* |
| Video dài xử lý lâu | Bình thường — Whisper là khâu chậm nhất. Dùng `WHISPER_MODEL=medium` để nhanh gấp đôi |
| Máy hết dung lượng | Xoá thư mục `data/jobs/` và `data/broll_cache/` |

---

## Bản quyền B-roll

Video từ Pexels và Pixabay dùng được cho mục đích thương mại, không bắt buộc ghi nguồn.
Phần mềm vẫn lưu lại tên tác giả và link trang gốc trong `data/jobs/<id>/project.json`
nếu bạn muốn ghi credit.
