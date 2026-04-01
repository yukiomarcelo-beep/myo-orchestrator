// MYO Ops UI — pipeline dinâmico
'use strict';

const STEP_KEYS   = ['opportunity','product','content','video','sales','performance'];
const STEP_LABELS = ['Análise','Produto','Conteúdo','Vídeo','Vendas','Performance'];
const STEP_NUMS   = ['01','02','03','04','05','06'];

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTimer;
function toast(msg, color = '#9ca3af') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.style.color = color;
  el.style.borderColor = color + '55';
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}

// ── Ações ─────────────────────────────────────────────────────────────────────
async function run() {
  const btn = document.getElementById('btn-run');
  if (btn) { btn.disabled = true; btn.style.opacity = '.5'; }
  toast('⏳ Iniciando melhoria…', '#10b981');
  try {
    const r = await fetch('/api/run-kaizen', { method: 'POST' });
    const d = await r.json();
    toast('🔁 ' + (d.message || 'Kaizen rodando'), '#10b981');
  } catch { toast('❌ Erro', '#ef4444'); }
  finally { if (btn) { btn.disabled = false; btn.style.opacity = '1'; } }
}

async function applySuggestion() {
  const btn = document.getElementById('btn-suggest');
  if (btn) { btn.disabled = true; btn.style.opacity = '.5'; }
  toast('🧠 Consultando…', '#a78bfa');
  try {
    const r = await fetch('/api/sugerir', { method: 'POST' });
    const d = await r.json();
    if (d.sugestao) {
      const s = d.sugestao;
      toast(`💡 Melhor: ${s.objetivo} / ${s.fase}`, '#10b981');
      // auto-preenche dropdowns do painel
      const os = document.getElementById('cfg-objetivo');
      const fs = document.getElementById('cfg-fase');
      if (os) os.value = s.objetivo;
      if (fs) fs.value = s.fase;
    } else {
      toast('⚠️ ' + (d.message || 'Histórico insuficiente'), '#f59e0b');
    }
  } catch { toast('❌ Erro', '#ef4444'); }
  finally { if (btn) { btn.disabled = false; btn.style.opacity = '1'; } }
}

async function toggleMode() {
  try {
    const r  = await fetch('/api/autonomous');
    const d  = await r.json();
    const r2 = await fetch('/api/autonomous', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: ((d.level ?? 0) + 1) % 3 }),
    });
    const d2 = await r2.json();
    const labels = { 0: '⏸ Manual', 1: '💡 Assistido', 2: '⚡ Autônomo' };
    const colors = { 0: '#9ca3af',  1: '#38bdf8',     2: '#f59e0b' };
    const lvl = d2.level ?? 0;
    const btn = document.getElementById('btn-mode');
    if (btn) {
      btn.textContent = labels[lvl];
      btn.style.color = colors[lvl];
      btn.style.borderColor = colors[lvl] + '55';
      btn.style.background  = colors[lvl] + '18';
    }
    toast(d2.message || 'Modo alterado', colors[lvl]);
  } catch { toast('❌ Erro', '#ef4444'); }
}

function openConfig() {
  const p = document.getElementById('config-panel');
  if (p) p.classList.toggle('open');
}
document.addEventListener('click', e => {
  const p = document.getElementById('config-panel');
  if (p && p.classList.contains('open') &&
      !p.contains(e.target) && !e.target.closest('[onclick="openConfig()"]')) {
    p.classList.remove('open');
  }
});

async function applyStrategy() {
  const objetivo = document.getElementById('cfg-objetivo')?.value;
  const fase     = document.getElementById('cfg-fase')?.value;
  if (!objetivo || !fase) return;
  toast(`⏳ Aplicando ${objetivo}…`, '#f59e0b');
  try {
    const r = await fetch('/api/estrategia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ objetivo, fase }),
    });
    const d = await r.json();
    toast((d.status === 'bloqueado' ? '🔒 ' : '✅ ') + (d.message || 'ok'),
           d.status === 'bloqueado' ? '#f59e0b' : '#10b981');
    document.getElementById('config-panel')?.classList.remove('open');
  } catch { toast('❌ Erro', '#ef4444'); }
}

async function startPipeline() {
  const obj = prompt('Objetivo do produto (ex: CFO Digital):', 'CFO Digital');
  if (!obj) return;
  toast('🚀 Iniciando pipeline…', '#06b6d4');
  try {
    const r = await fetch('/api/pipeline/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ objetivo: obj, mode: 'auto' }),
    });
    const d = await r.json();
    toast('🟢 ' + (d.message || 'Pipeline iniciado'), '#06b6d4');
  } catch { toast('❌ Erro', '#ef4444'); }
}

// Ação da "próxima ação" — chamada do botão Executar
async function executeAction() {
  const btn = document.getElementById('btn-execute');
  const js  = btn?.dataset.actionJs;
  if (js) { try { eval(js); } catch {} }
  else { run(); }
}

// ── Pipeline update ───────────────────────────────────────────────────────────
function _renderPipeline(produtos) {
  const steps = document.querySelectorAll('.step');
  if (!steps.length) return;

  // Reseta todos
  steps.forEach((el, i) => {
    el.className = 'step';
    const num   = el.querySelector('.step-num');
    const lbl   = el.querySelector('.step-label');
    const sub   = el.querySelector('.step-sub');
    if (num) num.textContent = STEP_NUMS[i];
    if (lbl) lbl.textContent = STEP_LABELS[i];
    if (sub) { sub.textContent = ''; sub.style.display = 'none'; }
  });

  if (!produtos || produtos.length === 0) return;

  // Pega o produto "mais avançado" para o pipeline principal
  const ativo = produtos.find(p => p.status === 'rodando')
             || produtos.find(p => p.status === 'error')
             || produtos[0];

  const faseIdx = STEP_KEYS.indexOf(ativo.fase_atual || '');

  steps.forEach((el, i) => {
    if (i < faseIdx) {
      el.classList.add('done');
    } else if (i === faseIdx) {
      el.classList.add(ativo.status === 'error' ? 'error' : 'active');
      const sub = el.querySelector('.step-sub');
      if (sub) {
        sub.style.display = 'block';
        sub.innerHTML = `<span>${ativo.produto || ''}</span> · <span>${ativo.progresso || 0}%</span>`;
      }
    }
  });
}

function _renderChips(produtos) {
  const stack = document.getElementById('produtos-stack');
  if (!stack) return;
  const icons  = { rodando:'🟡', done:'🟢', error:'🔴', idle:'⬛' };
  if (!produtos || produtos.length === 0) {
    stack.innerHTML = '';
    return;
  }
  stack.innerHTML = produtos.map(p => {
    const st = p.status || 'idle';
    const ic = icons[st] || '⬛';
    const prog = p.progresso ? ` ${p.progresso}%` : '';
    return `<span class="chip ${st}">${ic} ${p.produto || '?'} — ${p.fase_atual || ''}${prog}</span>`;
  }).join('');
}

// ── Polling ───────────────────────────────────────────────────────────────────
async function atualizarPipeline() {
  try {
    const r    = await fetch('/api/state');
    const data = await r.json();
    _renderPipeline(data.produtos || []);
    _renderChips(data.produtos || []);

    // Modo autônomo no botão
    const lvl = data.autonomous_level ?? (data.autonomous ? 2 : 0);
    const labels = { 0:'⏸ Manual', 1:'💡 Assistido', 2:'⚡ Autônomo' };
    const colors = { 0:'#9ca3af',  1:'#38bdf8',      2:'#f59e0b' };
    const btn = document.getElementById('btn-mode');
    if (btn) {
      btn.textContent = labels[lvl];
      btn.style.color = colors[lvl];
      btn.style.borderColor = colors[lvl] + '55';
      btn.style.background  = lvl > 0 ? colors[lvl] + '18' : '#111827';
    }
  } catch {}
}

// ── Uptime ────────────────────────────────────────────────────────────────────
const _t0 = Date.now();
function _uptime() {
  const s   = Math.floor((Date.now() - _t0) / 1000);
  const h   = Math.floor(s / 3600);
  const m   = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const el  = document.getElementById('strip-uptime');
  if (el) el.textContent = h > 0 ? `⏱ ${h}h ${m}m` : m > 0 ? `⏱ ${m}m ${sec}s` : `⏱ ${sec}s`;
}

// ── Init ──────────────────────────────────────────────────────────────────────
setInterval(atualizarPipeline, 2000);
setInterval(_uptime, 1000);
atualizarPipeline();
_uptime();
