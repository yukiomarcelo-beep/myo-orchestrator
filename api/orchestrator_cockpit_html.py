"""
api/orchestrator_cockpit_html.py
=================================

Cockpit HTML embedado como string Python. Servido em GET /orch.

Dark theme, Bebas Neue + DM Mono, navy/cyan — padrao SIGNAL do MYO.

Sem build step, sem StaticFiles, sem filesystem — tudo num import.
"""

COCKPIT_HTML = r"""<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MYO Cockpit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --navy: #05091A;
    --navy-2: #0b1330;
    --blue: #1256E8;
    --cyan: #00B4D8;
    --ink: #e8edf7;
    --ink-dim: #8a94b0;
    --ok: #2ecc71;
    --warn: #f39c12;
    --bad: #e74c3c;
    --mono: 'DM Mono', ui-monospace, monospace;
    --display: 'Bebas Neue', sans-serif;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; height: 100%;
    background: var(--navy); color: var(--ink);
    font-family: var(--mono); font-size: 13px;
  }
  header {
    padding: 16px 24px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    display: flex; align-items: baseline; gap: 16px;
  }
  header h1 {
    margin: 0; font-family: var(--display);
    font-size: 28px; letter-spacing: 2px; color: var(--cyan);
  }
  header .subtitle { color: var(--ink-dim); font-size: 11px; letter-spacing: 1px; }
  header .tenant { margin-left: auto; color: var(--ink-dim); font-size: 11px; }
  main {
    display: grid; grid-template-columns: 360px 1fr; gap: 0;
    height: calc(100vh - 62px);
  }
  aside.sidebar {
    border-right: 1px solid rgba(255,255,255,0.08);
    padding: 16px; overflow-y: auto;
  }
  section.detail { padding: 16px; overflow-y: auto; }
  .card {
    background: var(--navy-2);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 6px;
    padding: 12px; margin-bottom: 10px;
    cursor: pointer; transition: border-color 0.15s;
  }
  .card:hover { border-color: var(--cyan); }
  .card.selected { border-color: var(--blue); box-shadow: 0 0 0 1px var(--blue); }
  .card .row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .card .runid { font-size: 11px; color: var(--ink-dim); }
  .card .agent { font-weight: 500; color: var(--ink); }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 3px;
    font-size: 10px; letter-spacing: 1px; text-transform: uppercase;
    font-family: var(--display);
  }
  .badge.pending { background: rgba(243,156,18,0.15); color: var(--warn); }
  .badge.running { background: rgba(18,86,232,0.2); color: var(--blue); }
  .badge.done { background: rgba(46,204,113,0.15); color: var(--ok); }
  .badge.failed { background: rgba(231,76,60,0.15); color: var(--bad); }
  .badge.cancelled { background: rgba(138,148,176,0.15); color: var(--ink-dim); }
  button {
    background: var(--blue); color: #fff; border: 0;
    padding: 8px 14px; border-radius: 4px; cursor: pointer;
    font-family: var(--mono); font-size: 12px; letter-spacing: 0.5px;
  }
  button:hover { background: var(--cyan); color: var(--navy); }
  button.secondary { background: transparent; border: 1px solid rgba(255,255,255,0.2); }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  input, textarea {
    background: var(--navy); color: var(--ink);
    border: 1px solid rgba(255,255,255,0.15); border-radius: 4px;
    padding: 6px 10px; font-family: var(--mono); font-size: 12px;
    width: 100%;
  }
  .toolbar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
  .toolbar input { flex: 1; min-width: 140px; }
  h2 { font-family: var(--display); letter-spacing: 1.5px; color: var(--cyan); margin: 0 0 12px; }
  .event-stream {
    background: #000; border: 1px solid rgba(255,255,255,0.08);
    border-radius: 4px; padding: 12px; max-height: 50vh;
    overflow-y: auto; font-size: 11px;
  }
  .event {
    padding: 6px 0; border-bottom: 1px dashed rgba(255,255,255,0.05);
    display: grid; grid-template-columns: 90px 1fr; gap: 8px;
  }
  .event .kind { color: var(--cyan); font-weight: 500; }
  .event .payload { color: var(--ink-dim); word-break: break-all; }
  .empty { color: var(--ink-dim); text-align: center; padding: 40px 20px; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  label { display: block; font-size: 10px; letter-spacing: 1px; color: var(--ink-dim); margin-bottom: 4px; text-transform: uppercase; }
</style>
</head>
<body>
<header>
  <h1>MYO COCKPIT</h1>
  <span class="subtitle">canonical / wave 2</span>
  <span class="tenant" id="tenant-indicator"></span>
</header>

<main>
  <aside class="sidebar">
    <div class="toolbar">
      <input id="filter-project" placeholder="project_id filter" />
      <button class="secondary" onclick="refreshRuns()">reload</button>
    </div>
    <div id="runs-list"></div>
  </aside>

  <section class="detail">
    <h2>Submit new run</h2>
    <div class="form-grid">
      <div>
        <label>project_id</label>
        <input id="new-project" value="myo-default" />
      </div>
      <div>
        <label>agent_id</label>
        <input id="new-agent" value="echo" placeholder="echo / slow / tool" />
      </div>
    </div>
    <label>input (JSON)</label>
    <textarea id="new-input" rows="3">{"content": "hello"}</textarea>
    <div style="margin-top:8px"><button onclick="submitRun()">submit</button></div>

    <h2 style="margin-top:24px">Run detail</h2>
    <div id="run-detail" class="empty">nenhum run selecionado</div>
  </section>
</main>

<script>
const TENANT = localStorage.getItem('myo_tenant') || 'marcelo';
const API = '/api/orchestrator';
document.getElementById('tenant-indicator').textContent = 'tenant: ' + TENANT;

let selectedRunId = null;
let currentEventSource = null;

async function api(path, options = {}) {
  const opts = {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-Id': TENANT,
      ...(options.headers || {}),
    },
    ...options,
  };
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function refreshRuns() {
  try {
    const filter = document.getElementById('filter-project').value.trim();
    const qs = filter ? '?project_id=' + encodeURIComponent(filter) : '';
    const runs = await api('/runs' + qs);
    const listEl = document.getElementById('runs-list');
    if (runs.length === 0) {
      listEl.innerHTML = '<div class="empty">nenhum run ainda</div>';
      return;
    }
    listEl.innerHTML = runs.map(r => `
      <div class="card ${r.run_id === selectedRunId ? 'selected' : ''}"
           onclick="selectRun('${r.run_id}')">
        <div class="row">
          <span class="agent">${escapeHtml(r.agent_id)}</span>
          <span class="badge ${r.status}">${r.status}</span>
        </div>
        <div class="row" style="margin-top:6px">
          <span class="runid">${r.run_id.slice(0, 8)}…</span>
          <span class="runid">${escapeHtml(r.project_id)}</span>
        </div>
      </div>
    `).join('');
  } catch (e) {
    document.getElementById('runs-list').innerHTML =
      '<div class="empty" style="color:var(--bad)">erro: ' + escapeHtml(e.message) + '</div>';
  }
}

async function selectRun(runId) {
  selectedRunId = runId;
  await refreshRuns();
  try {
    const detail = await api('/status?run_id=' + runId);
    const detailEl = document.getElementById('run-detail');
    detailEl.classList.remove('empty');
    detailEl.innerHTML = `
      <div class="card" style="cursor:default">
        <div class="row">
          <span class="agent">${escapeHtml(detail.agent_id)}</span>
          <span class="badge ${detail.status}">${detail.status}</span>
        </div>
        <div class="runid" style="margin-top:6px">run_id: ${detail.run_id}</div>
        <div class="runid">tenant: ${escapeHtml(detail.tenant_id)}  /  project: ${escapeHtml(detail.project_id)}</div>
        ${detail.parent_run_id ? '<div class="runid">parent: ' + detail.parent_run_id + '</div>' : ''}
        <div style="margin-top:10px">
          <button class="secondary" onclick="cancelRun('${detail.run_id}')"
                  ${['done','failed','cancelled'].includes(detail.status) ? 'disabled' : ''}>
            cancel
          </button>
        </div>
      </div>
      <h2 style="margin-top:20px">Event stream</h2>
      <div id="event-stream" class="event-stream"></div>
    `;
    openStream(runId);
  } catch (e) {
    document.getElementById('run-detail').innerHTML =
      '<div class="empty" style="color:var(--bad)">erro: ' + escapeHtml(e.message) + '</div>';
  }
}

function openStream(runId) {
  if (currentEventSource) currentEventSource.close();
  const url = API + '/stream/' + runId;
  currentEventSource = new EventSource(url);
  const streamEl = document.getElementById('event-stream');
  streamEl.innerHTML = '';

  const render = (kind, data) => {
    const div = document.createElement('div');
    div.className = 'event';
    const payload = data && data.payload ? JSON.stringify(data.payload) : '';
    div.innerHTML = `
      <span class="kind">${escapeHtml(kind)}</span>
      <span class="payload">${escapeHtml(payload)}</span>
    `;
    streamEl.appendChild(div);
    streamEl.scrollTop = streamEl.scrollHeight;
  };

  ['run.created','run.started','run.step','run.finished','run.failed','run.cancelled'].forEach(kind => {
    currentEventSource.addEventListener(kind, (ev) => {
      try { render(kind, JSON.parse(ev.data)); }
      catch { render(kind, { raw: ev.data }); }
      if (['run.finished','run.failed','run.cancelled'].includes(kind)) {
        currentEventSource.close();
        refreshRuns();
      }
    });
  });

  currentEventSource.onerror = () => {
    currentEventSource.close();
  };
}

async function submitRun() {
  const agent = document.getElementById('new-agent').value.trim();
  const project = document.getElementById('new-project').value.trim();
  const inputRaw = document.getElementById('new-input').value;
  if (!agent) return alert('agent_id obrigatorio');
  let input;
  try { input = JSON.parse(inputRaw); }
  catch { return alert('input precisa ser JSON valido'); }
  const body = { project_id: project, agent_id: agent, input };
  try {
    const resp = await api('/run', { method: 'POST', body: JSON.stringify(body) });
    await refreshRuns();
    selectRun(resp.run_id);
  } catch (e) {
    alert('erro ao submeter: ' + e.message);
  }
}

async function cancelRun(runId) {
  try {
    await api('/cancel/' + runId, { method: 'POST' });
    setTimeout(() => selectRun(runId), 200);
  } catch (e) {
    alert('erro ao cancelar: ' + e.message);
  }
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

refreshRuns();
setInterval(refreshRuns, 5000);
</script>
</body>
</html>
"""
