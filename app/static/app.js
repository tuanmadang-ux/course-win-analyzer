/* Trợ lý cắt video — giao diện. Không dùng thư viện ngoài. */

const $ = (id) => document.getElementById(id);

const state = {
  caps: {},
  uploadId: null,
  probe: null,
  projectId: null,
  project: null,
  cuts: [],
  brolls: [],
  autoMode: false,
};

const KIND_LABEL = {
  silence: 'Im lặng',
  filler: 'Từ đệm',
  badtake: 'Vấp / nói lại',
  offtopic: 'Lạc đề',
};

/* ---------------------------------------------------------- tiện ích --- */

function toast(msg, type = '') {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast ' + type;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), 5200);
}

function fmt(t) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60);
  const s = t % 60;
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

function show(id) { $(id).classList.remove('hidden'); }
function hide(id) { $(id).classList.add('hidden'); }

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Lỗi ${res.status}`);
  return data;
}

/* ------------------------------------------------------- khởi động --- */

async function init() {
  try {
    state.caps = await api('/api/status');
  } catch {
    state.caps = {};
  }
  const c = state.caps;
  $('capabilities').innerHTML = [
    cap('ffmpeg', c.ffmpeg),
    cap(c.nvenc ? 'GPU NVENC' : 'CPU render', true),
    cap(c.claude ? `Claude (${c.model})` : 'Chưa có Claude key', c.claude),
    cap(c.stock ? 'Kho B-roll' : 'Chưa có key B-roll', c.stock),
  ].join('');

  if (!c.claude) {
    $('wrap-offtopic').classList.add('disabled');
    $('opt-offtopic').checked = false;
  }
  if (!c.stock || !c.claude) {
    $('wrap-broll').classList.add('disabled');
    $('opt-broll').checked = false;
  }

  bindUpload();
  bindTunes();
  bindTabs();

  $('btn-analyze').onclick = () => startAnalysis(false);
  $('btn-auto').onclick = () => startAnalysis(true);
  $('btn-render').onclick = () => startRender();
  $('btn-toggle-all').onclick = toggleAllCuts;
}

function cap(label, ok) {
  return `<span class="cap ${ok ? 'on' : 'off'}">${ok ? '✓' : '·'} ${label}</span>`;
}

/* ---------------------------------------------------------- upload --- */

function bindUpload() {
  const dz = $('dropzone');
  const input = $('file-input');

  dz.onclick = () => input.click();
  input.onchange = () => input.files[0] && uploadFile(input.files[0]);

  ['dragenter', 'dragover'].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('over'); }));
  dz.addEventListener('drop', (e) => {
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
}

function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);

  show('upload-progress');
  $('upload-label').textContent = `Đang tải lên ${file.name}…`;

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload');
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      $('upload-bar').style.width = `${(e.loaded / e.total) * 100}%`;
    }
  };
  xhr.onload = () => {
    const data = JSON.parse(xhr.responseText || '{}');
    if (xhr.status !== 200) {
      hide('upload-progress');
      return toast(data.detail || 'Tải lên thất bại', 'err');
    }
    state.uploadId = data.upload_id;
    state.probe = data.probe;
    hide('upload-progress');

    const p = data.probe;
    $('video-info').innerHTML = `
      <span><b>${data.filename}</b></span>
      <span>Dài <b>${fmt(p.duration)}</b></span>
      <span>${p.width}×${p.height}</span>
      <span>${p.fps.toFixed(1)} fps</span>
      <span>${p.has_audio ? 'có tiếng' : '⚠ không có tiếng'}</span>`;
    show('video-info');
    show('step-settings');
    $('step-settings').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
  xhr.onerror = () => { hide('upload-progress'); toast('Mất kết nối khi tải lên', 'err'); };
  xhr.send(form);
}

/* --------------------------------------------------------- cài đặt --- */

function bindTunes() {
  const pairs = [
    ['tune-db', 'out-db'], ['tune-mindur', 'out-mindur'], ['tune-pad', 'out-pad'],
    ['tune-broll', 'out-broll'], ['tune-brolllen', 'out-brolllen'],
  ];
  pairs.forEach(([a, b]) => {
    const inp = $(a);
    const out = $(b);
    out.textContent = inp.value;
    inp.oninput = () => { out.textContent = inp.value; };
  });
}

function cutSettings() {
  const extra = $('tune-fillers').value
    .split(',').map((s) => s.trim()).filter(Boolean);
  return {
    detect_silence: $('opt-silence').checked,
    detect_fillers: $('opt-fillers').checked,
    detect_badtakes: $('opt-badtakes').checked,
    detect_offtopic: $('opt-offtopic').checked,
    silence_db: parseFloat($('tune-db').value),
    silence_min_dur: parseFloat($('tune-mindur').value),
    silence_keep_pad: parseFloat($('tune-pad').value),
    extra_fillers: extra,
  };
}

function brollSettings() {
  return {
    enabled: $('opt-broll').checked,
    max_clips: parseInt($('tune-broll').value, 10),
    clip_len: parseFloat($('tune-brolllen').value),
  };
}

function renderSettings() {
  return {
    vertical: $('out-vertical').checked,
    keep_original_ratio: $('out-original').checked,
    export_srt: $('out-srt').checked,
    burn_subtitles: $('out-burn').checked,
  };
}

/* -------------------------------------------------------- phân tích --- */

async function startAnalysis(auto) {
  if (!state.uploadId) return toast('Chưa chọn video', 'err');
  state.autoMode = auto;

  $('btn-analyze').disabled = true;
  $('btn-auto').disabled = true;
  $('progress-title').textContent = auto ? 'Chế độ Auto — đang phân tích…' : 'Đang phân tích…';
  show('step-progress');
  hide('step-review');
  hide('step-export');
  $('step-progress').scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const { job_id } = await api('/api/analyze', {
      method: 'POST',
      body: JSON.stringify({
        upload_id: state.uploadId,
        language: 'vi',
        cut: cutSettings(),
        broll: brollSettings(),
      }),
    });
    const job = await pollJob(job_id);
    state.projectId = job.result.project_id;
    await loadProject();

    hide('step-progress');
    show('step-review');
    show('step-export');

    if (auto) {
      startRender();
    } else {
      $('step-review').scrollIntoView({ behavior: 'smooth', block: 'start' });
      toast('Phân tích xong — hãy duyệt lại rồi bấm Render.', 'ok');
    }
  } catch (err) {
    hide('step-progress');
    toast(err.message, 'err');
  } finally {
    $('btn-analyze').disabled = false;
    $('btn-auto').disabled = false;
  }
}

function pollJob(jobId) {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      let job;
      try {
        job = await api(`/api/jobs/${jobId}`);
      } catch (e) {
        return reject(e);
      }
      $('job-bar').style.width = `${(job.progress * 100).toFixed(1)}%`;
      $('job-stage').textContent = job.stage || '';
      $('job-message').textContent = job.message || '';

      if (job.status === 'done') return resolve(job);
      if (job.status === 'error') return reject(new Error(job.error || 'Tác vụ thất bại'));
      setTimeout(tick, 900);
    };
    tick();
  });
}

/* ---------------------------------------------------------- duyệt --- */

async function loadProject() {
  const p = await api(`/api/projects/${state.projectId}`);
  state.project = p;
  state.cuts = p.cuts || [];
  state.brolls = p.brolls || [];

  $('player').src = `/api/projects/${state.projectId}/video`;
  renderSummary();
  renderTimeline();
  renderCuts();
  renderBrolls();
  renderScript();
}

function renderSummary() {
  const s = state.project.stats || {};
  const topic = state.project.topic;
  const removed = s.removed || 0;
  const pct = s.duration ? ((removed / s.duration) * 100).toFixed(0) : 0;

  $('summary').innerHTML = `
    <div class="stat"><div class="k">Gốc</div><div class="v">${fmt(s.duration)}</div></div>
    <div class="stat good"><div class="k">Sau khi cắt</div><div class="v" id="stat-out">${fmt(s.output_duration)}</div></div>
    <div class="stat"><div class="k">Bỏ đi</div><div class="v" id="stat-removed">${fmt(removed)} · ${pct}%</div></div>
    <div class="stat"><div class="k">Đề xuất cắt</div><div class="v">${s.cut_count || 0}</div></div>
    <div class="stat"><div class="k">B-roll</div><div class="v">${s.broll_count || 0}</div></div>
    ${topic ? `<div class="stat" style="flex:1;min-width:240px"><div class="k">Chủ đề</div><div class="v" style="font-size:14px;font-weight:500">${escapeHtml(topic)}</div></div>` : ''}`;
}

function recomputeStats() {
  const dur = state.project.probe.duration;
  let removed = 0;
  state.cuts.forEach((c) => { if (c.enabled) removed += c.end - c.start; });
  const out = Math.max(0, dur - removed);
  const pct = dur ? ((removed / dur) * 100).toFixed(0) : 0;
  const so = $('stat-out'); const sr = $('stat-removed');
  if (so) so.textContent = fmt(out);
  if (sr) sr.textContent = `${fmt(removed)} · ${pct}%`;
}

function renderTimeline() {
  const dur = state.project.probe.duration || 1;
  const tl = $('timeline');
  tl.innerHTML = '';
  state.cuts.forEach((c, i) => {
    const el = document.createElement('div');
    el.className = 'tl-cut' + (c.enabled ? '' : ' off');
    el.style.left = `${(c.start / dur) * 100}%`;
    el.style.width = `${Math.max(((c.end - c.start) / dur) * 100, 0.15)}%`;
    el.dataset.cut = i;
    el.title = `${KIND_LABEL[c.kind]} · ${fmt(c.start)}`;
    tl.appendChild(el);
  });
  state.brolls.forEach((b) => {
    if (!b.enabled) return;
    const el = document.createElement('div');
    el.className = 'tl-broll';
    el.style.left = `${(b.start / dur) * 100}%`;
    el.style.width = `${Math.max(((b.end - b.start) / dur) * 100, 0.3)}%`;
    el.title = `B-roll: ${b.query}`;
    tl.appendChild(el);
  });
  tl.onclick = (e) => {
    const rect = tl.getBoundingClientRect();
    seek(((e.clientX - rect.left) / rect.width) * dur);
  };
}

function activeKinds() {
  return new Set([...document.querySelectorAll('.kind-filter')]
    .filter((c) => c.checked).map((c) => c.dataset.kind));
}

function renderCuts() {
  const kinds = activeKinds();
  const box = $('tab-cuts');
  box.innerHTML = '';
  let shown = 0;

  state.cuts.forEach((c, i) => {
    if (!kinds.has(c.kind)) return;
    shown++;
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `
      <input type="checkbox" ${c.enabled ? 'checked' : ''}>
      <div class="body">
        <div class="head">
          <span class="pill ${c.kind}">${KIND_LABEL[c.kind]}</span>
          <span class="time">${fmt(c.start)} → ${fmt(c.end)}</span>
          <span class="muted small">(${(c.end - c.start).toFixed(2)}s)</span>
        </div>
        <div class="reason">${escapeHtml(c.reason || '')}</div>
        ${c.text ? `<div class="quote">“${escapeHtml(c.text)}”</div>` : ''}
      </div>`;
    row.querySelector('input').onchange = (e) => {
      state.cuts[i].enabled = e.target.checked;
      renderTimeline();
      recomputeStats();
      renderScript();
    };
    row.querySelector('.body').onclick = () => seek(c.start - 0.6);
    box.appendChild(row);
  });

  if (!shown) box.innerHTML = '<p class="muted">Không có đề xuất nào ở bộ lọc này.</p>';
  $('count-cuts').textContent = state.cuts.length;

  document.querySelectorAll('.kind-filter').forEach((cb) => { cb.onchange = renderCuts; });
}

function toggleAllCuts() {
  const anyOn = state.cuts.some((c) => c.enabled);
  state.cuts.forEach((c) => { c.enabled = !anyOn; });
  $('btn-toggle-all').textContent = anyOn ? 'Tick tất cả' : 'Bỏ tick tất cả';
  renderCuts();
  renderTimeline();
  recomputeStats();
  renderScript();
}

function renderBrolls() {
  const box = $('tab-brolls');
  box.innerHTML = '';
  $('count-brolls').textContent = state.brolls.length;

  if (!state.brolls.length) {
    box.innerHTML = `<p class="muted">Chưa có B-roll.
      ${state.caps.stock && state.caps.claude ? 'AI không tìm được vị trí phù hợp trong video này.'
        : 'Cần cả ANTHROPIC_API_KEY và PEXELS_API_KEY (hoặc PIXABAY_API_KEY) trong file .env.'}</p>`;
    return;
  }

  state.brolls.forEach((b, i) => {
    const card = document.createElement('div');
    card.className = 'broll';
    const thumb = b.thumb ? `/api/projects/${state.projectId}/media/${b.thumb}` : '';
    const scoreCls = b.score >= 70 ? 'hi' : (b.score >= 55 ? '' : 'lo');
    card.innerHTML = `
      ${thumb ? `<img src="${thumb}" alt="">` : '<div style="width:116px"></div>'}
      <div class="meta">
        <div class="q">
          <input type="checkbox" ${b.enabled ? 'checked' : ''} style="accent-color:#35c98b">
          ${escapeHtml(b.query_vi || b.query)}
          <span class="score ${scoreCls}">· khớp ${b.score}/100</span>
        </div>
        <div class="why">${escapeHtml(b.reason || '')}</div>
        <div class="line" title="${escapeHtml(b.line || '')}">🎙 “${escapeHtml(b.line || '')}”</div>
        <div class="tools">
          <input type="text" value="${escapeHtml(b.query)}" placeholder="từ khoá tiếng Anh">
          <button>Tìm lại</button>
          <span class="muted small">${fmt(b.start)}</span>
        </div>
      </div>`;

    card.querySelector('input[type=checkbox]').onchange = (e) => {
      state.brolls[i].enabled = e.target.checked;
      renderTimeline();
    };
    card.querySelector('.line').onclick = () => seek(b.start - 0.5);

    const queryInput = card.querySelector('input[type=text]');
    const btn = card.querySelector('button');
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = '…';
      try {
        const updated = await api(
          `/api/projects/${state.projectId}/brolls/${b.id}/search`,
          { method: 'POST', body: JSON.stringify({ query: queryInput.value, line: b.line || '' }) },
        );
        state.brolls[i] = { ...state.brolls[i], ...updated };
        renderBrolls();
        renderTimeline();
        toast('Đã đổi B-roll.', 'ok');
      } catch (err) {
        toast(err.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Tìm lại';
      }
    };
    box.appendChild(card);
  });
}

function renderScript() {
  const box = $('tab-script');
  const segs = (state.project.transcript || {}).segments || [];
  const cuts = state.cuts.filter((c) => c.enabled);

  box.innerHTML = segs.map((s) => {
    const mid = (s.start + s.end) / 2;
    const isCut = cuts.some((c) => mid >= c.start && mid <= c.end);
    return `<div class="line-item ${isCut ? 'cut' : ''}" data-t="${s.start}">
      <span class="t">${fmt(s.start)}</span>${escapeHtml(s.text || '')}</div>`;
  }).join('') || '<p class="muted">Không bóc được lời nói nào.</p>';

  box.querySelectorAll('.line-item').forEach((el) => {
    el.onclick = () => seek(parseFloat(el.dataset.t));
  });
}

function seek(t) {
  const v = $('player');
  if (!v.src) return;
  v.currentTime = Math.max(0, t);
  v.play().catch(() => {});
}

function bindTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      ['cuts', 'brolls', 'script'].forEach((name) => {
        $(`tab-${name}`).classList.toggle('hidden', name !== tab.dataset.tab);
      });
      $('cut-filters').classList.toggle('hidden', tab.dataset.tab !== 'cuts');
    };
  });
}

/* ---------------------------------------------------------- render --- */

async function startRender() {
  if (!state.projectId) return toast('Chưa có dự án nào', 'err');
  const rs = renderSettings();
  if (!rs.vertical && !rs.keep_original_ratio) {
    return toast('Chọn ít nhất một định dạng xuất (9:16 hoặc tỉ lệ gốc).', 'err');
  }

  $('btn-render').disabled = true;
  hide('outputs');
  $('progress-title').textContent = 'Đang render…';
  $('job-bar').style.width = '0%';
  show('step-progress');
  $('step-progress').scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const { job_id } = await api('/api/render', {
      method: 'POST',
      body: JSON.stringify({
        project_id: state.projectId,
        cuts: state.cuts,
        brolls: state.brolls.map((b) => ({ id: b.id, enabled: b.enabled })),
        cut: cutSettings(),
        render: rs,
      }),
    });
    const job = await pollJob(job_id);
    hide('step-progress');
    showOutputs(job.result);
    toast('Xong! Bấm để tải video về.', 'ok');
  } catch (err) {
    hide('step-progress');
    toast(err.message, 'err');
  } finally {
    $('btn-render').disabled = false;
  }
}

function showOutputs(result) {
  const labels = { vertical: '⬇️ Bản dọc 9:16', original: '⬇️ Bản tỉ lệ gốc', srt: '⬇️ Phụ đề .srt' };
  const box = $('outputs');
  box.innerHTML = `<p class="muted small" style="width:100%;margin:0 0 6px">
      Thành phẩm dài ${fmt(result.output_duration)} · ghép từ ${result.clip_count} đoạn.</p>`
    + Object.entries(result.outputs || {}).map(([k, name]) =>
      `<a href="/api/projects/${state.projectId}/output/${encodeURIComponent(name)}" download>
        ${labels[k] || k}</a>`).join('');
  show('outputs');
  $('step-export').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ------------------------------------------------------------ misc --- */

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (m) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

init();
