/* =============================================================
   Campus Eye — Dashboard JavaScript
   Handles: WebSocket streams, alerts, face registry, event log,
            mode switching, schedule display, toasts, modals.
   ============================================================= */

const API = '';          // same origin — empty string = relative URLs
const WS_PROTO = location.protocol === 'https:' ? 'wss' : 'ws';
const WS_BASE  = `${WS_PROTO}://${location.host}`;

/* ── State ─────────────────────────────────────────────────── */
let currentMode   = 'normal';
let eventsPage    = 1;
let eventsTotal   = 0;
let alertCount    = 0;
let streamWs      = null;
let alertWs       = null;
let feedFrameTs   = 0;
let feedFpsTimer  = null;
let fpsFrameCount = 0;

/* ── Icons per event type ───────────────────────────────────── */
const EVENT_ICONS = {
  loitering:          '🚶',
  littering:          '🗑️',
  vandalism:          '💥',
  unknown_face:       '👤',
  weapon:             '🔪',
  vehicle_intrusion:  '🚲',
  overcrowding:       '👥',
  alcohol:            '🍺',
  foreign_object:     '📱',
  head_swiveling:     '👀',
  talking:            '💬',
  hand_interaction:   '🤝',
  drink_in_exam:      '🥤',
  crowd_cheat:        '🤔',
};

/* =============================================================
   INIT
   ============================================================= */
document.addEventListener('DOMContentLoaded', () => {
  connectAlertWebSocket();
  connectStreamWebSocket();
  loadStats();
  loadFaces();
  loadMode();
  loadSchedule();
  updateSourceStatus();
  loadUploads();

  // Poll snapshot fallback if WS stream fails
  setInterval(pollSnapshot, 2000);

  // Refresh stats every 30s
  setInterval(loadStats, 30000);

  // Refresh source status every 5s
  setInterval(updateSourceStatus, 5000);

  // Update feed info
  document.getElementById('info-api').textContent = `${location.origin}/api`;
});

/* =============================================================
   NAVIGATION
   ============================================================= */
function showPanel(name, el) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`panel-${name}`).classList.add('active');
  el.classList.add('active');

  if (name === 'events') loadEvents();
  if (name === 'faces')  loadFaces();
  if (name === 'settings') { loadMode(); loadSchedule(); }
}

/* =============================================================
   WEBSOCKET — Live stream
   ============================================================= */
function connectStreamWebSocket() {
  if (streamWs) streamWs.close();

  streamWs = new WebSocket(`${WS_BASE}/ws/stream`);

  streamWs.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'frame' && msg.data) {
        const img = document.getElementById('live-feed');
        img.src = `data:image/jpeg;base64,${msg.data}`;
        fpsFrameCount++;
      }
    } catch (_) {}
  };

  streamWs.onclose = () => {
    setTimeout(connectStreamWebSocket, 3000);
  };

  // FPS counter
  if (feedFpsTimer) clearInterval(feedFpsTimer);
  feedFpsTimer = setInterval(() => {
    document.getElementById('feed-fps-tag').textContent = `${fpsFrameCount} FPS`;
    fpsFrameCount = 0;
  }, 1000);
}

/* Fallback: poll /api/stream/snapshot every 2s if WS not delivering */
let lastFeedSrc = '';
function pollSnapshot() {
  if (streamWs && streamWs.readyState === WebSocket.OPEN) return;
  const img = document.getElementById('live-feed');
  const url = `/api/stream/snapshot?t=${Date.now()}`;
  img.src = url;
}

/* =============================================================
   WEBSOCKET — Alerts
   ============================================================= */
function connectAlertWebSocket() {
  if (alertWs) alertWs.close();

  alertWs = new WebSocket(`${WS_BASE}/ws/alerts`);

  alertWs.onopen = () => {
    setWsStatus(true);
  };

  alertWs.onmessage = (e) => {
    try {
      const alert = JSON.parse(e.data);
      handleIncomingAlert(alert);
    } catch (_) {}
  };

  alertWs.onclose = () => {
    setWsStatus(false);
    setTimeout(connectAlertWebSocket, 4000);
  };

  alertWs.onerror = () => setWsStatus(false);
}

function setWsStatus(connected) {
  const dot   = document.getElementById('ws-dot');
  const label = document.getElementById('ws-label');
  const info  = document.getElementById('info-ws');
  dot.className   = 'ws-dot' + (connected ? ' connected' : '');
  label.textContent = connected ? 'Live' : 'Reconnecting…';
  if (info) info.textContent = connected ? '✔ Connected' : '✗ Disconnected';
}

/* =============================================================
   ALERT HANDLING
   ============================================================= */
function handleIncomingAlert(alert) {
  alertCount++;

  // Update badge
  const badge = document.getElementById('alert-badge');
  badge.textContent = alertCount;
  badge.style.display = 'inline';

  // Update unack stat
  const unack = document.getElementById('stat-unack');
  if (unack.textContent !== '—') unack.textContent = parseInt(unack.textContent || 0) + 1;

  const item = buildAlertItem(alert, true);

  // Prepend to recent-alerts (live panel)
  const recent = document.getElementById('recent-alerts');
  clearPlaceholder(recent);
  recent.insertBefore(item.cloneNode(true), recent.firstChild);
  if (recent.children.length > 10) recent.lastChild.remove();

  // Prepend to all-alerts (alerts panel)
  const allAlerts = document.getElementById('all-alerts');
  clearPlaceholder(allAlerts);
  allAlerts.insertBefore(item, allAlerts.firstChild);

  // Toast
  showToast(`${EVENT_ICONS[alert.event_type] || '⚠'} ${fmtType(alert.event_type)} detected`, 'error');

  // Sound pulse on mode badge
  const badge2 = document.getElementById('mode-badge');
  badge2.style.transform = 'scale(1.08)';
  setTimeout(() => badge2.style.transform = '', 300);
}

function buildAlertItem(alert, isNew = false) {
  const el = document.createElement('div');
  el.className = 'alert-item' + (isNew ? ' new' : '');
  el.dataset.eventId = alert.event_id;

  const snapHtml = alert.snapshot_url
    ? `<img class="alert-snap" src="${alert.snapshot_url}" alt="snap"
           onclick="openModal('${alert.snapshot_url}','${fmtType(alert.event_type)}','${(alert.description||'').replace(/'/g,"\\'")}')"/>`
    : '';

  el.innerHTML = `
    <div class="alert-icon ${alert.event_type}">${EVENT_ICONS[alert.event_type] || '⚠'}</div>
    <div class="alert-body">
      <div class="alert-type">${fmtType(alert.event_type)}</div>
      <div class="alert-desc">${alert.description || '—'}</div>
    </div>
    ${snapHtml}
    <div class="alert-meta">
      <div class="alert-time">${fmtTime(alert.timestamp)}</div>
      <div class="alert-cam">${alert.camera_id || ''}</div>
      ${alert.event_id ? `<button class="btn-ack" onclick="acknowledgeEvent(${alert.event_id},this)">Ack</button>` : ''}
    </div>`;

  return el;
}

function clearAlerts() {
  const containers = ['recent-alerts', 'all-alerts'];
  containers.forEach(id => {
    const el = document.getElementById(id);
    el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:12px 0;">No alerts.</div>';
  });
  alertCount = 0;
  document.getElementById('alert-badge').style.display = 'none';
}

/* =============================================================
   STATS
   ============================================================= */
async function loadStats() {
  try {
    const [facesRes, eventsRes, unackRes, modeRes] = await Promise.all([
      fetch(`${API}/api/faces/`),
      fetch(`${API}/api/events/?page_size=1`),
      fetch(`${API}/api/events/?acknowledged=false&page_size=1`),
      fetch(`${API}/api/settings/mode`),
    ]);

    if (facesRes.ok) {
      const faces = await facesRes.json();
      document.getElementById('stat-faces').textContent = faces.length;
    }
    if (eventsRes.ok) {
      const ev = await eventsRes.json();
      document.getElementById('stat-events').textContent = ev.total;
    }
    if (unackRes.ok) {
      const ua = await unackRes.json();
      document.getElementById('stat-unack').textContent = ua.total;
    }
    if (modeRes.ok) {
      const m = await modeRes.json();
      document.getElementById('stat-mode').textContent = m.mode.toUpperCase();
    }
  } catch (e) {
    console.warn('Stats load failed:', e);
  }
}

/* =============================================================
   VIDEO SOURCE MANAGEMENT
   ============================================================= */
async function updateSourceStatus() {
  try {
    const res = await fetch(`${API}/api/stream/source`);
    if (!res.ok) return;
    const data = await res.json();
    const dot   = document.getElementById('source-dot');
    const label = document.getElementById('source-label');
    if (!dot || !label) return;
    const icons = { file: '📂', rtsp: '📡', webcam: '🎥', none: '⭕', unknown: '❓' };
    dot.className = 'ws-dot' + (data.active ? ' connected' : '');
    label.textContent = data.source
      ? `${icons[data.type] || ''} ${data.source} ${data.active ? '(live)' : '(buffering…)'}`
      : 'No source — upload a video or enter an RTSP URL below';
  } catch (e) {}
}

async function uploadVideo() {
  const input = document.getElementById('upload-file');
  const file  = input.files[0];
  if (!file) { showToast('Select a video file first', 'error'); return; }
  const labelText = document.getElementById('upload-label-text');
  const prog = document.getElementById('upload-progress');
  if (labelText) labelText.textContent = `Uploading ${file.name}…`;
  prog.style.display = 'block';
  prog.textContent = 'Uploading…';
  const fd = new FormData();
  fd.append('file', file);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', `${API}/api/stream/upload`);
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const pct = Math.round(e.loaded/e.total*100);
      prog.textContent = `Uploading… ${pct}%`;
    }
  };
  xhr.onload = () => {
    if (xhr.status === 200) {
      const data = JSON.parse(xhr.responseText);
      showToast(`✔ ${data.filename} uploaded & processing started`, 'success');
      prog.textContent = `✔ ${data.filename} (${data.size_kb} KB) — processing`;
      if (labelText) labelText.textContent = `Click to select another video file`;
      input.value = '';
      loadUploads();
      updateSourceStatus();
    } else {
      try {
        const err = JSON.parse(xhr.responseText);
        showToast(err.error || 'Upload failed', 'error');
      } catch { showToast('Upload failed', 'error'); }
      prog.style.display = 'none';
      if (labelText) labelText.textContent = 'Click to select a video file — upload starts automatically';
    }
  };
  xhr.onerror = () => {
    prog.style.display = 'none';
    if (labelText) labelText.textContent = 'Click to select a video file — upload starts automatically';
    showToast('Upload error — check your connection', 'error');
  };
  xhr.send(fd);
}

async function setRtspSource() {
  const url = document.getElementById('rtsp-url').value.trim();
  if (!url) { showToast('Enter an RTSP URL or webcam index (e.g. 0)', 'error'); return; }
  try {
    const res = await fetch(`${API}/api/stream/source`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({url}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    showToast(`✔ Source set to: ${url}`, 'success');
    updateSourceStatus();
  } catch (e) { showToast(e.message, 'error'); }
}

async function loadUploads() {
  const list = document.getElementById('uploads-list');
  if (!list) return;
  try {
    const res = await fetch(`${API}/api/stream/uploads`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.uploads.length) {
      list.innerHTML = '<span style="color:var(--text-muted);">No uploads yet.</span>';
      return;
    }
    list.innerHTML = data.uploads.map(f => `
      <div style="display:flex;align-items:center;justify-content:space-between;
                  padding:7px 10px;background:rgba(255,255,255,0.03);border-radius:6px;gap:8px;">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary);">
          📄 ${escHtml(f.name)} <span style="color:var(--text-muted);font-size:0.7rem;">${f.size_kb} KB</span>
        </span>
        <button class="btn-ack" onclick="useUpload('${escHtml(f.name)}')" style="white-space:nowrap;">▶ Use</button>
      </div>`).join('');
  } catch (e) {}
}

async function useUpload(filename) {
  try {
    const res = await fetch(`${API}/api/stream/use-upload`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({filename}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    showToast(`▶ Now processing: ${filename}`, 'success');
    updateSourceStatus();
  } catch (e) { showToast(e.message, 'error'); }
}

/* =============================================================
   MODE
   ============================================================= */
async function loadMode() {
  try {
    const res = await fetch(`${API}/api/settings/mode`);
    if (!res.ok) return;
    const data = await res.json();
    applyMode(data.mode);
  } catch (e) {}
}

async function setMode(mode) {
  try {
    const res = await fetch(`${API}/api/settings/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();
    applyMode(data.mode);
    showToast(`Mode switched to ${mode.toUpperCase()}`, 'success');
  } catch (e) {
    showToast('Failed to switch mode', 'error');
  }
}

function applyMode(mode) {
  currentMode = mode;
  const badge = document.getElementById('mode-badge');
  const text  = document.getElementById('mode-text');
  const label = document.getElementById('settings-mode-label');
  badge.className = `mode-badge ${mode}`;
  text.textContent = `${mode.toUpperCase()} MODE`;
  if (label) label.textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
  document.getElementById('stat-mode').textContent = mode.toUpperCase();
}

function toggleMode() {
  setMode(currentMode === 'normal' ? 'exam' : 'normal');
}

/* =============================================================
   SCHEDULE
   ============================================================= */
async function loadSchedule() {
  try {
    const res = await fetch(`${API}/api/settings/schedule`);
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById('schedule-tbody');
    if (!data.schedule || data.schedule.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-muted);padding:12px 0;">No schedule configured.</td></tr>';
      return;
    }
    tbody.innerHTML = data.schedule.map(e => `
      <tr>
        <td>${e.day}</td>
        <td style="font-family:'JetBrains Mono',monospace;">${e.start}</td>
        <td style="font-family:'JetBrains Mono',monospace;">${e.end}</td>
        <td><span class="tag tag-${e.mode}">${e.mode.toUpperCase()}</span></td>
      </tr>`).join('');
  } catch (e) {}
}

/* =============================================================
   EVENT LOG
   ============================================================= */
async function loadEvents() {
  const type = document.getElementById('filter-type').value;
  const mode = document.getElementById('filter-mode').value;
  const ack  = document.getElementById('filter-ack').value;

  let url = `${API}/api/events/?page=${eventsPage}&page_size=15`;
  if (type) url += `&event_type=${type}`;
  if (mode) url += `&mode=${mode}`;
  if (ack !== '') url += `&acknowledged=${ack}`;

  const tbody = document.getElementById('events-tbody');
  tbody.innerHTML = '<tr><td colspan="8" style="color:var(--text-muted);text-align:center;padding:20px;">Loading…</td></tr>';

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();
    eventsTotal = data.total;

    document.getElementById('events-count').textContent =
      `${data.total} total event${data.total !== 1 ? 's' : ''}`;
    document.getElementById('page-label').textContent = `Page ${eventsPage}`;
    document.getElementById('btn-prev').disabled = eventsPage <= 1;
    document.getElementById('btn-next').disabled = eventsPage * 15 >= eventsTotal;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="color:var(--text-muted);text-align:center;padding:20px;">No events found.</td></tr>';
      return;
    }

    tbody.innerHTML = data.items.map(ev => {
      const snapBtn = ev.snapshot_path
        ? `<button class="btn-ack" onclick="openModal('/${ev.snapshot_path}','${fmtType(ev.event_type)}','')">📷</button>`
        : '—';
      const ackBtn = !ev.acknowledged
        ? `<button class="btn-ack" onclick="acknowledgeEvent(${ev.id},this)">Ack</button>`
        : '✔';
      return `
        <tr>
          <td style="font-family:'JetBrains Mono',monospace;color:var(--text-muted);">#${ev.id}</td>
          <td>${EVENT_ICONS[ev.event_type] || ''} ${fmtType(ev.event_type)}</td>
          <td><span class="tag tag-${ev.mode}">${ev.mode.toUpperCase()}</span></td>
          <td>${ev.camera_id}</td>
          <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
              title="${ev.description || ''}">${ev.description || '—'}</td>
          <td style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;">${fmtTime(ev.created_at)}</td>
          <td>${ev.acknowledged
            ? '<span class="tag tag-acked">Acked</span>'
            : '<span class="tag tag-open">Open</span>'}</td>
          <td style="display:flex;gap:6px;">${snapBtn} ${ackBtn}</td>
        </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" style="color:var(--accent-red);text-align:center;padding:20px;">Failed to load events.</td></tr>`;
  }
}

function changePage(delta) {
  const newPage = eventsPage + delta;
  if (newPage < 1) return;
  if ((newPage - 1) * 15 >= eventsTotal && delta > 0) return;
  eventsPage = newPage;
  loadEvents();
}

async function clearEventLog(acknowledgedOnly = false) {
  const label = acknowledgedOnly ? 'acknowledged events' : 'ALL events';
  if (!confirm(`This will permanently delete ${label} and their snapshots. Continue?`)) return;
  try {
    const url = `${API}/api/events/?acknowledged_only=${acknowledgedOnly}`;
    const res  = await fetch(url, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to clear events');
    showToast(`🗑 ${data.message}`, 'success');
    eventsPage = 1;
    loadEvents();
    loadStats();
  } catch (err) {
    showToast(err.message, 'error');
  }
}


async function acknowledgeEvent(eventId, btn) {
  try {
    const res = await fetch(`${API}/api/events/${eventId}/acknowledge`, { method: 'POST' });
    if (!res.ok) throw new Error();
    if (btn) { btn.textContent = '✔'; btn.disabled = true; }
    showToast('Event acknowledged', 'success');
    loadStats();
  } catch (e) {
    showToast('Failed to acknowledge', 'error');
  }
}

/* =============================================================
   FACE REGISTRY
   ============================================================= */
async function loadFaces() {
  const grid = document.getElementById('faces-grid');
  grid.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;">Loading…</div>';
  try {
    const res = await fetch(`${API}/api/faces/`);
    if (!res.ok) throw new Error();
    const faces = await res.json();

    document.getElementById('stat-faces').textContent = faces.length;

    if (!faces.length) {
      grid.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;">No faces registered yet.</div>';
      return;
    }

    grid.innerHTML = faces.map(f => {
      const roleClass = f.role;
      const photoHtml = f.photo_path
        ? `<img class="face-avatar" src="/${f.photo_path}" alt="${f.name}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"/>`
        : '';
      const placeholderHtml = `<div class="face-avatar-placeholder" ${f.photo_path ? 'style="display:none"' : ''}>
          ${f.name.charAt(0).toUpperCase()}</div>`;

      return `
        <div class="face-card" id="face-card-${f.id}">
          <button class="face-delete-btn" onclick="deleteFace(${f.id})" title="Remove">✕</button>
          ${photoHtml}${placeholderHtml}
          <div class="face-name">${escHtml(f.name)}</div>
          <div class="face-id">${f.student_id || '—'}</div>
          <span class="face-role-badge ${roleClass}">${f.role}</span>
        </div>`;
    }).join('');
  } catch (e) {
    grid.innerHTML = '<div style="color:var(--accent-red);font-size:0.8rem;">Failed to load faces.</div>';
  }
}

/* ────────────────────────────────────────────────────────────
   FACE REGISTRY — Registration Tab Logic
   ============================================================= */

// State for webcam
let _webcamStream  = null;
let _webcamFrames  = [];     // base64 JPEG strings
let _webcamTimer   = null;
let _selectedClip  = null;

function switchRegTab(tab) {
  ['photo', 'clip', 'webcam'].forEach(t => {
    document.getElementById(`reg-tab-${t}`).style.display = t === tab ? '' : 'none';
    document.getElementById(`tab-${t}`).classList.toggle('active', t === tab);
  });
  // Cancel webcam if switching away
  if (tab !== 'webcam') cancelWebcam();
}

// ── Photo tab ────────────────────────────────────────────────
async function registerFacePhoto() {
  const name  = document.getElementById('reg-name').value.trim();
  const sid   = document.getElementById('reg-id').value.trim();
  const role  = document.getElementById('reg-role').value;
  const photo = document.getElementById('reg-photo').files[0];
  if (!name)  { showToast('Name is required', 'error'); return; }
  if (!photo) { showToast('Select a photo first', 'error'); return; }

  const btn = document.getElementById('btn-register-photo');
  btn.disabled = true; btn.textContent = 'Uploading…';

  const fd = new FormData();
  fd.append('name', name); fd.append('role', role); fd.append('photo', photo);
  if (sid) fd.append('student_id', sid);

  try {
    const res  = await fetch(`${API}/api/faces/register`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Registration failed');
    showToast(`✔ ${name} registered (photo)`, 'success');
    resetRegForm(); loadFaces();
  } catch (err) { showToast(err.message, 'error'); }
  finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> Register Face`;
  }
}

// ── Clip tab ─────────────────────────────────────────────────
function onClipSelected(input) {
  _selectedClip = input.files[0];
  if (!_selectedClip) return;
  document.getElementById('clip-label-text').textContent = `✔ ${_selectedClip.name}`;
  document.getElementById('btn-register-clip').disabled = false;
}

async function registerFaceClip() {
  const name = document.getElementById('reg-name').value.trim();
  const sid  = document.getElementById('reg-id').value.trim();
  const role = document.getElementById('reg-role').value;
  if (!name)         { showToast('Name is required', 'error'); return; }
  if (!_selectedClip){ showToast('Select a video clip first', 'error'); return; }

  const btn  = document.getElementById('btn-register-clip');
  const prog = document.getElementById('clip-progress');
  btn.disabled = true; btn.textContent = 'Processing clip…';
  prog.style.display = 'block';
  prog.textContent = '⏳ Uploading clip and extracting face embeddings… (this may take 10–20s)';

  const fd = new FormData();
  fd.append('name', name); fd.append('role', role); fd.append('clip', _selectedClip);
  if (sid) fd.append('student_id', sid);

  try {
    const res  = await fetch(`${API}/api/faces/register-clip`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Registration failed');
    showToast(`✔ ${name} registered with ${data.message.match(/\d+/)?.[0] || 'multiple'} embeddings`, 'success');
    prog.textContent = `✔ ${data.message}`;
    resetRegForm(); loadFaces();
  } catch (err) {
    showToast(err.message, 'error');
    prog.textContent = `✗ ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> Register from Clip`;
  }
}

// ── Webcam tab ───────────────────────────────────────────────
async function startWebcamCapture() {
  const statusEl = document.getElementById('webcam-status');

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    statusEl.textContent = '✗ Your browser does not support camera access. Try Chrome or Firefox.';
    showToast('Camera API not supported in this browser', 'error');
    return;
  }

  statusEl.textContent = 'Requesting camera access…';

  try {
    // Use plain { video: true } — no facingMode, more compatible on Linux/desktop
    _webcamStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    const video = document.getElementById('webcam-video');
    video.srcObject = _webcamStream;
    document.getElementById('webcam-overlay').style.display  = 'none';
    document.getElementById('webcam-rec-dot').style.display  = 'flex';
    document.getElementById('webcam-frame-count').style.display = 'block';
    document.getElementById('btn-webcam-start').disabled  = true;
    document.getElementById('btn-webcam-stop').disabled   = false;
    document.getElementById('btn-webcam-cancel').style.display = 'inline-flex';
    statusEl.textContent = 'Capturing… slowly turn your head left → centre → right → centre';
    _webcamFrames = [];

    _webcamTimer = setInterval(() => {
      const canvas = document.createElement('canvas');
      canvas.width  = video.videoWidth  || 640;
      canvas.height = video.videoHeight || 480;
      canvas.getContext('2d').drawImage(video, 0, 0);
      _webcamFrames.push(canvas.toDataURL('image/jpeg', 0.85));
      document.getElementById('webcam-frame-count').textContent = `${_webcamFrames.length} frames`;
    }, 500);

  } catch (err) {
    let msg, hint;
    if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
      msg  = 'Camera is already in use by another application.';
      hint = '💡 The monitoring pipeline may be capturing from this webcam. ' +
             'Go to <strong>Live Feed → Video Source</strong> and switch to a video file or RTSP stream, ' +
             'then retry webcam registration.';
    } else if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      msg  = 'Camera permission was denied.';
      hint = '💡 Click the camera icon in your browser address bar, allow access, then retry.';
    } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
      msg  = 'No camera device found.';
      hint = '💡 Make sure a webcam is connected and recognised by your OS.';
    } else {
      msg  = err.message || 'Unknown camera error.';
      hint = '💡 Ensure the camera is connected and not blocked by another application.';
    }
    statusEl.innerHTML =
      `<span style="color:var(--accent-red);font-weight:600;">✗ ${msg}</span><br>` +
      `<span style="color:var(--text-muted);font-size:0.73rem;line-height:1.6;">${hint}</span>`;
    showToast(`Camera: ${msg}`, 'error');
  }
}

async function stopWebcamCapture() {
  clearInterval(_webcamTimer);
  if (_webcamStream) { _webcamStream.getTracks().forEach(t => t.stop()); _webcamStream = null; }
  document.getElementById('webcam-rec-dot').style.display  = 'none';
  document.getElementById('btn-webcam-start').disabled  = false;
  document.getElementById('btn-webcam-stop').disabled   = true;

  const name = document.getElementById('reg-name').value.trim();
  const sid  = document.getElementById('reg-id').value.trim();
  const role = document.getElementById('reg-role').value;

  if (!name) { showToast('Enter a name before capturing', 'error'); return; }
  if (_webcamFrames.length < 2) {
    showToast('Too few frames captured. Try again.', 'error');
    document.getElementById('webcam-status').textContent = 'Not enough frames — try again.';
    return;
  }

  document.getElementById('webcam-status').textContent =
    `⏳ Sending ${_webcamFrames.length} frames for face embedding…`;
  document.getElementById('btn-webcam-cancel').style.display = 'none';

  const fd = new FormData();
  fd.append('name', name); fd.append('role', role);
  fd.append('frames', JSON.stringify(_webcamFrames));
  if (sid) fd.append('student_id', sid);

  try {
    const res  = await fetch(`${API}/api/faces/register-webcam`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Registration failed');
    showToast(`✔ ${name} registered via webcam`, 'success');
    document.getElementById('webcam-status').textContent = `✔ ${data.message}`;
    document.getElementById('webcam-overlay').style.display = 'flex';
    document.getElementById('webcam-frame-count').style.display = 'none';
    _webcamFrames = [];
    resetRegForm(); loadFaces();
  } catch (err) {
    showToast(err.message, 'error');
    document.getElementById('webcam-status').textContent = `✗ ${err.message}`;
  }
}

function cancelWebcam() {
  clearInterval(_webcamTimer);
  if (_webcamStream) { _webcamStream.getTracks().forEach(t => t.stop()); _webcamStream = null; }
  _webcamFrames = [];
  const video = document.getElementById('webcam-video');
  if (video) video.srcObject = null;
  const overlay = document.getElementById('webcam-overlay'); if (overlay) overlay.style.display = 'flex';
  const rec = document.getElementById('webcam-rec-dot');     if (rec) rec.style.display = 'none';
  const cnt = document.getElementById('webcam-frame-count'); if (cnt) cnt.style.display = 'none';
  const st  = document.getElementById('btn-webcam-start');   if (st) st.disabled = false;
  const sp  = document.getElementById('btn-webcam-stop');    if (sp) sp.disabled = true;
  const ca  = document.getElementById('btn-webcam-cancel');  if (ca) ca.style.display = 'none';
  const ws  = document.getElementById('webcam-status');      if (ws) ws.textContent = '';
}

function resetRegForm() {
  document.getElementById('reg-name').value = '';
  document.getElementById('reg-id').value   = '';
  document.getElementById('reg-role').value = 'student';
  // Photo tab
  const ph = document.getElementById('reg-photo'); if (ph) ph.value = '';
  const preview = document.getElementById('photo-preview');
  if (preview) { preview.src = ''; preview.style.display = 'none'; }
  const di = document.getElementById('drop-icon'); if (di) di.style.display = 'block';
  const dt = document.getElementById('drop-text'); if (dt) dt.textContent = 'Drop a photo here or click to browse';
  // Clip tab
  _selectedClip = null;
  const ci = document.getElementById('reg-clip'); if (ci) ci.value = '';
  const cl = document.getElementById('clip-label-text'); if (cl) cl.textContent = 'Click to select a video clip';
  const cp = document.getElementById('clip-progress'); if (cp) cp.style.display = 'none';
  const cb = document.getElementById('btn-register-clip'); if (cb) cb.disabled = true;
  // Webcam tab
  cancelWebcam();
}

function previewPhoto(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const preview = document.getElementById('photo-preview');
    preview.src = e.target.result;
    preview.style.display = 'block';
    const di = document.getElementById('drop-icon');
    const dt = document.getElementById('drop-text');
    if (di) di.style.display = 'none';
    if (dt) dt.textContent = file.name;
  };
  reader.readAsDataURL(file);
}

async function deleteFace(id) {
  if (!confirm('Remove this face from the registry?')) return;
  try {
    const res = await fetch(`${API}/api/faces/${id}`, { method: 'DELETE' });
    if (res.status === 204) {
      document.getElementById(`face-card-${id}`)?.remove();
      showToast('Face removed', 'info');
      loadStats();
    } else {
      throw new Error();
    }
  } catch (e) {
    showToast('Failed to delete face', 'error');
  }
}

// Drag-and-drop for photo zone
document.addEventListener('DOMContentLoaded', () => {
  const zone = document.getElementById('file-drop-zone');
  if (!zone) return;
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault(); zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) {
      const input = document.getElementById('reg-photo');
      const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
      previewPhoto(input);
    }
  });
});

/* =============================================================
   MODAL
   ============================================================= */
function openModal(src, title, desc) {
  document.getElementById('modal-image').src = src;
  document.getElementById('modal-title').textContent = title || 'Snapshot';
  document.getElementById('modal-desc').textContent  = desc || '';
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  document.getElementById('modal-image').src = '';
}

/* =============================================================
   TOASTS
   ============================================================= */
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const icons = { success: '✔', error: '✕', info: 'ℹ' };
  const colors = { success: 'var(--accent-green)', error: 'var(--accent-red)', info: 'var(--accent-blue)' };

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span style="color:${colors[type]};font-size:1rem;">${icons[type]}</span><span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

/* =============================================================
   HELPERS
   ============================================================= */
function fmtType(type) {
  return (type || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function fmtTime(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return ts; }
}

function escHtml(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function clearPlaceholder(container) {
  const ph = container.querySelector('[style*="color:var(--text-muted)"]');
  if (ph) ph.remove();
}
