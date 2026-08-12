/* Giao diện tạo video người nói. Không dùng thư viện ngoài. */

const $ = (id) => document.getElementById(id);

const state = {
  photos: [],        // [{photo_id, url, face_found, warning}]
  options: null,
  jobId: null,
  poller: null,
};

// ---------------------------------------------------------------------------
// Tiện ích
// ---------------------------------------------------------------------------

function toast(message, kind = "") {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 3500);
}

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }
  if (!resp.ok) throw new Error(data?.detail || `Lỗi ${resp.status}`);
  return data;
}

function fmtTime(seconds) {
  const s = Math.max(seconds || 0, 0);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Nạp cấu hình ban đầu
// ---------------------------------------------------------------------------

async function loadOptions() {
  const [status, options] = await Promise.all([
    api("/api/status"),
    api("/api/avatar/options"),
  ]);
  state.options = options;

  const caps = [
    ["ffmpeg", status.ffmpeg, "ffmpeg"],
    ["Gemini", options.gemini, "Gemini"],
    ["GPU", status.nvenc, "GPU"],
  ];
  $("caps").innerHTML = caps
    .map(([label, on]) => `<span class="cap ${on ? "on" : "off"}">${label}${on ? " ✓" : " ✗"}</span>`)
    .join("");

  if (!options.gemini) {
    toast("Chưa có GEMINI_API_KEY trong file .env — chưa tạo được giọng đọc.", "err");
  }

  // Giọng điệu
  $("style").innerHTML = options.styles
    .map((s) => `<option value="${s.id}">${s.label}</option>`)
    .join("");

  // Voice
  const voiceHtml = options.voices
    .map((v) => `<option value="${v.id}">${v.label}</option>`)
    .join("");
  $("voice-a").innerHTML = voiceHtml;
  $("voice-b").innerHTML = voiceHtml;
  $("voice-a").value = options.defaults.voice_a;
  $("voice-b").value = options.defaults.voice_b;

  // Engine dựng thẻ đồ hoạ
  $("motion-engine").innerHTML =
    `<option value="auto">Tự chọn (đang là: ${options.motion_active})</option>` +
    (options.motion_engines || [])
      .map((e) => `<option value="${e.id}">${e.ready || e.id === "off" ? "" : "⚠ "}${e.label}</option>`)
      .join("");
  updateMotionNote();

  // Engine
  $("engine").innerHTML =
    `<option value="auto">Tự chọn (đang là: ${options.engine_active})</option>` +
    options.engines
      .map((e) => `<option value="${e.id}" ${e.ready ? "" : "data-missing=1"}>${e.ready ? "" : "⚠ "}${e.label}</option>`)
      .join("");
  updateEngineNote();

  renderMusicList();
}

function renderMusicList() {
  const tracks = state.options.music || [];
  $("music-file").innerHTML =
    `<option value="">Tự chọn theo nội dung</option>` +
    tracks.map((m) => `<option value="${m.name}">${m.label}</option>`).join("");

  $("music-hint").textContent = tracks.length
    ? `${tracks.length} bài trong data/music/`
    : "Thư mục data/music/ đang trống — chưa có nhạc để chèn.";
}

function updateMotionNote() {
  const value = $("motion-engine").value;
  const found = (state.options.motion_engines || []).find((e) => e.id === value);
  const note = $("motion-note");
  const types = (state.options.motion_cards || [])
    .map((c) => `<span class="card-chip">${c.id}</span>`)
    .join("");

  if (value === "off") {
    note.innerHTML = "Không chèn thẻ nào.";
    return;
  }
  if (found && !found.ready) {
    note.innerHTML = `⚠ Chưa cài. Chạy: <code>${found.hint}</code>`;
    return;
  }

  // Giấy phép Remotion là thứ người dùng phải biết TRƯỚC khi chọn, không phải
  // sau khi đã dựng xong cả video.
  const license =
    value === "remotion" || (value === "auto" && state.options.motion_active === "remotion")
      ? `<span class="license-warn">⚠ Remotion chỉ miễn phí cho cá nhân và công ty tối đa 3 người.
         Công ty từ 4 người trở lên phải mua license ở remotion.pro.
         Muốn tránh hẳn chuyện này thì dùng HyperFrames (Apache 2.0).</span>`
      : "";

  note.innerHTML = `Các loại thẻ AI được phép dùng: ${types}${license}`;
}

function updateEngineNote() {
  const value = $("engine").value;
  const found = (state.options.engines || []).find((e) => e.id === value);
  const note = $("engine-note");

  if (value === "auto") {
    note.innerHTML = `Sẽ dùng <b>${state.options.engine_active}</b>. Cài thêm engine để nét hơn: <code>bash setup_lipsync.sh latentsync</code>`;
  } else if (value === "veo") {
    note.innerHTML =
      "⚠ Veo <b>tự đọc lời thoại bằng giọng của nó</b>, không dùng giọng bạn chọn ở trên, " +
      "và mỗi câu chỉ ra được ~8 giây. Hợp với clip ngắn, không hợp video dài.";
  } else if (found && !found.ready) {
    note.innerHTML = `⚠ Chưa cài. Chạy: <code>${found.hint}</code>`;
  } else if (value === "still") {
    note.textContent = "Chỉ zoom chậm ảnh tĩnh, môi không cử động. Dùng khi chưa cài engine nào.";
  } else {
    note.textContent = "Nhép môi theo đúng giọng đọc Gemini TTS đã tạo.";
  }
}

// ---------------------------------------------------------------------------
// Ảnh
// ---------------------------------------------------------------------------

async function uploadPhotos(files) {
  const room = 2 - state.photos.length;
  if (room <= 0) return toast("Tối đa 2 người thôi.", "err");

  for (const file of Array.from(files).slice(0, room)) {
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await api("/api/avatar/photos", { method: "POST", body: form });
      state.photos.push({ ...result, url: URL.createObjectURL(file) });
      if (result.warning) toast(result.warning, "err");
    } catch (exc) {
      toast(exc.message, "err");
    }
  }
  renderPhotos();
}

function renderPhotos() {
  $("photos").innerHTML = state.photos
    .map((p, i) => `
      <div class="photo">
        <span class="tag ${i === 1 ? "b" : ""}">Người ${i + 1}</span>
        <button class="drop-x" data-remove="${i}" title="Bỏ ảnh này">×</button>
        <img src="${p.url}" alt="Người ${i + 1}">
        <div class="note ${p.face_found ? "ok" : ""}">
          ${p.face_found ? "✓ Thấy mặt" : "⚠ Không thấy mặt"}
        </div>
      </div>`)
    .join("");

  $("photos").querySelectorAll("[data-remove]").forEach((btn) => {
    btn.onclick = () => {
      state.photos.splice(Number(btn.dataset.remove), 1);
      renderPhotos();
    };
  });

  const two = state.photos.length >= 2;
  $("voice-b").disabled = !two;
  $("photo-drop").classList.toggle("hidden", state.photos.length >= 2);
}

// ---------------------------------------------------------------------------
// Thu thập cài đặt
// ---------------------------------------------------------------------------

function collectSettings() {
  return {
    rewrite_script: $("rewrite").checked,
    style: $("style").value,
    max_seconds: Number($("max-seconds").value) || 90,
    voice_a: $("voice-a").value,
    voice_b: $("voice-b").value,
    segment_gap: Number($("gap").value),
    engine: $("engine").value,
    background: $("background").value,
    background_color: $("background-color").value,
    motion: $("motion").checked,
    motion_engine: $("motion-engine").value,
    motion_max_cards: Number($("motion-max").value),
    subtitles: $("subtitles").checked,
    subtitle_size: Number($("sub-size").value),
    subtitle_max_chars: Number($("sub-chars").value),
    music: $("music").checked,
    music_file: $("music-file").value,
    music_gain_db: Number($("music-gain").value),
    music_duck: $("music-duck").checked,
  };
}

// ---------------------------------------------------------------------------
// Xem trước kịch bản
// ---------------------------------------------------------------------------

async function previewScript() {
  const content = $("content").value.trim();
  if (!content) return toast("Chưa nhập nội dung.", "err");

  const btn = $("btn-preview");
  btn.disabled = true;
  btn.textContent = "Đang biên tập…";

  try {
    const plan = await api("/api/avatar/script", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        speakers: Math.max(state.photos.length, 1),
        avatar: collectSettings(),
      }),
    });
    renderScript(plan);
  } catch (exc) {
    toast(exc.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "👀 Xem trước kịch bản";
  }
}

function renderScript(plan) {
  const box = $("script-preview");
  box.classList.remove("hidden");

  const head = `
    <p class="muted small">
      ${plan.title ? `<b>${plan.title}</b> · ` : ""}
      ${plan.segments.length} câu · khoảng ${plan.estimated_seconds}s
      ${plan.music_mood ? ` · nhạc gợi ý: ${plan.music_mood}` : ""}
    </p>`;

  const rows = plan.segments
    .map((s) => `
      <div class="seg sp${s.speaker}">
        <span class="who">${s.speaker === 2 ? "B" : "A"}</span>
        <span class="txt">${s.text}</span>
      </div>`)
    .join("");

  box.innerHTML = head + rows;
}

// ---------------------------------------------------------------------------
// Tạo video
// ---------------------------------------------------------------------------

async function generate() {
  if (!state.photos.length) return toast("Chưa có ảnh nào.", "err");
  const content = $("content").value.trim();
  if (!content) return toast("Chưa nhập nội dung.", "err");

  $("btn-generate").disabled = true;
  $("result-card").classList.add("hidden");
  $("progress-card").classList.remove("hidden");
  $("bar").style.width = "2%";
  $("stage").textContent = "Bắt đầu";
  $("progress-msg").textContent = "";

  try {
    const { job_id } = await api("/api/avatar/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        photo_ids: state.photos.map((p) => p.photo_id),
        content,
        avatar: collectSettings(),
        render: { crf: 20, audio_bitrate: "192k" },
      }),
    });
    state.jobId = job_id;
    poll();
  } catch (exc) {
    toast(exc.message, "err");
    $("btn-generate").disabled = false;
    $("progress-card").classList.add("hidden");
  }
}

function poll() {
  clearInterval(state.poller);
  state.poller = setInterval(async () => {
    let job;
    try {
      job = await api(`/api/jobs/${state.jobId}`);
    } catch {
      return; // mạng chớp nhoáng, để lần sau
    }

    $("bar").style.width = `${Math.round((job.progress || 0) * 100)}%`;
    $("stage").textContent = job.stage || "Đang chạy";
    $("progress-msg").textContent = job.message || "";

    if (job.status === "done") {
      clearInterval(state.poller);
      $("btn-generate").disabled = false;
      $("progress-card").classList.add("hidden");
      showResult(job.result);
    } else if (job.status === "error") {
      clearInterval(state.poller);
      $("btn-generate").disabled = false;
      $("progress-card").classList.add("hidden");
      toast(job.error || "Có lỗi xảy ra.", "err");
    }
  }, 1200);
}

// ---------------------------------------------------------------------------
// Kết quả
// ---------------------------------------------------------------------------

async function showResult(result) {
  const card = $("result-card");
  card.classList.remove("hidden");

  const base = `/api/projects/${result.project_id}/output`;
  $("result-video").src = `${base}/${result.video}`;

  $("result-stats").innerHTML = [
    ["Thời lượng", fmtTime(result.duration)],
    ["Số câu", result.segments],
    ["Nhép môi", result.engine],
    ["Thẻ đồ hoạ", result.motion_cards || 0],
    ["Nhạc nền", result.music || "không"],
  ]
    .map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`)
    .join("");

  $("result-links").innerHTML = `
    <a href="${base}/${result.video}" download>⬇ Tải video 9:16</a>
    <a href="${base}/${result.srt}" download>⬇ Tải phụ đề .srt</a>`;

  try {
    const project = await api(`/api/avatar/projects/${result.project_id}`);
    $("sub-list").innerHTML = (project.subtitle_lines || [])
      .map((l) => `
        <div class="line-item" data-at="${l.start}">
          <span class="t">${fmtTime(l.start)}</span>${l.text}
        </div>`)
      .join("");

    $("sub-list").querySelectorAll("[data-at]").forEach((row) => {
      row.onclick = () => {
        const video = $("result-video");
        video.currentTime = Number(row.dataset.at);
        video.play();
      };
    });
  } catch {
    $("sub-list").innerHTML = `<p class="muted small">Không tải được danh sách phụ đề.</p>`;
  }

  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------------------
// Gắn sự kiện
// ---------------------------------------------------------------------------

function bind() {
  const drop = $("photo-drop");
  drop.onclick = () => $("photo-input").click();
  $("photo-input").onchange = (e) => {
    uploadPhotos(e.target.files);
    e.target.value = "";
  };

  ["dragenter", "dragover"].forEach((type) =>
    drop.addEventListener(type, (e) => {
      e.preventDefault();
      drop.classList.add("over");
    })
  );
  ["dragleave", "drop"].forEach((type) =>
    drop.addEventListener(type, (e) => {
      e.preventDefault();
      drop.classList.remove("over");
    })
  );
  drop.addEventListener("drop", (e) => uploadPhotos(e.dataTransfer.files));

  $("content").addEventListener("input", () => {
    const words = $("content").value.trim().split(/\s+/).filter(Boolean).length;
    const seconds = Math.round(words / 4.5);
    const target = Number($("max-seconds").value) || 90;
    const el = $("counter");
    el.textContent = `${words} chữ · ~${seconds} giây`;
    el.classList.toggle("over", seconds > target * 1.3);
  });

  $("engine").onchange = updateEngineNote;
  $("motion-engine").onchange = updateMotionNote;
  $("motion").onchange = () => {
    const on = $("motion").checked;
    $("motion-tune").style.opacity = on ? "" : ".45";
    $("motion-tune").style.pointerEvents = on ? "" : "none";
  };
  $("background").onchange = () => {
    $("bg-color-wrap").style.display = $("background").value === "solid" ? "" : "none";
  };

  [["sub-size", "sub-size-out"], ["sub-chars", "sub-chars-out"],
   ["music-gain", "music-gain-out"], ["gap", "gap-out"],
   ["motion-max", "motion-max-out"]].forEach(([input, out]) => {
    $(input).addEventListener("input", () => ($(out).textContent = $(input).value));
  });

  $("btn-music-upload").onclick = () => $("music-input").click();
  $("music-input").onchange = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;

    const form = new FormData();
    form.append("file", file);
    try {
      const saved = await api("/api/avatar/music", { method: "POST", body: form });
      state.options.music = (await api("/api/avatar/options")).music;
      renderMusicList();
      $("music-file").value = saved.name;
      toast(`Đã thêm nhạc: ${saved.name}`, "ok");
    } catch (exc) {
      toast(exc.message, "err");
    }
  };

  $("btn-preview").onclick = previewScript;
  $("btn-generate").onclick = generate;
}

bind();
loadOptions().catch((exc) => toast(`Không nạp được cấu hình: ${exc.message}`, "err"));
