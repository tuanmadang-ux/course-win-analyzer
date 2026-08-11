Kho này có **hai phần mềm chạy local**, dùng chung file `.env`:

| Chạy | Làm gì |
|---|---|
| `python run.py` | [✂️ **Trợ lý cắt video**](#-trợ-lý-cắt-video) — cắt im lặng/từ đệm/vấp, chèn B-roll, xuất 9:16 |
| `python run_radar.py` | [📡 **Radar đối thủ**](#-radar-đối-thủ) — đào insight từ bình luận đối thủ, viết bài mới, đo hiệu suất |

---

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
5. **Chưa ưng ngưỡng cắt?** Kéo lại thanh trượt ở bước 2 rồi bấm **🔄 Dò lại với cài đặt mới**.
   Lời thoại đã bóc được dùng lại nên chỉ mất vài giây thay vì chạy lại Whisper từ đầu —
   cứ thử thoải mái cho tới khi vừa ý. Tick **tìm lại cả B-roll** nếu muốn đổi luôn hình
   chèn (cái này mới tốn thêm lượt gọi API).

   > Lưu ý: dò lại sẽ **đặt lại** các tick bạn đã chỉnh tay, vì danh sách đề xuất được
   > sinh mới theo ngưỡng mới.

6. **Xuất** — chọn 9:16 / tỉ lệ gốc / .srt / nướng phụ đề, rồi **Render ngay**.

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

---
---

# 📡 Radar đối thủ

```bash
python run_radar.py      # mở http://127.0.0.1:8010
```

Đọc phần bình luận dưới bài của đối thủ để biết khách đang **hỏi gì, nghi ngờ gì, bức
xúc gì mà bài gốc chưa gỡ được** — rồi viết bài mới của bạn nhắm thẳng vào chỗ đó.

Không cần API key vẫn dùng được: dán bài + bình luận bằng tay → hệ thống chấm điểm,
gom cụm, rút insight, rồi giao dàn ý cho bạn viết.

## Luồng 5 bước

```
1. Thu thập  →  2. Bài đã thu  →  3. Insight  →  4. Duyệt & đăng  →  5. Hiệu suất
```

| Bước | Việc | Cần key? |
|---|---|---|
| 1 | Lấy bài + bình luận về (3 cách: dán tay / nhập file / Apify) | Chỉ cách 3 mới cần |
| 2 | Chấm điểm từng bình luận, bỏ "hay quá ạ", giữ câu hỏi & phản đối | Không |
| 2 | Gom bình luận cùng ý về một cụm (TF-IDF, hiểu tiếng Việt không dấu) | Không |
| 3 | Tổng hợp thành insight + **chỉ ra bài gốc còn thiếu chỗ nào** | Có (không key thì lấy bình luận tiêu biểu) |
| 3 | Viết bài mới: 3 hook + thân bài + CTA, 4 định dạng | Có (không key thì ra dàn ý) |
| 3 | Đo độ trùng lặp với bài gốc, chặn bài chép | Không |
| 4 | Bạn đọc lại, sửa, duyệt → lên lịch khung giờ vàng | Không |
| 4 | Đẩy lịch lên Fanpage **của bạn** qua Graph API | Có `FB_PAGE_TOKEN` |
| 5 | Kéo chỉ số về, chỉ ra công thức nào đang ăn nhất | Có `FB_PAGE_TOKEN` |

## Ba cách lấy dữ liệu về

**① Dán tay** (luôn dùng được) — mở bài đối thủ, bấm hết "Xem thêm bình luận", quét
chọn, dán vào ô. Bộ tách tự cắt từng bình luận và bỏ dòng rác `Thích · Trả lời · 2 ngày`.

**② Nhập file** — `.json`, `.jsonl`, `.csv` bạn đã xuất từ công cụ khác. Không cần đúng
tên cột: hệ thống thử lần lượt `text`/`message`/`content`, `likes`/`likesCount`… và tự
biết bản ghi nào là bài, bản ghi nào là bình luận.

**③ Apify** — điền `APIFY_TOKEN` + `APIFY_ACTOR_POSTS` vào `.env` rồi dán link fanpage.
Phần mềm gọi API công khai của Apify bằng token **của bạn**; hạn mức và việc tuân thủ
điều khoản nền tảng thuộc về tài khoản Apify của bạn.

> Muốn dùng nhà cung cấp khác? Viết một hàm trả về `list[dict]` rồi gắn vào
> `radar/ingest/__init__.py` — phần còn lại của luồng chạy y nguyên.

## Ba chốt chặn đặt cứng trong code

Đây là phần đáng đọc nhất, vì nó quyết định bạn có bị bóp reach hay dính bản quyền không.

**1. Ẩn danh người bình luận ngay ở cửa vào.** Tên người bình luận bị băm thành mã
`nd_xxxxxxxxxx` (muối riêng theo máy, không tra ngược được). Số điện thoại, email, thẻ
`@tên`, link trong nội dung bị thay bằng `[sđt]` `[email]` `[tên]` `[link]`. Kho dữ liệu
của bạn giữ được *điều họ nói*, không giữ *họ là ai*.

**2. Chặn bài "xào" quá tay.** Mỗi bài AI viết ra đều bị đo hai chỉ số so với bài gốc:

- tỉ lệ trùng cụm 5 tiếng (ngưỡng 28%)
- chuỗi từ giống hệt dài nhất (ngưỡng 12 từ)

Vượt ngưỡng → AI được yêu cầu viết lại một lần; vẫn vượt → bài bị gắn cờ đỏ và
**không duyệt được** cho tới khi bạn sửa. Sửa xong hệ thống đo lại ngay.

**3. Không có gì tự lên trang.** Bài phải được bấm **Duyệt** thủ công mới lên lịch hay
đăng được. Không có công tắc nào tắt bước này.

Phần mềm **không** đăng nhập Facebook, không dùng cookie của bạn, không né giới hạn tần
suất. Graph API chỉ dùng cho Fanpage bạn quản trị (đăng bài + đọc chỉ số của chính bạn).

## Khung giờ vàng

Tính từ chính bài của trang bạn: gom theo giờ trong ngày, chấm điểm
`tim + 2×bình_luận + 3×chia_sẻ`, lấy giờ mạnh nhất. Dưới 8 bài thì chưa đủ mẫu →
dùng mốc phổ biến ở VN (11–13h, 19–22h). Hai bài lên lịch luôn cách nhau ít nhất 4 giờ.

Đặt `TZ_OFFSET_HOURS=7` trong `.env` cho giờ Việt Nam.

## Đo hiệu suất

Tab 5 không chỉ liệt kê số like. Nó nhóm các bài đã đăng theo **dạng insight**
(câu hỏi / phản đối / trải nghiệm) và theo **định dạng** (bài dài / gạch đầu dòng /
Reels / carousel), rồi nói thẳng công thức nào đang cho tương tác cao nhất để bạn nhân
bản. Bài đăng dưới 6 giờ chỉ ghi nhận, chưa đem xếp hạng.

## Cấu trúc mã nguồn

```
run_radar.py               khởi động server + mở trình duyệt
radar/
  config.py                khoá API, ngưỡng lọc, ngưỡng chống trùng lặp
  store.py                 SQLite: sources, posts, comments, insights, drafts, metrics
  llm.py                   gọi Claude, ép trả JSON đúng schema
  main.py                  route API
  service.py               điều phối các bước
  jobs.py                  tác vụ nền + báo tiến độ
  ingest/
    normalize.py           chuẩn hoá tên trường lệch nhau + ẩn danh
    paste.py               tách khối chữ dán tay thành từng bình luận
    filefeed.py            đọc CSV/JSON/JSONL, phân biệt bài với bình luận
    apify.py               gọi actor Apify bằng token của bạn
  mine/
    text.py                tách tiếng Việt, bỏ dấu, bigram, n-gram
    quality.py             chấm điểm & phân loại bình luận (offline)
    cluster.py             gom bình luận cùng ý (TF-IDF + cosine)
    insight.py             tổng hợp cụm thành insight + "bài gốc còn thiếu"
  create/
    write.py               viết hook + thân bài + CTA theo 4 định dạng
    originality.py         đo độ trùng lặp, chặn bài chép
  publish/
    facebook.py            Graph API — chỉ cho trang của bạn
    schedule.py            khung giờ vàng + xếp lịch
  measure/                 kéo chỉ số, tìm công thức hiệu quả nhất
  static/                  giao diện web (không dùng thư viện ngoài)
data/radar/radar.db        toàn bộ dữ liệu (đã .gitignore)
```

Không cần cài thêm thư viện nào ngoài `requirements.txt` sẵn có.

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| Dán bình luận vào mà tách sai | Dán lại, để mỗi bình luận cách nhau một dòng trống |
| "Không cái nào đủ chất" | Bài đó toàn khen xã giao. Hạ *Bình luận ngắn hơn … chữ thì bỏ* xuống 3 |
| Insight toàn cụm 1 bình luận | Bình thường với bài ít bình luận. Thu thêm bài của cùng đối thủ |
| Bài viết ra bị gắn cờ đỏ liên tục | Thêm `BRAND_VOICE` vào `.env` để AI có giọng riêng mà bám vào |
| Apify báo 404 actor | Tên actor phải đúng dạng `user/ten-actor`, xem lại `APIFY_ACTOR_POSTS` |
| Apify chạy xong mà 0 bài | Actor bạn chọn dùng schema đầu vào khác — sửa `APIFY_POSTS_INPUT` trong `.env` |
| Graph API báo lỗi quyền | Page Access Token cần quyền `pages_manage_posts` + `pages_read_engagement` |
| Tab Hiệu suất trống | Chỉ đếm bài đăng **qua hệ thống**; bài đăng tay không có trong đó |
