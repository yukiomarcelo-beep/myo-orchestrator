/* ──────────────────────────────────────────────────────────────────────────
   MYO — app.js  v3
   Centro de Controle: modais · progresso · multi-ação · IA sugestões · log
   ────────────────────────────────────────────────────────────────────────── */

'use strict';

// ════════════════════════════════════════════════════════════════════════════
// 0. ESTADO GLOBAL
// ════════════════════════════════════════════════════════════════════════════

let _currentAction   = null;
let _lastLogSnapshot = '';

// Batch
let _batchQueue      = new Set();   // ids das ações selecionadas
let _batchRunning    = false;

// Progress
let _progressInterval = null;
let _progressDone     = false;


// ════════════════════════════════════════════════════════════════════════════
// 1. MODAIS
// ════════════════════════════════════════════════════════════════════════════

const MODALS = {

  idea: {
    title: '💡 Avaliar Nova Ideia',
    body: `
      <label>Descreva a ideia</label>
      <input id="f-ideia" type="text" placeholder="Ex: Agente de e-mails para e-commerce">
      <label>Nicho de mercado</label>
      <input id="f-nicho" type="text" placeholder="Ex: E-commerce, SaaS, Educação">
      <label>Público-alvo</label>
      <input id="f-publico" type="text" placeholder="Ex: Empreendedores, PMEs">
    `,
    submit: async () => {
      const ideia   = val('f-ideia');
      const nicho   = val('f-nicho');
      const publico = val('f-publico');
      if (!ideia) return { error: 'Descreva a ideia antes de enviar.' };
      return post('/api/new-idea', { ideia, nicho, publico });
    },
  },

  lead: {
    title: '👤 Novo Lead',
    body: `
      <label>Nome completo</label>
      <input id="f-nome"  type="text"  placeholder="Ex: João Silva">
      <label>E-mail (opcional)</label>
      <input id="f-email" type="email" placeholder="joao@empresa.com">
      <label>Score de qualificação</label>
      <div style="display:flex;align-items:center;gap:10px;margin-top:4px">
        <input id="f-score" type="range" min="0" max="100" value="60"
               oninput="document.getElementById('f-score-val').textContent=this.value"
               style="flex:1;accent-color:#a855f7">
        <span id="f-score-val" style="color:#a855f7;font-weight:700;min-width:26px;text-align:right">60</span>
      </div>
      <label>Temperatura</label>
      <select id="f-temp">
        <option value="quente">🔥 Quente</option>
        <option value="morno" selected>🌡 Morno</option>
        <option value="frio">❄️ Frio</option>
      </select>
    `,
    submit: async () => {
      const nome  = val('f-nome');
      if (!nome) return { error: 'Informe o nome do lead.' };
      const email = val('f-email');
      const score = parseInt(document.getElementById('f-score')?.value || '60');
      const temp  = document.getElementById('f-temp')?.value;
      return post('/api/add-lead', { nome, email, score, temperatura: temp });
    },
  },

  content: {
    title: '📊 Registrar Performance',
    body: `
      <label>Plataforma</label>
      <select id="f-platform">
        <option>Instagram</option><option>YouTube</option>
        <option>LinkedIn</option><option>TikTok</option><option>E-mail</option>
      </select>
      <label>Métrica principal</label>
      <input id="f-metric" type="text" placeholder="Ex: Taxa de abertura, Alcance">
      <label>Valor</label>
      <input id="f-mvalue" type="number" placeholder="Ex: 8.5">
      <label>Observação</label>
      <input id="f-obs" type="text" placeholder="Contexto opcional…">
    `,
    submit: async () => {
      const metric = val('f-metric');
      const value  = val('f-mvalue');
      if (!metric || !value) return { error: 'Preencha a métrica e o valor.' };
      return post('/api/log-performance', {
        platform: document.getElementById('f-platform')?.value,
        metric, value: parseFloat(value), obs: val('f-obs'),
      });
    },
  },

  market: {
    title: '🔍 Validar Mercado',
    body: `
      <label>Produto ou segmento</label>
      <input id="f-market-prod" type="text" placeholder="Ex: Curso de IA para PMEs">
      <label>Objetivo</label>
      <select id="f-market-obj">
        <option value="maximizar_receita">💰 Maximizar Receita</option>
        <option value="aumentar_conversao">🎯 Aumentar Conversão</option>
        <option value="equilibrio" selected>⚖️ Equilíbrio</option>
      </select>
      <p style="color:#475569;font-size:.75rem;margin:10px 0 0">O Opportunity Engine analisa demanda, concorrência e potencial.</p>
    `,
    submit: async () => {
      const produto = val('f-market-prod') || 'Validação de Mercado';
      return post('/api/run-pipeline', { objetivo: produto, modo: 'auto' });
    },
    withProgress: true,
    progressProduct: () => val('f-market-prod') || 'Validação de Mercado',
  },

  scenario: {
    title: '⚡ Simular Cenário',
    body: `
      <p style="color:#94a3b8;font-size:.82rem;margin:0 0 14px;line-height:1.6">
        Simula um ciclo completo — Oportunidade → Performance — com eventos reais no log (~9 segundos).
      </p>
      <label>Produto de referência (opcional)</label>
      <input id="f-sim-prod" type="text" placeholder="Ex: CFO Digital">
    `,
    submit: async () => post('/api/simulate', {}),
    withProgress: true,
    progressProduct: () => null,   // detecta pelo polling
  },

  margin: {
    title: '💰 Calcular Margem',
    body: `
      <label>Receita mensal (R$)</label>
      <input id="f-receita" type="number" placeholder="Ex: 15000">
      <label>Custo total (R$)</label>
      <input id="f-custo"   type="number" placeholder="Ex: 8500">
      <label>Unidades vendidas</label>
      <input id="f-units"   type="number" placeholder="Ex: 50">
    `,
    submit: async () => {
      const receita = parseFloat(val('f-receita') || '0');
      const custo   = parseFloat(val('f-custo')   || '0');
      const units   = parseFloat(val('f-units')   || '1');
      if (!receita) return { error: 'Informe a receita mensal.' };
      const lucro  = receita - custo;
      const margem = ((lucro / receita) * 100).toFixed(1);
      const ticket = units > 0 ? (receita / units).toFixed(2) : 0;
      const roi    = custo > 0 ? ((lucro / custo) * 100).toFixed(0) : '∞';
      addLog(`💰 Margem ${margem}% · Lucro R$${fmt(lucro)} · Ticket R$${fmt(ticket)}`);
      return {
        inline: `
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px">
            <div class="result-kpi"><span class="rk-label">Lucro</span><span class="rk-val" style="color:#4ade80">R$ ${fmt(lucro)}</span></div>
            <div class="result-kpi"><span class="rk-label">Margem</span><span class="rk-val" style="color:#a855f7">${margem}%</span></div>
            <div class="result-kpi"><span class="rk-label">Ticket Médio</span><span class="rk-val" style="color:#38bdf8">R$ ${fmt(ticket)}</span></div>
            <div class="result-kpi"><span class="rk-label">ROI</span><span class="rk-val" style="color:#fbbf24">${roi}%</span></div>
          </div>`,
      };
    },
  },

};

// ─── Abrir / Fechar ───────────────────────────────────────────────────────────

function openModal(type) {
  const def = MODALS[type];
  if (!def) return;
  _currentAction = type;

  document.getElementById('modal-title').textContent = def.title;
  document.getElementById('modal-body').innerHTML    = def.body;
  document.getElementById('modal-result').innerHTML  = '';
  document.getElementById('modal-result').style.display = 'none';
  document.getElementById('modal-submit').textContent = 'Executar';
  document.getElementById('modal-submit').disabled   = false;

  const m = document.getElementById('modal');
  m.classList.remove('hidden');
  requestAnimationFrame(() => m.classList.add('visible'));

  setTimeout(() => {
    const first = document.querySelector('#modal-body input, #modal-body textarea');
    if (first) first.focus();
  }, 120);
}

function closeModal() {
  const m = document.getElementById('modal');
  m.classList.remove('visible');
  setTimeout(() => m.classList.add('hidden'), 220);
  _currentAction = null;
}

document.addEventListener('click', e => {
  if (e.target === document.getElementById('modal')) closeModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

// ─── Submit ───────────────────────────────────────────────────────────────────

async function submitModal() {
  const def = MODALS[_currentAction];
  if (!def) return;

  const btn     = document.getElementById('modal-submit');
  btn.disabled  = true;
  btn.innerHTML = '<span class="spinner"></span> Executando…';

  showLoader(`⚙️ ${def.title.replace(/^\S+ /, '')}…`);

  try {
    const result = await def.submit();

    if (result?.error) {
      showModalResult(result.error, 'error');
    } else if (result?.inline) {
      showModalResult(result.inline, 'inline');
      addLog(`✓ ${def.title.replace(/^\S+ /, '')} concluído`);
    } else {
      const msg = result?.message || `${def.title.replace(/^\S+ /, '')} iniciado`;
      addLog(`✓ ${msg}`);
      closeModal();

      // Abre progresso se a ação usar pipeline/simulate
      if (def.withProgress) {
        const prod = def.progressProduct?.() || result?.produto || null;
        openProgress(def.title, prod);
      }
    }
  } catch {
    showModalResult('Erro ao conectar ao servidor.', 'error');
  } finally {
    btn.disabled  = false;
    btn.innerHTML = 'Executar';
    hideLoader();
  }
}

function showModalResult(html, type) {
  const el = document.getElementById('modal-result');
  el.innerHTML     = type === 'inline' ? html : `<div class="modal-err">${html}</div>`;
  el.style.display = 'block';
}


// ════════════════════════════════════════════════════════════════════════════
// 2. PROGRESSO REAL (barra tipo IA)
// ════════════════════════════════════════════════════════════════════════════

const PIPELINE_STAGES = [
  { id: 'opportunity', label: 'Análise de Oportunidade', icon: '🔍' },
  { id: 'product',     label: 'Criação de Produto',      icon: '📦' },
  { id: 'content',     label: 'Geração de Conteúdo',     icon: '✍️'  },
  { id: 'video',       label: 'Produção de Vídeo',       icon: '🎬' },
  { id: 'sales',       label: 'Motor de Vendas',         icon: '💰' },
  { id: 'performance', label: 'Performance & Memória',   icon: '📊' },
];

const STAGE_INDEX = Object.fromEntries(PIPELINE_STAGES.map((s, i) => [s.id, i]));

/**
 * Abre o painel de progresso e começa a monitorar via /api/state.
 * @param {string} title  — título exibido
 * @param {string|null} targetProduct — nome do produto a rastrear (null = detecta)
 */
function openProgress(title, targetProduct = null) {
  _progressDone = false;

  // Monta HTML das etapas
  const stagesHtml = PIPELINE_STAGES.map((s, i) => `
    <div class="prog-stage" id="ps-${s.id}" data-idx="${i}">
      <div class="ps-dot" id="psd-${s.id}">
        <span class="ps-spinner"></span>
        <span class="ps-check" style="display:none">✓</span>
        <span class="ps-num">${i + 1}</span>
      </div>
      <div class="ps-info">
        <span class="ps-icon">${s.icon}</span>
        <span class="ps-label">${s.label}</span>
        <span class="ps-time" id="pst-${s.id}"></span>
      </div>
    </div>`).join('');

  document.getElementById('prog-title').textContent = title;
  document.getElementById('prog-stages').innerHTML  = stagesHtml;
  document.getElementById('prog-bar-fill').style.width = '0%';
  document.getElementById('prog-pct').textContent   = '0%';
  document.getElementById('prog-status').textContent = 'Iniciando…';

  const panel = document.getElementById('progress-panel');
  panel.classList.remove('hidden');
  requestAnimationFrame(() => panel.classList.add('visible'));

  // Stage times
  const _stageTimes = {};

  // Polling
  let _lastFase = null; let _lastStatus = null;
  _progressInterval = setInterval(async () => {
    try {
      const data = await (await fetch('/api/state')).json();
      const produtos = data.produtos || [];

      // Encontra produto alvo
      let alvo = targetProduct
        ? produtos.find(p => p.produto === targetProduct)
        : produtos.find(p => p.status === 'rodando') || produtos[produtos.length - 1];

      if (!alvo) return;

      const fase   = alvo.fase_atual || 'idle';
      const status = alvo.status || 'idle';
      const prog   = alvo.progresso || 0;
      const idx    = STAGE_INDEX[fase] ?? -1;

      if (fase !== _lastFase || status !== _lastStatus) {
        _lastFase = fase; _lastStatus = status;
        if (!_stageTimes[fase]) _stageTimes[fase] = Date.now();
      }

      // Atualiza visuais das etapas
      PIPELINE_STAGES.forEach((s, i) => {
        const dotEl   = document.getElementById(`psd-${s.id}`);
        const timeEl  = document.getElementById(`pst-${s.id}`);
        const stageEl = document.getElementById(`ps-${s.id}`);
        if (!dotEl) return;

        const spinner = dotEl.querySelector('.ps-spinner');
        const check   = dotEl.querySelector('.ps-check');
        const num     = dotEl.querySelector('.ps-num');

        if (i < idx || (i === idx && status === 'done')) {
          // Concluído
          stageEl.className = 'prog-stage done';
          spinner.style.display = 'none';
          check.style.display   = 'inline';
          num.style.display     = 'none';
          if (_stageTimes[s.id] && !timeEl.textContent) {
            const elapsed = ((Date.now() - _stageTimes[s.id]) / 1000).toFixed(1);
            timeEl.textContent = `${elapsed}s`;
          }
        } else if (i === idx && status === 'rodando') {
          // Ativo
          stageEl.className = 'prog-stage active';
          spinner.style.display = 'inline-block';
          check.style.display   = 'none';
          num.style.display     = 'none';
          timeEl.textContent    = '';
        } else {
          // Pendente
          stageEl.className = 'prog-stage';
          spinner.style.display = 'none';
          check.style.display   = 'none';
          num.style.display     = 'inline';
        }
      });

      // Barra de progresso
      let pct = idx >= 0 ? Math.round(((idx + (status === 'done' ? 1 : 0.5)) / PIPELINE_STAGES.length) * 100) : prog;
      pct = Math.max(0, Math.min(100, pct));
      document.getElementById('prog-bar-fill').style.width = pct + '%';
      document.getElementById('prog-pct').textContent = pct + '%';

      // Status text
      if (status === 'rodando' && idx >= 0) {
        document.getElementById('prog-status').textContent =
          `${PIPELINE_STAGES[idx].icon} ${PIPELINE_STAGES[idx].label}…`;
      } else if (status === 'done' || fase === 'idle') {
        document.getElementById('prog-status').textContent = '✓ Concluído!';
        document.getElementById('prog-bar-fill').style.width = '100%';
        document.getElementById('prog-pct').textContent = '100%';
        _finishProgress();
      } else if (status === 'error') {
        document.getElementById('prog-status').textContent = '✗ Erro na execução';
        document.getElementById('prog-bar-fill').style.background =
          'linear-gradient(90deg, #ef4444, #f87171)';
        _finishProgress();
      }
    } catch { /* silencioso */ }
  }, 800);
}

function _finishProgress() {
  if (_progressDone) return;
  _progressDone = true;
  clearInterval(_progressInterval);
  setTimeout(closeProgress, 2500);
}

function closeProgress() {
  clearInterval(_progressInterval);
  _progressDone = true;
  const panel = document.getElementById('progress-panel');
  panel.classList.remove('visible');
  setTimeout(() => panel.classList.add('hidden'), 280);
}


// ════════════════════════════════════════════════════════════════════════════
// 3. MULTI-AÇÃO (batch)
// ════════════════════════════════════════════════════════════════════════════

const BATCH_ACTIONS = [
  { id: 'pipeline',  label: 'Rodar Pipeline',  icon: '🚀', endpoint: 'run-pipeline', params: { objetivo: 'CFO Digital', modo: 'auto' }, withProgress: true },
  { id: 'simulate',  label: 'Simular Ciclo',   icon: '⚡', endpoint: 'simulate',     params: {},                                         withProgress: true },
  { id: 'market',    label: 'Validar Mercado', icon: '🔍', endpoint: 'run-pipeline', params: { objetivo: 'Validação de Mercado', modo: 'auto' }, withProgress: true },
  { id: 'kaizen',    label: 'Rodar Kaizen',    icon: '🔁', endpoint: 'run-kaizen',   params: {} },
];

function toggleBatch(id) {
  const chip = document.getElementById(`batch-${id}`);
  if (!chip) return;

  if (_batchQueue.has(id)) {
    _batchQueue.delete(id);
    chip.classList.remove('selected');
  } else {
    _batchQueue.add(id);
    chip.classList.add('selected');
  }
  _updateBatchBtn();
}

function _updateBatchBtn() {
  const btn = document.getElementById('btn-run-batch');
  if (!btn) return;
  const n = _batchQueue.size;
  btn.disabled = n === 0 || _batchRunning;
  btn.textContent = n === 0
    ? '▶ Selecione ações acima'
    : `▶ Executar ${n} ação${n > 1 ? 'ões' : ''} em sequência`;
}

async function runBatch() {
  if (_batchQueue.size === 0 || _batchRunning) return;
  _batchRunning = true;

  const btn = document.getElementById('btn-run-batch');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Executando sequência…'; }

  const toRun = BATCH_ACTIONS.filter(a => _batchQueue.has(a.id));
  let firstWithProgress = null;

  for (const action of toRun) {
    addLog(`⏳ Iniciando: ${action.label}…`);
    showLoader(`${action.icon} ${action.label}…`);
    try {
      const r = await post(`/api/${action.endpoint}`, action.params);
      addLog(`✓ ${r.message || action.label + ' iniciado'}`);
      if (action.withProgress && !firstWithProgress) {
        firstWithProgress = action;
        openProgress(action.label, r.produto || null);
      }
    } catch {
      addLog(`✗ Erro: ${action.label}`);
    }
    hideLoader();
    await _sleep(600);   // pequena pausa entre ações
  }

  _batchRunning = false;
  _batchQueue.clear();
  document.querySelectorAll('.batch-chip').forEach(c => c.classList.remove('selected'));
  _updateBatchBtn();
}

function _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }


// ════════════════════════════════════════════════════════════════════════════
// 4. IA SUGERINDO AÇÕES
// ════════════════════════════════════════════════════════════════════════════

async function loadSuggestions() {
  const container = document.getElementById('ai-suggestions');
  if (!container) return;

  try {
    const data = await (await fetch('/api/suggest-actions')).json();
    const sug  = data.sugestoes || [];

    if (!sug.length) {
      container.innerHTML = '<div class="ai-empty">Nenhuma sugestão disponível agora.</div>';
      return;
    }

    container.innerHTML = sug.map((s, i) => `
      <div class="ai-card" style="--ai-cor: ${s.cor}; animation-delay: ${i * 80}ms">
        <div class="ai-card-left">
          <span class="ai-icon">${s.icon}</span>
          <div class="ai-text">
            <div class="ai-title">${s.titulo}</div>
            <div class="ai-motivo">${s.motivo}</div>
          </div>
        </div>
        ${s.endpoint
          ? `<button class="btn-ai-exec" onclick="execSuggestion('${s.endpoint}', ${JSON.stringify(s.params || {}).replace(/'/g, '&#39;')}, '${s.titulo}')">
               Executar →
             </button>`
          : s.acao_js
          ? `<button class="btn-ai-exec" onclick="${s.acao_js}">Executar →</button>`
          : `<span class="ai-ok">✓ OK</span>`
        }
      </div>`).join('');
  } catch {
    container.innerHTML = '<div class="ai-empty">Erro ao carregar sugestões.</div>';
  }
}

async function execSuggestion(endpoint, params, title) {
  showLoader(`⏳ ${title}…`);
  addLog(`🧠 IA disparou: ${title}`);
  try {
    const r = await post(`/api/${endpoint}`, params);
    addLog(`✓ ${r.message || title + ' iniciado'}`);
    if (endpoint === 'run-pipeline' || endpoint === 'simulate') {
      openProgress(title, r.produto || null);
    }
  } catch {
    addLog(`✗ Erro: ${title}`);
  } finally {
    hideLoader();
  }
}

// Recarrega sugestões periodicamente
setInterval(loadSuggestions, 30_000);


// ════════════════════════════════════════════════════════════════════════════
// 5. AÇÕES DIRETAS
// ════════════════════════════════════════════════════════════════════════════

async function runPipeline() {
  showLoader('🚀 Iniciando pipeline…');
  addLog('🚀 Pipeline solicitado…');
  try {
    const r = await post('/api/run-pipeline', { objetivo: 'CFO Digital', modo: 'auto' });
    addLog(`✓ ${r.message || 'Pipeline iniciado'}`);
    openProgress('Rodar Pipeline', r.produto || 'CFO Digital');
  } catch {
    addLog('✗ Erro ao iniciar pipeline');
  } finally {
    hideLoader();
  }
}

function openCRM() { window.location.href = '/crm'; }


// ════════════════════════════════════════════════════════════════════════════
// 6. HELPERS
// ════════════════════════════════════════════════════════════════════════════

function val(id) { return (document.getElementById(id)?.value || '').trim(); }

function fmt(n) {
  return Number(n).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}


// ════════════════════════════════════════════════════════════════════════════
// 7. LOADER
// ════════════════════════════════════════════════════════════════════════════

function showLoader(msg = '⚙️ Executando…') {
  const text = document.getElementById('loader-text');
  const el   = document.getElementById('loader');
  if (text) text.textContent = msg;
  if (el)   el.classList.remove('hidden');
}

function hideLoader() {
  document.getElementById('loader')?.classList.add('hidden');
}


// ════════════════════════════════════════════════════════════════════════════
// 8. LOG AO VIVO
// ════════════════════════════════════════════════════════════════════════════

function addLog(msg) {
  const log  = document.getElementById('log');
  if (!log) return;
  const el   = document.createElement('div');
  el.className = 'log-entry new';
  const time = new Date().toLocaleTimeString('pt-BR', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
  el.innerHTML = `<span class="log-ts">${time}</span><span class="log-msg">${msg}</span>`;
  log.prepend(el);
  while (log.children.length > 60) log.removeChild(log.lastChild);
  setTimeout(() => el.classList.remove('new'), 600);
}

function _syncServerLog() {
  fetch('/api/log?n=20')
    .then(r => r.json())
    .then(entries => {
      if (!entries?.length) return;
      const snap = entries.slice(0, 5).map(e => e.ts + e.evento).join('|');
      if (snap === _lastLogSnapshot) return;
      _lastLogSnapshot = snap;

      const log = document.getElementById('log');
      if (!log) return;

      const existing = new Set(
        Array.from(log.querySelectorAll('[data-key]')).map(el => el.dataset.key)
      );

      entries.forEach(e => {
        const key = e.ts + e.evento;
        if (existing.has(key)) return;
        const el = document.createElement('div');
        el.className  = 'log-entry server-entry';
        el.dataset.key = key;
        const cls = { ok:'log-ok', error:'log-error', warn:'log-warn' }[e.status] || '';
        el.innerHTML = `<span class="log-ts">${e.ts}</span>`
                     + `<span class="log-prod">${e.produto}</span>`
                     + `<span class="log-msg ${cls}">${e.evento}</span>`;
        log.appendChild(el);
      });

      // Ordena: mais recente no topo
      const items = Array.from(log.children);
      items.sort((a, b) => {
        const ta = a.querySelector('.log-ts')?.textContent || '';
        const tb = b.querySelector('.log-ts')?.textContent || '';
        return tb.localeCompare(ta);
      });
      items.forEach(el => log.appendChild(el));
      while (log.children.length > 60) log.removeChild(log.lastChild);
    })
    .catch(() => {});
}

setInterval(_syncServerLog, 2500);
_syncServerLog();
