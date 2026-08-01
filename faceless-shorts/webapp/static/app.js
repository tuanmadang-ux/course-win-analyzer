'use strict';

const $ = (sel) => document.querySelector(sel);
const TRACKS = { tsx: 'TSX', ai: 'AI video', vox: 'Collage' };

let shots = [];
let filter = 'all';
let poll = null;
// "<shot>:<kind>" của các tác vụ đang chạy — dùng để khoá nút, tránh hai tiến
// trình render cùng ghi một file (server cũng chặn, đây là lớp thứ hai).
let busy = new Set();

const api = async (url, opts) => {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Lỗi ${res.status}`);
  }
  return res.json();
};

const post = (url, body) =>
  api(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const mb = (n) => (n / 1048576).toFixed(1) + ' MB';

// ------------------------------------------------------------------ status

async function loadStatus() {
  let s;
  try {
    s = await api('/api/status');
  } catch {
    return;
  }
  const pill = (ok, label) => `<span class="pill ${ok ? 'ok' : 'bad'}">${ok ? '✓' : '✗'} ${label}</span>`;
  $('#status').innerHTML =
    pill(s.node, 'node') +
    pill(s.ffmpeg, 'ffmpeg') +
    pill(s.deps, 'thư viện') +
    `<span class="pill">${s.shots} composition</span>`;

  const problems = [];
  if (!s.node) problems.push('Chưa có <code>node</code> trên PATH — cài Node 18+.');
  if (!s.ffmpeg) problems.push('Chưa có <code>ffmpeg</code>/<code>ffprobe</code> — không xuất được video.');
  if (!s.deps) problems.push('Chưa cài thư viện Remotion — chạy <code>bash setup.sh</code>.');
  if (s.browser_auto)
    problems.push(
      'Không thấy Chrome/Chromium cài sẵn. Remotion sẽ tự tải khi render lần đầu (~150MB). ' +
        'Máy chặn mạng thì đặt <code>REMOTION_BROWSER_EXECUTABLE</code> rồi khởi động lại.'
    );

  const warn = $('#warn');
  warn.classList.toggle('hidden', problems.length === 0);
  warn.innerHTML = problems.map((p) => `<div>${p}</div>`).join('');
}

// ------------------------------------------------------------------- shots

async function loadShots() {
  shots = (await api('/api/shots')).shots;
  renderGrid();
}

function renderGrid() {
  const list = filter === 'all' ? shots : shots.filter((s) => s.track === filter);
  if (!list.length) {
    $('#grid').innerHTML = '<p class="empty">Không có composition nào khớp bộ lọc.</p>';
    return;
  }
  $('#grid').innerHTML = list
    .map((s) => {
      const thumb = s.still
        ? `<img src="/api/still/${s.id}.png?t=${Date.now()}" alt="${esc(s.title)}" loading="lazy">`
        : '<span class="none">Chưa có ảnh preview</span>';
      const done = s.video ? `<span class="badge-done">${mb(s.video_size)}</span>` : '';
      return `
      <article class="card" data-id="${s.id}">
        <div class="thumb" data-act="open" data-id="${s.id}">
          ${thumb}
          <span class="badge ${s.track}">${TRACKS[s.track] || s.track}</span>
          ${done}
        </div>
        <div class="meta">
          <h3>${esc(s.title)}</h3>
          <div class="id">${s.id}</div>
          <div class="facts">${s.duration_s}s · ${s.width}×${s.height} · ${s.fps}fps${
            s.vo_lines ? ` · ${s.vo_lines} câu` : ''
          }</div>
        </div>
        <div class="actions">
          <button class="btn small" data-act="still" data-id="${s.id}"
            ${busy.has(`${s.id}:still`) ? 'disabled' : ''}>
            ${busy.has(`${s.id}:still`) ? 'Đang render…' : 'Ảnh preview'}
          </button>
          <button class="btn small primary" data-act="video" data-id="${s.id}"
            ${busy.has(`${s.id}:video`) ? 'disabled' : ''}>
            ${busy.has(`${s.id}:video`) ? 'Đang render…' : 'Render'}
          </button>
          ${s.video ? `<a class="btn small" href="/api/video/${s.id}" download>Tải về</a>` : ''}
        </div>
      </article>`;
    })
    .join('');
}

// -------------------------------------------------------------------- jobs

function jobRow(j) {
  const pct = Math.round(j.progress * 100);
  const kind =
    { video: 'render video', still: 'ảnh preview', frames: 'khung QA', gen: 'sinh registry' }[j.kind] ||
    j.kind;
  const body = j.status === 'error' ? j.error : j.message;
  return `
    <div class="job">
      <div class="job-top">
        <span style="display:flex;align-items:center;gap:9px;min-width:0">
          <span class="dot ${j.status}"></span>
          <span class="job-name">${esc(j.shot || '—')} <span class="kind">· ${kind}</span></span>
        </span>
        <span style="display:flex;align-items:center;gap:10px">
          <span class="kind" style="color:var(--dim);font-size:12px">${j.elapsed_s}s</span>
          ${
            j.status === 'running' || j.status === 'queued'
              ? `<button class="btn small" data-act="cancel" data-job="${j.id}">Huỷ</button>`
              : ''
          }
        </span>
      </div>
      ${
        j.status === 'running'
          ? `<div class="bar"><i style="width:${pct}%"></i></div>`
          : ''
      }
      ${body ? `<div class="job-msg ${j.status === 'error' ? 'err' : ''}">${esc(body)}</div>` : ''}
    </div>`;
}

async function loadJobs() {
  let jobs;
  try {
    jobs = (await api('/api/jobs')).jobs;
  } catch {
    return;
  }
  $('#jobs').innerHTML = jobs.length
    ? jobs.map(jobRow).join('')
    : '<p class="empty">Chưa có tác vụ nào.</p>';

  const live = jobs.filter((j) => j.status === 'running' || j.status === 'queued');
  const next = new Set(live.map((j) => `${j.shot}:${j.kind}`));
  const changed = next.size !== busy.size || [...next].some((k) => !busy.has(k));
  busy = next;
  if (changed) renderGrid(); // khoá / mở lại nút cho đúng trạng thái

  if (live.length && !poll) poll = setInterval(tick, 1200);
  if (!live.length && poll) {
    clearInterval(poll);
    poll = null;
    loadShots(); // job vừa xong — làm mới thumbnail và nút tải
  }
}

const tick = () => loadJobs();

// ------------------------------------------------------------------- modal

function openModal(title, html) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = html;
  $('#modal').classList.remove('hidden');
}
const closeModal = () => $('#modal').classList.add('hidden');

async function showShot(id) {
  const s = shots.find((x) => x.id === id);
  if (!s) return;

  let html = '';
  if (s.video) {
    html += `<video controls preload="metadata" src="/api/video/${s.id}"></video>
             <div class="row" style="margin-top:12px">
               <a class="btn primary" href="/api/video/${s.id}" download>Tải ${s.id}</a>
               <span class="kind" style="color:var(--dim);font-size:12px">${mb(s.video_size)}</span>
             </div>`;
  } else if (s.still) {
    html += `<img src="/api/still/${s.id}.png" style="max-height:60vh;border-radius:10px;display:block;margin:0 auto">`;
  }

  html += `<div class="row" style="margin-top:16px">
      <label>Khung hình QA</label>
      <input type="text" id="qa-frames" value="0,${Math.floor(s.frames / 2)},${s.frames - 1}">
      <button class="btn" data-act="qa" data-id="${s.id}">Render khung</button>
    </div>`;

  try {
    const { frames } = await api(`/api/qa-frames/${s.id}`);
    if (frames.length) {
      html += `<div class="frames">${frames
        .map(
          (f) =>
            `<figure style="margin:0"><img src="/api/qa/${f}?t=${Date.now()}" loading="lazy">
             <figcaption>${esc(f.replace(s.id + '-', '').replace('.png', ''))}</figcaption></figure>`
        )
        .join('')}</div>`;
    }
  } catch { /* không có khung QA — bỏ qua */ }

  if (s.has_script) {
    try {
      const { script } = await api(`/api/shots/${s.id}/script`);
      html += `<h4 style="margin:20px 0 8px;font-size:14px">Kịch bản</h4><pre>${esc(script)}</pre>`;
    } catch { /* không đọc được script — bỏ qua */ }
  }

  openModal(`${s.title} · ${s.id}`, html);
}

// ------------------------------------------------------------------ events

document.addEventListener('click', async (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const { act, id, job } = el.dataset;

  try {
    if (act === 'open') return showShot(id);

    if (act === 'still') {
      el.disabled = true;
      await post('/api/render', { id, kind: 'still', scale: 0.5 });
    } else if (act === 'video') {
      el.disabled = true;
      await post('/api/render', { id, kind: 'video', scale: 1 });
    } else if (act === 'qa') {
      const frames = $('#qa-frames').value;
      el.disabled = true;
      await post('/api/frames', { id, frames, scale: 0.5 });
      closeModal();
    } else if (act === 'cancel') {
      await post(`/api/jobs/${job}/cancel`);
    }
    loadJobs();
  } catch (err) {
    alert(err.message);
  } finally {
    el.disabled = false;
  }
});

$('#filters').addEventListener('click', (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  document.querySelectorAll('.chip').forEach((c) => c.classList.toggle('on', c === chip));
  filter = chip.dataset.track;
  renderGrid();
});

$('#btn-gen').addEventListener('click', async (e) => {
  e.target.disabled = true;
  try {
    await post('/api/gen');
    loadJobs();
  } catch (err) {
    alert(err.message);
  } finally {
    e.target.disabled = false;
  }
});

$('#modal-x').addEventListener('click', closeModal);
$('#modal').addEventListener('click', (e) => {
  if (e.target.id === 'modal') closeModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
});

// -------------------------------------------------------------------- boot

(async () => {
  await loadStatus();
  await loadShots().catch((e) => {
    $('#grid').innerHTML = `<p class="empty">Không tải được danh sách: ${esc(e.message)}</p>`;
  });
  loadJobs();
})();
