# 🎬 Trợ lý video

Phần mềm chạy trên máy bạn (web app local, mở bằng trình duyệt). Hai công cụ dùng
chung một bộ máy render:

| Trang | Việc nó làm |
|---|---|
| **✂️ Cắt video** | Thả video quay sẵn vào → tự bóc lời, cắt chỗ im lặng / từ đệm / câu vấp, chèn B-roll đúng ngữ cảnh, xuất bản dọc 9:16 kèm phụ đề |
| **🎬 Tạo video** | Đưa ảnh 1–2 người + gõ nội dung → xuất video dọc 9:16 có người đó nói, nhép môi, phụ đề và nhạc nền |

---

# Phần A — 🎬 Tạo video người nói từ ảnh

## Nó làm được gì

Bạn đưa vào **ảnh chân dung** (1 người, hoặc 2 người để họ nói qua lại) và **nội
dung muốn nói**. Phần mềm trả về một file `.mp4` dọc 1080×1920 sẵn đăng TikTok /
Reels / Shorts.

Quy trình bên trong:

```
Ảnh + nội dung
   ↓  Gemini biên tập lại thành lời thoại dễ nói, chia câu theo nhịp video ngắn
   ↓  Gemini TTS đọc từng câu → biết CHÍNH XÁC câu nào dài bao nhiêu giây
   ↓  Dò mặt, dựng khung 9:16 (mặt ở 1/3 trên, nền mờ lấp phần thiếu)
   ↓  Engine nhép môi ghép ảnh + tiếng thành video người đang nói
   ↓  AI chọn chỗ đáng chèn thẻ đồ hoạ, dựng thẻ, chồng lên hình
   ↓  Phụ đề canh theo đúng độ dài từng câu, nướng lên hình
   ↓  Nhạc nền tự hạ xuống mỗi khi có tiếng nói (ducking)
video_doc_9x16.mp4  +  phu_de.srt
```

## Cần gì

| Thứ | Bắt buộc? | Lấy ở đâu |
|---|---|---|
| `GEMINI_API_KEY` | **Có** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — miễn phí |
| Engine nhép môi | Không, nhưng nên có | `bash setup_lipsync.sh` |
| Engine dựng thẻ đồ hoạ | Không | `bash setup_motion.sh` (cần Node.js 22+) |
| File nhạc nền | Không | Thả `.mp3` vào `data/music/` |
| GPU NVIDIA | Không, nhưng nhanh hơn nhiều | — |

Chưa cài engine nhép môi thì phần mềm **vẫn chạy**, chỉ là dùng chế độ ảnh tĩnh
zoom chậm (môi không cử động). Đủ để thử toàn bộ quy trình trước khi tải vài GB.

## Chọn engine nhép môi

```bash
bash setup_lipsync.sh              # xem so sánh
bash setup_lipsync.sh latentsync   # rồi chọn một cái
```

| Engine | Chất lượng môi | Cử động đầu | VRAM | Tải về |
|---|---|---|---|---|
| **LatentSync** | Tốt nhất | Không | ~8GB | ~5GB |
| **SadTalker** | Khá | **Có** — nhìn "sống" hơn | ~4GB | ~2GB |
| **Wav2Lip** | Tạm được | Không | ~2GB, chạy được CPU | ~500MB |
| **Veo 3.1** | Tốt | Có | 0 (gọi API) | 0 |
| **Ảnh tĩnh** | Không nhép môi | Zoom chậm | 0 | 0 |

### ⚠ Lưu ý quan trọng về Veo

Veo 3.1 dựng được video rất đẹp, nhưng **không nhận file tiếng làm đầu vào**. Nó
tự đọc lời thoại bằng giọng của chính nó. Nghĩa là khi chọn engine `veo`:

- Giọng bạn chọn ở mục "Giọng đọc" **bị bỏ qua**
- Mỗi lần gọi chỉ ra được **khoảng 8 giây**, nên video dài phải nối nhiều clip
- Giọng và khuôn mặt có thể **hơi khác nhau giữa các clip**
- Tính tiền theo giây video

Nên Veo hợp với **clip ngắn một câu punchline**. Video 60–90 giây thì đường
Gemini TTS + engine local cho kết quả nhất quán hơn hẳn, và gần như miễn phí.

## Dùng thế nào

1. Mở trang **🎬 Tạo video**
2. **Kéo ảnh vào** — ảnh chính diện, rõ mặt, đủ sáng. Phần mềm báo ngay nếu không
   dò được khuôn mặt, để bạn đổi ảnh trước khi tốn thời gian render.
3. **Gõ nội dung**. Cứ viết thoải mái — bật *Để AI biên tập lại* thì Gemini sẽ
   sửa cho dễ nói, thêm câu móc mở đầu, chia câu ngắn.
   Muốn 2 người nói qua lại thì đánh dấu `A:` và `B:` ở đầu dòng.
4. Bấm **👀 Xem trước kịch bản** — miễn phí, chưa tốn lượt đọc tiếng. Xem ưng thì
   mới chạy tiếp.
5. Chọn giọng, engine, phụ đề, nhạc nền → **🎬 Tạo video dọc 9:16**

## Vì sao phụ đề luôn khớp

Không dùng bóc lời (Whisper) cho video tự tạo. Vì đã biết trước **từng chữ sẽ
được đọc**, và Gemini TTS trả về **đúng đoạn audio của từng câu** nên biết chính
xác câu đó dài bao nhiêu giây. Chỉ cần chia thời gian trong câu theo độ dài từng
chữ (chữ dài đọc lâu hơn, chữ trước dấu phẩy có nhịp nghỉ). Cách này **không bao
giờ sai chữ** — khác hẳn bóc lời, vốn có thể nghe nhầm.

Một chi tiết dễ sai: khoảng nghỉ ngăn cách hai người nói phải nằm **trong** cảnh
trước. Bỏ sót thì tổng độ dài các cảnh ngắn hơn trục thời gian phụ đề, và phụ đề
sẽ trôi dần một nhịp sau mỗi lần đổi người.

## Thẻ đồ hoạ B-roll

Đây là loại B-roll khác hẳn stock footage: thay vì đi tìm một clip chung chung về
"tiền bạc", AI đọc lời thoại rồi dựng một thẻ mang **đúng nội dung đang được
nói** — người nói "ba khoản làm bạn hết tiền" thì thẻ liệt kê đúng ba khoản đó.

Sáu loại thẻ:

| Loại | Dùng khi |
|---|---|
| `stat` | Câu đang nói có một con số cụ thể |
| `steps` | Đang liệt kê 2–5 ý |
| `quote` | Một câu chốt đáng nhớ |
| `compare` | So sánh cách sai / cách đúng |
| `hook` | Câu móc, chỉ dùng ở 1–2 câu đầu |
| `lower_third` | Thanh giới thiệu tên và vai trò |

Thẻ nằm ở khoảng giữa khung: dưới mặt người nói, trên phụ đề. Thẻ nhiều mục mọc
**ngược lên** chứ không thò xuống, nên không bao giờ che phụ đề.

AI chỉ chèn khi thẻ thật sự làm rõ thêm điều đang nói, tối đa 4 thẻ mỗi video và
hai thẻ phải cách nhau ít nhất 6 giây. Không có key Gemini thì không chèn thẻ nào
— thà không có còn hơn chèn thẻ vô nghĩa.

### Chọn engine dựng thẻ

```bash
bash setup_motion.sh              # xem so sánh
bash setup_motion.sh hyperframes  # rồi chọn
```

| | HyperFrames | Remotion |
|---|---|---|
| Của | HeyGen | Remotion |
| Thẻ viết bằng | HTML thường | React |
| **Giấy phép** | **Apache 2.0 — miễn phí mọi quy mô** | **⚠ miễn phí cho cá nhân và công ty ≤3 người; từ 4 người phải mua license ở remotion.pro** |
| Tải về | ~150MB | ~400MB |
| Hệ sinh thái | Mới, gọn | Lớn, trưởng thành |

Cả hai cần **Node.js 22 trở lên** và cho ra thẻ nhìn giống hệt nhau (dùng chung
một bảng màu và một vùng an toàn), nên đổi engine không làm đổi diện mạo video.

**Khuyên dùng HyperFrames** vì giấy phép Apache 2.0 không có ngưỡng quy mô — bạn
tuyển thêm người cũng không phát sinh nghĩa vụ mua license. `auto` luôn ưu tiên
HyperFrames vì lý do này.

> Remotion tự tải Chromium riêng ở lần render đầu. Máy bị proxy chặn thì đặt
> `REMOTION_BROWSER=/duong/dan/chrome-headless-shell` trong `.env`.

Muốn sửa kiểu dáng thẻ: sửa `app/motion/project/assets/theme.css` (HyperFrames)
và `app/motion/remotion/src/theme.ts` (Remotion) — sửa cả hai thì hai engine mới
tiếp tục giống nhau.

## Nhạc nền

Phần mềm **không tự sinh nhạc** — nhạc sinh ra không dùng thương mại được. Thay
vào đó nó đọc file bạn bỏ vào `data/music/`, rồi nhờ Gemini chọn bài hợp tâm
trạng video dựa trên **tên file**. Nên đặt tên mô tả một chút:

```
data/music/
  upbeat-corporate-motivation.mp3
  calm-piano-storytelling.mp3
  energetic-trap-hook.mp3
```

Bật *Tự hạ nhạc khi có tiếng nói* thì nhạc tự nhỏ lại mỗi khi có lời — nghe
chuyên nghiệp hơn nhiều so với để nhạc chạy đều một mức.

## Chi phí

Với video 60 giây, đường Gemini TTS + engine local:

| Khoản | Chi phí |
|---|---|
| Biên tập kịch bản (Gemini Flash) | vài trăm đồng |
| Đọc lời thoại (Gemini TTS) | vài nghìn đồng |
| Nhép môi | **0đ** — chạy trên máy bạn |
| **Tổng** | **dưới 5 nghìn đồng/video** |

Đường Veo tốn hơn đáng kể vì tính theo giây video.

---

# Phần B — ✂️ Cắt video quay sẵn

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

**Không có API key vẫn dùng được ngay**: cắt im lặng + từ đệm + vấp + xuất 9:16 +
phụ đề đều chạy hoàn toàn offline.

### Quy trình dùng

1. **Thả video vào** — hỗ trợ MP4, MOV, MKV, WebM, AVI…
2. **Tick thứ cần cắt** — mặc định đã hợp lý. Vào *Tinh chỉnh nâng cao* nếu muốn
   siết ngưỡng im lặng hoặc thêm từ đệm của riêng bạn.
3. Bấm **Phân tích & để tôi duyệt**, hoặc **⚡ Auto** để chạy thẳng tới thành phẩm.
4. **Duyệt** 3 tab: *Đoạn cắt* (mỗi dòng có lý do, bấm để tua), *B-roll* (xem
   thumbnail + điểm khớp, sửa từ khoá rồi **Tìm lại**), *Lời thoại* (dòng bị cắt
   hiện gạch ngang).
5. **Chưa ưng ngưỡng cắt?** Kéo lại thanh trượt rồi bấm **🔄 Dò lại với cài đặt
   mới** — lời thoại đã bóc được dùng lại nên chỉ mất vài giây.

   > Lưu ý: dò lại sẽ **đặt lại** các tick bạn đã chỉnh tay.

6. **Xuất** — chọn 9:16 / tỉ lệ gốc / .srt / nướng phụ đề, rồi **Render ngay**.

### Cách hoạt động (phần đáng chú ý)

**Timeline không phải là "overlay".** Mỗi đoạn B-roll được cắt thành một clip
riêng lấy **hình từ clip stock, tiếng từ video gốc**, rồi ghép nối tiếp với các
clip A-roll. Nhờ vậy tiếng nói không bao giờ bị lệch khỏi hình dù cắt bao nhiêu chỗ.

**B-roll "đúng ngữ cảnh" đi qua 3 lớp lọc:** AI chỉ chọn câu *nhìn được* → viết
từ khoá tiếng Anh **cụ thể** (`"hands typing on laptop keyboard"`) → tải 6 ứng
viên rồi chấm điểm 0–100 độ khớp. Dưới 55 điểm thì **không tick** — thà không
chèn còn hơn chèn hình sai.

**Auto-reframe 9:16** dùng crop cố định cho từng đoạn (lấy trung vị vị trí mặt đã
làm mượt EMA) thay vì pan liên tục — ổn định, không rung.

---

# Cài đặt

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

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

Nếu vẫn lỗi, phần mềm **tự chuyển sang CPU** — không cần làm gì. Muốn ép CPU:
đặt `WHISPER_DEVICE=cpu` trong `.env`.

## Chạy

```bash
source .venv/bin/activate    # Windows: .venv\Scripts\activate
python run.py
```

Trình duyệt tự mở `http://127.0.0.1:8419`:

| Trang | Địa chỉ |
|---|---|
| ✂️ Cắt video | `http://127.0.0.1:8419/index.html` |
| 🎬 Tạo video | `http://127.0.0.1:8419/avatar.html` |

Cổng 8419 bị chiếm thì phần mềm **tự nhảy sang cổng trống khác** và in địa chỉ mới
ra terminal. Muốn cố định: đặt `PORT=8080` trong `.env`.

> Lần chạy đầu, trang Cắt video sẽ tải model Whisper (~3GB với `large-v3`). Trang
> Tạo video không cần Whisper nên dùng được ngay.

## Toàn bộ API key

| Key | Cho trang nào | Bắt buộc? | Lấy ở đâu |
|---|---|---|---|
| `GEMINI_API_KEY` | 🎬 Tạo video | **Có** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `ANTHROPIC_API_KEY` | ✂️ Cắt video | Không | [console.anthropic.com](https://console.anthropic.com) |
| `PEXELS_API_KEY` | ✂️ Cắt video | Không | [pexels.com/api/new](https://www.pexels.com/api/new/) |
| `PIXABAY_API_KEY` | ✂️ Cắt video | Không | [pixabay.com/api/docs](https://pixabay.com/api/docs/) |

---

## Cấu trúc mã nguồn

```
run.py                     khởi động server + mở trình duyệt
setup.sh                   cài đặt 1 lần
setup_lipsync.sh           tải engine nhép môi về vendor/
setup_motion.sh            cài engine dựng thẻ đồ hoạ (Node)
app/
  config.py                đường dẫn, key, tham số mặc định cho cả hai công cụ
  main.py                  các route API của FastAPI
  jobs.py                  chạy tác vụ nền + báo tiến độ
  models.py                khai báo dữ liệu vào/ra
  service.py               điều phối trang CẮT video

  avatar/                  === TẠO video người nói ===
    gemini.py              client REST: text, TTS, ảnh, Veo
    script.py              nội dung thô -> câu thoại có gán người nói
    voice.py               gọi TTS từng câu, gom thành cảnh theo người nói
    portrait.py            ảnh -> khung 1080x1920 đã canh mặt
    lipsync.py             lớp engine: latentsync / sadtalker / wav2lip / veo / still
    align.py               canh giờ phụ đề, xuất .srt và .ass
    music.py               chọn nhạc theo tâm trạng + trộn có ducking
    compose.py             chuẩn hoá cảnh -> nối -> nướng phụ đề
    service.py             điều phối toàn bộ quy trình

  motion/                  === THẺ ĐỒ HOẠ B-roll ===
    cards.py               khai báo 6 loại thẻ + kiểm tra dữ liệu AI trả về
    plan.py                AI chọn câu nào đáng chèn thẻ và thẻ ghi gì
    engine.py              gọi HyperFrames / Remotion qua dòng lệnh
    overlay.py             chồng thẻ lên video bằng một lượt ffmpeg
    service.py             điều phối: lập kế hoạch -> dựng -> chồng
    project/               template HyperFrames (HTML + GSAP)
    remotion/              template Remotion (React)

  pipeline/                === CẮT video quay sẵn ===
    ffmpeg_utils.py        gọi ffmpeg/ffprobe, đọc metadata, tách audio
    transcribe.py          Whisper, trả timestamp từng chữ
    silence.py             dò khoảng im lặng
    fillers.py             từ đệm tiếng Việt
    analyze.py             gọi Claude: vấp / lạc đề / kế hoạch B-roll / chấm điểm
    broll.py               tìm & tải clip từ Pexels, Pixabay
    reframe.py             bám mặt người nói cho khung 9:16
    timeline.py            biến danh sách cắt thành danh sách clip để render
    subtitles.py           sinh .srt đã khớp lại thời gian
    render.py              cắt từng clip -> ghép -> nướng phụ đề

  static/                  giao diện web (không dùng thư viện ngoài)
    index.html app.js      trang Cắt video
    avatar.html avatar.js  trang Tạo video
    style.css              dùng chung

data/                      video tải lên, kết quả, nhạc nền (đã .gitignore)
vendor/                    engine nhép môi tải về (đã .gitignore)
```

---

## Windows: bấm đúp là chạy

Không cần biết terminal. Bấm đúp **`CHAY_PHAN_MEM.bat`** — nó tự tạo môi trường
Python, cài thư viện, mở `.env` cho bạn dán key, rồi khởi động phần mềm.

Chưa có Python thì nó bảo bạn tải ở python.org (nhớ tích **"Add Python to PATH"**
lúc cài).

## Không chạy được? Chạy cái này trước

```bash
python doctor.py
```

Nó kiểm tra Python, môi trường ảo, thư viện, ffmpeg, file `.env`, key Gemini và
cổng mạng — rồi in ra đúng chỗ sai kèm lệnh sửa. Chỉ dùng thư viện chuẩn nên
**chạy được cả khi cài đặt đang hỏng**.

Lỗi hay gặp nhất trên Windows là quên bật môi trường ảo:
`.venv\Scripts\activate` trước khi chạy `python run.py`.

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| `CHƯA CÀI FFMPEG` | Cài ffmpeg rồi mở terminal mới |
| Tạo video báo thiếu `GEMINI_API_KEY` | Điền key vào `.env` rồi khởi động lại `python run.py` |
| Gemini báo 429 khi đọc lời thoại | Bậc miễn phí cho **3 lượt TTS/phút**, mà mỗi câu là một lượt. Phần mềm tự đọc thời gian chờ trong thông báo lỗi rồi chờ đúng, nên video dài chỉ chạy chậm chứ không hỏng. Muốn nhanh thì bật thanh toán |
| Veo báo 429 ngay lập tức | Veo **không có hạn mức nào ở bậc miễn phí** — chờ rồi thử lại vô ích. Phải bật billing cho đúng project chứa key (có credit trong tài khoản Cloud vẫn chưa đủ). Dùng engine local thay thế |
| Nhép môi ra ảnh tĩnh | Chưa cài engine nào. Chạy `bash setup_lipsync.sh latentsync` |
| Engine báo lỗi giữa chừng | Phần mềm tự lùi cảnh đó về ảnh tĩnh thay vì bỏ cả video. Xem log terminal để biết lý do |
| Nhép môi chạy quá lâu rồi dừng | Tăng `LIPSYNC_TIMEOUT` trong `.env` (mặc định 1800 giây) |
| Engine đòi thư viện xung đột | Không còn xảy ra: `setup_lipsync.sh` tự tạo venv riêng cho từng engine, phần mềm tự tìm. Bắt buộc phải vậy vì LatentSync ghim `opencv-python==4.9.0.80`, SadTalker ghim `numpy==1.23.4`, Wav2Lip ghim `numpy==1.17.1` + `torch==1.1.0` — cài chung là hỏng phần dò mặt |
| Ảnh báo "không thấy mặt" | Dùng ảnh chính diện, mặt chiếm ít nhất 1/5 khung, đủ sáng, không đeo kính râm |
| Không có nhạc nền | Thư mục `data/music/` đang trống. Thả file `.mp3` vào |
| Không thấy thẻ đồ hoạ nào | Cần **cả** `GEMINI_API_KEY` lẫn một engine đã cài. Thiếu một trong hai là không có thẻ |
| AI không chèn thẻ nào | Bình thường nếu lời thoại không có số liệu / danh sách / câu chốt. Thẻ chỉ chèn khi thật sự làm rõ thêm ý |
| Thẻ dựng lỗi giữa chừng | Thẻ đó bị bỏ, các thẻ còn lại vẫn giữ. Xem log terminal để biết lý do |
| Remotion không tải được Chromium | Đặt `REMOTION_BROWSER` trong `.env` trỏ vào chrome-headless-shell có sẵn |
| `setup_motion.sh` báo cần Node 22 | Cài Node.js mới ở https://nodejs.org |
| Whisper báo lỗi CUDA / cuDNN | `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`, hoặc đặt `WHISPER_DEVICE=cpu` |
| Render lỗi codec | Đặt `USE_NVENC=0` trong `.env` để dùng CPU (libx264) |
| Tab B-roll trống | Cần **cả** `ANTHROPIC_API_KEY` lẫn key stock |
| Máy hết dung lượng | Xoá `data/jobs/` và `data/broll_cache/` |
| Không vào được địa chỉ trong terminal | Dùng đúng địa chỉ terminal in ra — cổng bị chiếm thì phần mềm đã tự đổi sang cổng khác. Dùng `127.0.0.1` chứ đừng dùng `localhost` nếu máy có cấu hình DNS lạ |

---

## Bản quyền

**B-roll** từ Pexels và Pixabay dùng được cho mục đích thương mại, không bắt buộc
ghi nguồn. Phần mềm vẫn lưu tên tác giả và link gốc trong `project.json`.

**Ảnh chân dung**: chỉ dùng ảnh của chính bạn, hoặc ảnh bạn có quyền sử dụng và
đã được người trong ảnh đồng ý. Tạo video người khác nói những điều họ không nói
là hành vi có thể vi phạm pháp luật.

**Engine nhép môi** (LatentSync, SadTalker, Wav2Lip) có giấy phép riêng của từng
tác giả — đọc kỹ trước khi dùng thương mại. Đó cũng là lý do chúng không được
đóng gói kèm mà phải tải riêng.

**Engine dựng thẻ đồ hoạ**: HyperFrames dùng giấy phép Apache 2.0, miễn phí cho
mọi quy mô kể cả thương mại. **Remotion thì khác**: chỉ miễn phí cho cá nhân và
công ty có tối đa 3 người; công ty từ 4 người trở lên bắt buộc mua Company
License tại [remotion.pro](https://remotion.pro). Điều khoản đầy đủ ở
[LICENSE.md của Remotion](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md).
Nếu bạn có kế hoạch mở rộng đội ngũ, chọn HyperFrames là gọn nhất.

**Nhạc nền**: bạn tự chịu trách nhiệm về bản quyền các file bỏ vào `data/music/`.
