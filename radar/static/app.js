'use strict';

const $ = (id) => document.getElementById(id);
const esc = (s) => (s ?? '').toString().replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const state = {
  status: null,
  sources: [],
  posts: [],
  insights: [],
  drafts: [],
  pickedPosts: new Set(),
  pickedInsights: new Set(),
  formats: new Set(['post']),
  mode: 'paste',
  fileToken: '',
};

// ---------------------------------------------------------------------------
// Tiện ích
// ---------------------------------------------------------------------------

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) throw new Error((data && data.detail) || `Lỗi ${res.status}`);
  return data;
}

let toastTimer = null;
function toast(message, bad = false) {
  const el = $('toast');
  el.textContent = message;
  el.className = 'toast' + (bad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), bad ? 7000 : 3500);
}

function when(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' });
}

async function pollJob(jobId, onTick) {
  for (;;) {
    const job = await api(`/api/jobs/${jobId}`);
    onTick(job);
    if (job.status === 'done') return job;
    if (job.status === 'error') throw new Error(job.error || 'Tác vụ lỗi');
    await new Promise((r) => setTimeout(r, 1200));
  }
}

function mineSettings() {
  return {
    min_comments: +$('opt-min-comments').value || 0,
    max_posts: +$('opt-max-posts').value || 30,
    max_age_days: +$('opt-max-age').value || 0,
    min_comment_words: +$('opt-min-words').value || 4,
  };
}

// ---------------------------------------------------------------------------
// Khởi động
// ---------------------------------------------------------------------------

async function loadStatus() {
  state.status = await api('/api/status');
  const s = state.status;
  const caps = [
    ['Claude', s.claude, s.claude ? s.model : 'chưa có key — chỉ ra dàn ý'],
    ['Apify', s.apify.ready, s.apify.ready ? 'quét tự động' : 'chưa cấu hình'],
    ['Fanpage', s.page, s.page ? (s.brand || 'đã nối') : 'chưa nối — đăng tay'],
  ];
  $('capabilities').innerHTML = caps.map(([name, on, note]) =>
    `<span class="cap ${on ? 'on' : 'off'}" title="${esc(note)}">${on ? '✓' : '·'} ${name}</span>`
  ).join('');

  $('format-picker').innerHTML = Object.entries(s.formats).map(([key, label]) => `
    <label class="check">
      <input type="checkbox" data-format="${key}" ${key === 'post' ? 'checked' : ''}>
      <span>${esc(label)}</span>
    </label>`).join('');
  $('format-picker').querySelectorAll('input').forEach((cb) => {
    cb.addEventListener('change', () => {
      cb.checked ? state.formats.add(cb.dataset.format) : state.formats.delete(cb.dataset.format);
    });
  });

  const apifyBox = $('apify-state');
  if (!s.apify.token) {
    apifyBox.className = 'notice warn';
    apifyBox.textContent = 'Chưa có APIFY_TOKEN trong .env — dùng tab “Dán tay” hoặc “Nhập file”.';
  } else if (!s.apify.posts_actor) {
    apifyBox.className = 'notice warn';
    apifyBox.textContent = 'Có token nhưng chưa khai báo APIFY_ACTOR_POSTS trong .env.';
  } else {
    apifyBox.className = 'notice good';
    apifyBox.textContent = 'Sẵn sàng quét.';
  }
}

async function loadSources() {
  state.sources = await api('/api/sources');

  $('source-list').innerHTML = state.sources.length
    ? state.sources.map((s) => `
      <div class="item">
        <div class="row between">
          <div>
            <h3>${esc(s.name)}</h3>
            <div class="meta">
              <span>${s.post_count} bài đã thu</span>
              ${s.ref ? `<span class="mono">${esc(s.ref)}</span>` : ''}
            </div>
          </div>
          <button class="btn sm danger" data-del-source="${s.id}">Xoá</button>
        </div>
      </div>`).join('')
    : '<p class="muted small">Chưa có nguồn nào. Thêm một đối thủ để bắt đầu.</p>';

  $('source-list').querySelectorAll('[data-del-source]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Xoá nguồn này cùng toàn bộ bài và insight đã thu?')) return;
      await api(`/api/sources/${btn.dataset.delSource}`, { method: 'DELETE' });
      await loadSources();
      toast('Đã xoá nguồn.');
    });
  });

  const options = state.sources.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  $('collect-source').innerHTML = options || '<option value="">— chưa có nguồn —</option>';
  $('posts-filter').innerHTML = '<option value="">Tất cả nguồn</option>' + options;
}

// ---------------------------------------------------------------------------
// 1. Thu thập
// ---------------------------------------------------------------------------

function currentSource() {
  const id = $('collect-source').value;
  if (!id) { toast('Thêm một nguồn trước đã.', true); return null; }
  return id;
}

function collectProgress(job) {
  $('collect-progress').classList.remove('hidden');
  $('collect-bar').style.width = `${Math.round(job.progress * 100)}%`;
  $('collect-label').textContent = job.message || job.stage;
}

function showCollectResult(result) {
  const skipped = (result.skipped || []).length
    ? `<details class="tune"><summary>${result.skipped.length} bài bị bỏ qua</summary>
       <ul class="quotes">${result.skipped.map((s) => `<li>${esc(s)}</li>`).join('')}</ul></details>`
    : '';
  $('collect-result').innerHTML = `
    <div class="notice good">${esc(result.message || 'Xong.')}</div>${skipped}`;
}

async function doPaste() {
  const sourceId = currentSource();
  if (!sourceId) return;
  const postText = $('paste-post').value.trim();
  if (!postText) { toast('Chưa dán nội dung bài gốc.', true); return; }

  $('btn-paste').disabled = true;
  try {
    const r = await api('/api/paste', {
      method: 'POST',
      body: JSON.stringify({
        source_id: sourceId,
        post_text: postText,
        comments_text: $('paste-comments').value,
        url: $('paste-url').value.trim(),
      }),
    });
    const n = (r.insights || []).length;
    showCollectResult({
      message: r.error
        ? `Đã lưu bài (${r.comments || 0} bình luận) — ${r.error}`
        : `Đã lưu bài, đọc ${r.comments || 0} bình luận, rút ra ${n} insight.`,
    });
    $('paste-post').value = '';
    $('paste-comments').value = '';
    $('paste-url').value = '';
    await Promise.all([loadSources(), loadInsights()]);
    if (n) toast(`${n} insight mới — xem tab 3.`);
  } catch (err) {
    toast(err.message, true);
  } finally {
    $('btn-paste').disabled = false;
  }
}

async function runCollectJob(payload, button) {
  button.disabled = true;
  $('collect-result').innerHTML = '';
  try {
    const { job_id } = await api('/api/collect', { method: 'POST', body: JSON.stringify(payload) });
    const job = await pollJob(job_id, collectProgress);
    showCollectResult(job.result || {});
    await Promise.all([loadSources(), loadPosts(), loadInsights()]);
    toast(job.result?.message || 'Thu thập xong.');
  } catch (err) {
    toast(err.message, true);
    $('collect-result').innerHTML = `<div class="notice bad">${esc(err.message)}</div>`;
  } finally {
    button.disabled = false;
    $('collect-progress').classList.add('hidden');
  }
}

async function doFile() {
  const sourceId = currentSource();
  if (!sourceId) return;
  if (!state.fileToken) { toast('Chọn file trước đã.', true); return; }
  await runCollectJob(
    { source_id: sourceId, adapter: 'file', target: state.fileToken, mine: mineSettings() },
    $('btn-file'),
  );
}

async function doApify() {
  const sourceId = currentSource();
  if (!sourceId) return;
  const target = $('apify-target').value.trim()
    || (state.sources.find((s) => s.id === sourceId) || {}).ref;
  if (!target) { toast('Chưa có link fanpage để quét.', true); return; }
  await runCollectJob(
    { source_id: sourceId, adapter: 'apify', target, mine: mineSettings(), with_comments: true },
    $('btn-apify'),
  );
}

// ---------------------------------------------------------------------------
// 2. Bài đã thu
// ---------------------------------------------------------------------------

async function loadPosts() {
  const sourceId = $('posts-filter').value;
  state.posts = await api('/api/posts' + (sourceId ? `?source_id=${sourceId}` : ''));

  $('post-list').innerHTML = state.posts.length
    ? state.posts.map((p) => `
      <div class="item">
        <label class="check">
          <input type="checkbox" data-post="${p.id}" ${state.pickedPosts.has(p.id) ? 'checked' : ''}>
          <div style="flex:1">
            <div class="meta">
              <span>${esc(p.source_name || '')}</span>
              <span>👍 ${p.reactions}</span>
              <span>💬 ${p.stored_comments}/${p.comment_count}</span>
              <span>🔁 ${p.shares}</span>
              <span>${p.posted_at ? when(p.posted_at) : ''}</span>
              <span class="pill">${p.status === 'mined' ? 'đã đào' : 'chưa đào'}</span>
            </div>
            <p class="body">${esc(p.text)}${p.text.length >= 400 ? '…' : ''}</p>
            ${p.url ? `<a class="mono muted" href="${esc(p.url)}" target="_blank" rel="noopener">mở bài gốc ↗</a>` : ''}
          </div>
        </label>
      </div>`).join('')
    : '<p class="muted small">Chưa có bài nào. Quay lại tab 1 để thu thập.</p>';

  $('post-list').querySelectorAll('[data-post]').forEach((cb) => {
    cb.addEventListener('change', () => {
      cb.checked ? state.pickedPosts.add(cb.dataset.post) : state.pickedPosts.delete(cb.dataset.post);
    });
  });
}

async function remine() {
  const ids = [...state.pickedPosts];
  if (!ids.length) { toast('Chưa chọn bài nào.', true); return; }
  $('btn-remine').disabled = true;
  try {
    const { job_id } = await api('/api/mine', {
      method: 'POST',
      body: JSON.stringify({ post_ids: ids, mine: mineSettings() }),
    });
    const job = await pollJob(job_id, (j) => { $('btn-remine').textContent = j.message || 'Đang đào…'; });
    toast(`Đào xong: ${job.result.insights} insight từ ${job.result.posts} bài.`);
    state.pickedPosts.clear();
    await Promise.all([loadPosts(), loadInsights()]);
  } catch (err) {
    toast(err.message, true);
  } finally {
    $('btn-remine').disabled = false;
    $('btn-remine').textContent = 'Đào lại bài đã chọn';
  }
}

// ---------------------------------------------------------------------------
// 3. Insight
// ---------------------------------------------------------------------------

function updateWriteButton() {
  const n = state.pickedInsights.size;
  $('btn-write').disabled = n === 0;
  $('btn-write').textContent = `Viết bài (${n} insight)`;
}

async function loadInsights() {
  state.insights = await api('/api/insights?status=new');
  const kinds = state.status?.kinds || {};

  $('insight-list').innerHTML = state.insights.length
    ? state.insights.map((i) => `
      <div class="item">
        <label class="check">
          <input type="checkbox" data-insight="${i.id}" ${state.pickedInsights.has(i.id) ? 'checked' : ''}>
          <div style="flex:1">
            <h3>${esc(i.title)}</h3>
            <div class="meta">
              <span class="pill ${esc(i.kind)}">${esc(kinds[i.kind] || i.kind)}</span>
              <span>${i.size} người cùng nói</span>
              <span>từ: ${esc(i.source_name || '')}</span>
            </div>
            ${i.detail ? `<p class="body">${esc(i.detail)}</p>` : ''}
            ${i.gap ? `<p class="body"><b>Bài gốc còn thiếu:</b> ${esc(i.gap)}</p>` : ''}
            ${(i.quotes || []).length ? `<ul class="quotes">${i.quotes.slice(0, 3)
                .map((q) => `<li>“${esc(q)}”</li>`).join('')}</ul>` : ''}
            <button class="btn sm" data-ignore="${i.id}">Bỏ qua</button>
          </div>
        </label>
      </div>`).join('')
    : '<p class="muted small">Chưa có insight nào. Thu thập một bài có nhiều bình luận trước.</p>';

  $('insight-list').querySelectorAll('[data-insight]').forEach((cb) => {
    cb.addEventListener('change', () => {
      cb.checked ? state.pickedInsights.add(cb.dataset.insight)
                 : state.pickedInsights.delete(cb.dataset.insight);
      updateWriteButton();
    });
  });
  $('insight-list').querySelectorAll('[data-ignore]').forEach((btn) => {
    btn.addEventListener('click', async (ev) => {
      ev.preventDefault();
      await api(`/api/insights/${btn.dataset.ignore}/ignore`, { method: 'POST' });
      state.pickedInsights.delete(btn.dataset.ignore);
      await loadInsights();
      updateWriteButton();
    });
  });
  updateWriteButton();
}

async function doWrite() {
  const ids = [...state.pickedInsights];
  if (!ids.length) return;
  if (!state.formats.size) { toast('Chọn ít nhất một định dạng.', true); return; }

  $('btn-write').disabled = true;
  $('write-result').innerHTML = '';
  try {
    const { job_id } = await api('/api/write', {
      method: 'POST',
      body: JSON.stringify({
        insight_ids: ids,
        write: { formats: [...state.formats], extra_brief: $('write-brief').value.trim() },
      }),
    });
    const job = await pollJob(job_id, (j) => {
      $('write-progress').classList.remove('hidden');
      $('write-bar').style.width = `${Math.round(j.progress * 100)}%`;
      $('write-label').textContent = j.message || j.stage;
    });
    const r = job.result || {};
    $('write-result').innerHTML =
      `<div class="notice ${r.flagged ? 'warn' : 'good'}">${esc(r.message || 'Xong.')}
       Sang tab <b>4. Duyệt &amp; đăng</b> để đọc lại.</div>`;
    state.pickedInsights.clear();
    await Promise.all([loadInsights(), loadDrafts()]);
  } catch (err) {
    toast(err.message, true);
  } finally {
    $('write-progress').classList.add('hidden');
    updateWriteButton();
  }
}

// ---------------------------------------------------------------------------
// 4. Duyệt & đăng
// ---------------------------------------------------------------------------

const STATUS_LABELS = {
  draft: 'Chờ duyệt', approved: 'Đã duyệt', scheduled: 'Đã lên lịch',
  published: 'Đã đăng', rejected: 'Đã bỏ',
};

async function loadGolden() {
  try {
    const g = await api('/api/schedule/golden');
    const top = Object.entries(g.hours).sort((a, b) => b[1] - a[1]).slice(0, 4)
      .map(([h]) => `${h}h`).join(', ');
    $('golden-info').className = 'notice';
    $('golden-info').innerHTML = g.source === 'page'
      ? `Khung giờ vàng tính từ ${g.samples} bài gần đây của trang bạn: <b>${top}</b>.
         Chỗ trống gần nhất: <b>${esc(g.next_slot_label)}</b>.`
      : `Chưa đủ dữ liệu trang để tính giờ vàng riêng — đang dùng mốc phổ biến ở VN:
         <b>${top}</b>. Chỗ trống gần nhất: <b>${esc(g.next_slot_label)}</b>.`;
  } catch {
    $('golden-info').innerHTML = '';
  }
}

function draftCard(d) {
  const warnings = (d.warnings || []).length
    ? `<div class="notice bad">⚠ ${d.warnings.map(esc).join('<br>')}</div>` : '';
  const simPct = Math.round((d.similarity || 0) * 100);
  const hooks = (d.hooks || []).length > 1
    ? `<div class="hooks">${d.hooks.map((h, i) =>
        `<button data-hook="${d.id}" data-index="${i}">Đổi sang hook ${i + 1}: ${esc(h)}</button>`).join('')}</div>`
    : '';
  const locked = d.status === 'published' || d.status === 'scheduled';

  return `
  <div class="item draft" data-draft="${d.id}">
    <div class="row between wrap">
      <div class="meta">
        <span class="pill">${esc(STATUS_LABELS[d.status] || d.status)}</span>
        <span class="pill">${esc((state.status?.formats || {})[d.format] || d.format)}</span>
        ${d.insight_kind ? `<span class="pill ${esc(d.insight_kind)}">${esc((state.status?.kinds || {})[d.insight_kind] || d.insight_kind)}</span>` : ''}
        <span title="Độ trùng lặp với bài gốc">trùng ${simPct}%</span>
        ${d.scheduled_at ? `<span>🗓 ${when(d.scheduled_at)}</span>` : ''}
      </div>
      <button class="btn sm danger" data-del-draft="${d.id}">Xoá</button>
    </div>
    ${d.insight_title ? `<p class="muted small">Từ insight: ${esc(d.insight_title)}</p>` : ''}
    ${d.angle ? `<p class="muted small">Góc viết: ${esc(d.angle)}</p>` : ''}
    ${warnings}
    <label class="field"><span>Hook</span>
      <textarea rows="2" data-field="hook" ${locked ? 'disabled' : ''}>${esc(d.hook)}</textarea></label>
    ${locked ? '' : hooks}
    <label class="field"><span>Thân bài</span>
      <textarea rows="10" data-field="body" ${locked ? 'disabled' : ''}>${esc(d.body)}</textarea></label>
    <label class="field"><span>CTA</span>
      <textarea rows="2" data-field="cta" ${locked ? 'disabled' : ''}>${esc(d.cta)}</textarea></label>
    <div class="actions">
      ${locked ? '' : `<button class="btn" data-save="${d.id}">Lưu sửa</button>`}
      ${d.status === 'draft' ? `<button class="btn ok" data-approve="${d.id}">✓ Duyệt</button>` : ''}
      ${d.status === 'approved' ? `
        <button class="btn primary" data-plan="${d.id}">🗓 Lên lịch giờ vàng</button>
        <button class="btn" data-now="${d.id}">Đăng ngay</button>` : ''}
      ${d.status !== 'published' ? `<button class="btn" data-copy="${d.id}">Copy nội dung</button>` : ''}
      ${d.published_id ? `<span class="mono muted">id: ${esc(d.published_id)}</span>` : ''}
    </div>
  </div>`;
}

async function loadDrafts() {
  const filter = $('draft-filter').value;
  state.drafts = await api('/api/drafts' + (filter ? `?status=${filter}` : ''));
  $('draft-list').innerHTML = state.drafts.length
    ? state.drafts.map(draftCard).join('')
    : '<p class="muted small">Chưa có bài nháp nào.</p>';
  bindDraftActions();
  loadGolden();
}

function draftBox(id) {
  return $('draft-list').querySelector(`[data-draft="${id}"]`);
}

function draftFields(id) {
  const box = draftBox(id);
  const get = (name) => {
    const el = box.querySelector(`[data-field="${name}"]`);
    return el ? el.value : undefined;
  };
  return { hook: get('hook'), body: get('body'), cta: get('cta') };
}

async function saveDraft(id, extra = {}) {
  const updated = await api(`/api/drafts/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ ...draftFields(id), ...extra }),
  });
  return updated;
}

function bindDraftActions() {
  const list = $('draft-list');

  list.querySelectorAll('[data-hook]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const draft = state.drafts.find((d) => d.id === btn.dataset.hook);
      const box = draftBox(btn.dataset.hook);
      box.querySelector('[data-field="hook"]').value = draft.hooks[+btn.dataset.index];
    });
  });

  list.querySelectorAll('[data-save]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const d = await saveDraft(btn.dataset.save);
        toast(d.warnings?.length ? 'Đã lưu — vẫn còn cảnh báo trùng lặp.' : 'Đã lưu.');
        await loadDrafts();
      } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
    });
  });

  list.querySelectorAll('[data-approve]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await saveDraft(btn.dataset.approve);   // lưu bản sửa tay trước khi duyệt
        await api(`/api/drafts/${btn.dataset.approve}/approve`, { method: 'POST' });
        toast('Đã duyệt. Giờ lên lịch được rồi.');
        await loadDrafts();
      } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
    });
  });

  list.querySelectorAll('[data-plan]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const r = await api('/api/schedule', {
          method: 'POST', body: JSON.stringify({ draft_id: btn.dataset.plan }),
        });
        toast(r.on_facebook
          ? `Đã hẹn giờ trên Facebook: ${r.slot_label}`
          : `Đã ghi lịch nội bộ: ${r.slot_label}. Chưa nối Fanpage nên tới giờ bạn đăng tay.`);
        await loadDrafts();
      } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
    });
  });

  list.querySelectorAll('[data-now]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Đăng ngay lên Fanpage của bạn?')) return;
      btn.disabled = true;
      try {
        await api('/api/schedule', {
          method: 'POST',
          body: JSON.stringify({ draft_id: btn.dataset.now, publish_now: true }),
        });
        toast('Đã đăng.');
        await loadDrafts();
      } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
    });
  });

  list.querySelectorAll('[data-copy]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const f = draftFields(btn.dataset.copy);
      const text = [f.hook, f.body, f.cta].filter(Boolean).join('\n\n');
      try {
        await navigator.clipboard.writeText(text);
        toast('Đã copy nội dung.');
      } catch { toast('Trình duyệt chặn copy — bôi đen và copy tay nhé.', true); }
    });
  });

  list.querySelectorAll('[data-del-draft]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Xoá bài nháp này?')) return;
      await api(`/api/drafts/${btn.dataset.delDraft}`, { method: 'DELETE' });
      await loadDrafts();
    });
  });
}

// ---------------------------------------------------------------------------
// 5. Hiệu suất
// ---------------------------------------------------------------------------

function groupTable(title, rows) {
  if (!rows.length) return '';
  return `
    <h3 class="muted small">${esc(title)}</h3>
    <table>
      <tr><th>Nhóm</th><th class="num">Bài</th><th class="num">Tương tác TB</th>
          <th class="num">Reach TB</th><th>Hook ăn nhất</th></tr>
      ${rows.map((r) => `<tr>
        <td>${esc(r.label)}</td>
        <td class="num">${r.posts}</td>
        <td class="num">${(r.avg_engagement_rate * 100).toFixed(1)}%</td>
        <td class="num">${r.avg_reach.toLocaleString('vi-VN')}</td>
        <td class="muted small">${esc(r.best_hook)}</td>
      </tr>`).join('')}
    </table>`;
}

async function loadReport() {
  const r = await api('/api/report');
  if (!r.posts) {
    $('report-body').innerHTML =
      '<p class="muted small">Chưa có bài nào đăng qua hệ thống, nên chưa có gì để đo.</p>';
    return;
  }
  $('report-body').innerHTML = `
    ${r.verdict ? `<div class="notice good">${esc(r.verdict)}</div>` : ''}
    ${groupTable('Theo dạng insight', r.by_kind)}
    ${groupTable('Theo định dạng bài', r.by_format)}
    <h3 class="muted small">Bài tốt nhất</h3>
    <table>
      <tr><th>Hook</th><th class="num">Reach</th><th class="num">Tương tác</th><th class="num">Tỉ lệ</th></tr>
      ${r.top.map((t) => `<tr>
        <td>${esc(t.hook)}</td>
        <td class="num">${t.reach.toLocaleString('vi-VN')}</td>
        <td class="num">${t.engaged}</td>
        <td class="num">${(t.engagement_rate * 100).toFixed(1)}%</td>
      </tr>`).join('')}
    </table>`;
}

async function refreshMetrics() {
  const btn = $('btn-refresh-metrics');
  btn.disabled = true;
  try {
    const { job_id } = await api('/api/measure/refresh', { method: 'POST' });
    const job = await pollJob(job_id, () => {});
    const r = job.result || {};
    toast(r.error ? r.error : `Đã cập nhật chỉ số của ${r.updated} bài.`, !!r.error);
    await loadReport();
  } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
}

// ---------------------------------------------------------------------------
// Gắn sự kiện
// ---------------------------------------------------------------------------

function showTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('hidden', p.id !== `panel-${name}`));
  if (name === 'posts') loadPosts();
  if (name === 'insights') loadInsights();
  if (name === 'drafts') loadDrafts();
  if (name === 'report') loadReport();
}

function init() {
  document.querySelectorAll('.tab').forEach((t) =>
    t.addEventListener('click', () => showTab(t.dataset.tab)));

  document.querySelectorAll('.subtab').forEach((t) => t.addEventListener('click', () => {
    state.mode = t.dataset.mode;
    document.querySelectorAll('.subtab').forEach((x) => x.classList.toggle('active', x === t));
    ['paste', 'file', 'apify'].forEach((m) =>
      $(`mode-${m}`).classList.toggle('hidden', m !== state.mode));
  }));

  $('btn-add-source').addEventListener('click', async () => {
    const name = $('src-name').value.trim();
    if (!name) { toast('Chưa nhập tên nguồn.', true); return; }
    await api('/api/sources', {
      method: 'POST',
      body: JSON.stringify({ name, ref: $('src-ref').value.trim() }),
    });
    $('src-name').value = '';
    $('src-ref').value = '';
    await loadSources();
    toast('Đã thêm nguồn.');
  });

  $('file-input').addEventListener('change', async () => {
    const file = $('file-input').files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
      const r = await api('/api/upload', { method: 'POST', body: form });
      state.fileToken = r.token;
      $('file-info').textContent = `Đã tải lên: ${r.filename} (${Math.round(r.size / 1024)} KB)`;
    } catch (err) { toast(err.message, true); }
  });

  $('btn-paste').addEventListener('click', doPaste);
  $('btn-file').addEventListener('click', doFile);
  $('btn-apify').addEventListener('click', doApify);
  $('btn-remine').addEventListener('click', remine);
  $('posts-filter').addEventListener('change', loadPosts);
  $('btn-reload-insights').addEventListener('click', loadInsights);
  $('btn-write').addEventListener('click', doWrite);
  $('btn-reload-drafts').addEventListener('click', loadDrafts);
  $('draft-filter').addEventListener('change', loadDrafts);
  $('btn-refresh-metrics').addEventListener('click', refreshMetrics);

  loadStatus().then(loadSources).catch((err) => toast(err.message, true));
}

init();
