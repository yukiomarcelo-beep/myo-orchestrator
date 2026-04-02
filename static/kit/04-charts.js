// ============================================================
// 04-charts.js — adaptado para MYO
// Paleta roxa/neon do MYO. Fonte: Inter (já carregada no MYO).
// Chart.js já está em /chart.umd.min.js — não reimportar.
// ============================================================

const MYO_COLORS = {
  purple: '#c060ff',   // --purple MYO
  blue:   '#5b9cff',   // --blue MYO
  cyan:   '#00e5ff',   // --cyan MYO
  green:  '#00ffc8',   // --teal MYO
  pink:   '#ff4db8',   // --pink MYO
  orange: '#ffb800',   // --amber MYO
  red:    '#ff4444',   // --red MYO
  yellow: '#ffb800',
  teal:   '#00ffc8',
  indigo: '#7040c8',
};

// Converte hex → rgba
function myoHexRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── DEFAULTS GLOBAIS ─────────────────────────────────────────
if (typeof Chart !== 'undefined') {
  Chart.defaults.color           = '#8a6aaa';      // --muted MYO
  Chart.defaults.borderColor     = 'rgba(74,32,149,0.25)';
  Chart.defaults.font.family     = "'Inter', system-ui, sans-serif";
  Chart.defaults.font.size       = 11;
  Chart.defaults.plugins.legend.display        = false;
  Chart.defaults.plugins.tooltip.backgroundColor = '#1f0a4e';  // --c1 MYO
  Chart.defaults.plugins.tooltip.borderColor     = 'rgba(112,64,200,0.5)';
  Chart.defaults.plugins.tooltip.borderWidth     = 1;
  Chart.defaults.plugins.tooltip.padding         = 10;
  Chart.defaults.plugins.tooltip.titleColor      = '#f0e8ff';
  Chart.defaults.plugins.tooltip.bodyColor       = '#b89ed8';
  Chart.defaults.plugins.tooltip.cornerRadius    = 8;
}

// ── 1. ÁREA (3 séries com fill gradiente) ───────────────────
function myoAreaChart(canvasId, customData = null) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const labels = customData?.labels ||
    ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];

  const data = customData || {
    series1: [40,55,45,70,65,80,72,88,76,92,85,95],
    series2: [30,40,35,50,48,60,55,68,60,72,65,78],
    series3: [20,28,22,35,32,45,40,52,44,58,50,62],
  };

  const mkGrad = (hex, a0, a1) => {
    const g = ctx.createLinearGradient(0,0,0,canvas.offsetHeight || 220);
    g.addColorStop(0, myoHexRgba(hex, a0));
    g.addColorStop(1, myoHexRgba(hex, a1));
    return g;
  };

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: data.label1 || 'Série 1',
          data: data.series1,
          borderColor: MYO_COLORS.purple,
          backgroundColor: mkGrad(MYO_COLORS.purple, 0.5, 0.0),
          borderWidth: 2, fill: true, tension: 0.45,
          pointRadius: 0, pointHoverRadius: 5,
          pointHoverBackgroundColor: MYO_COLORS.purple,
        },
        {
          label: data.label2 || 'Série 2',
          data: data.series2,
          borderColor: MYO_COLORS.cyan,
          backgroundColor: mkGrad(MYO_COLORS.cyan, 0.35, 0.0),
          borderWidth: 2, fill: true, tension: 0.45,
          pointRadius: 0, pointHoverRadius: 5,
          pointHoverBackgroundColor: MYO_COLORS.cyan,
        },
        {
          label: data.label3 || 'Série 3',
          data: data.series3,
          borderColor: MYO_COLORS.pink,
          backgroundColor: mkGrad(MYO_COLORS.pink, 0.25, 0.0),
          borderWidth: 2, fill: true, tension: 0.45,
          pointRadius: 0, pointHoverRadius: 5,
          pointHoverBackgroundColor: MYO_COLORS.pink,
        },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { grid: { color: 'rgba(74,32,149,0.15)', drawBorder: false }, ticks: { color: '#8a6aaa' } },
        y: { grid: { color: 'rgba(74,32,149,0.15)', drawBorder: false }, ticks: { color: '#8a6aaa' }, beginAtZero: true },
      },
      plugins: { legend: { display: false } }
    }
  });
}

// ── 2. DONUT com valor central ───────────────────────────────
function myoDonutChart(canvasId, customData = null) {
  const ctx = document.getElementById(canvasId)?.getContext('2d');
  if (!ctx) return;

  const data = customData || {
    labels: ['Produto A', 'Produto B', 'Produto C', 'Outros'],
    values: [40, 30, 20, 10],
    centerLabel: 'TOTAL',
  };

  return new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.labels,
      datasets: [{
        data: data.values,
        backgroundColor: [MYO_COLORS.purple, MYO_COLORS.cyan, MYO_COLORS.pink, MYO_COLORS.orange],
        borderColor: '#1f0a4e',
        borderWidth: 3,
        hoverBorderWidth: 0,
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '72%',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => ` ${c.label}: ${c.parsed}%` } }
      }
    },
    plugins: [{
      id: 'myoCenterText',
      beforeDraw(chart) {
        const { width, height, ctx } = chart;
        ctx.save();
        const total = data.values.reduce((a,b) => a+b, 0);
        ctx.font = 'bold 22px Inter, sans-serif';
        ctx.fillStyle = '#f0e8ff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(total + (data.centerSuffix || '%'), width / 2, height / 2 - 8);
        ctx.font = '10px Inter, sans-serif';
        ctx.fillStyle = '#8a6aaa';
        ctx.fillText(data.centerLabel || 'TOTAL', width / 2, height / 2 + 14);
        ctx.restore();
      }
    }]
  });
}

// ── 3. BARRAS VERTICAIS com gradiente MYO ───────────────────
function myoBarChart(canvasId, customData = null) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const labels = customData?.labels || ['Jan','Fev','Mar','Abr','Mai','Jun','Jul'];
  const values = customData?.values || [65,78,52,91,84,73,96];

  const barGrad = ctx.createLinearGradient(0,0,0,canvas.offsetHeight || 160);
  barGrad.addColorStop(0, MYO_COLORS.purple);
  barGrad.addColorStop(1, MYO_COLORS.cyan);

  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: customData?.label || 'Valor',
        data: values,
        backgroundColor: barGrad,
        borderRadius: 6, borderSkipped: false, borderWidth: 0,
        hoverBackgroundColor: myoHexRgba(MYO_COLORS.purple, 0.85),
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { grid: { display: false }, ticks: { color: '#8a6aaa' } },
        y: { grid: { color: 'rgba(74,32,149,0.15)', drawBorder: false }, ticks: { color: '#8a6aaa' }, beginAtZero: true },
      },
      plugins: { legend: { display: false } }
    }
  });
}

// ── 4. LINHA NEON multi-série (sem fill) ─────────────────────
function myoLineChart(canvasId, customData = null) {
  const ctx = document.getElementById(canvasId)?.getContext('2d');
  if (!ctx) return;

  const labels = customData?.labels ||
    Array.from({length: 16}, (_,i) => `S${i+1}`);

  const data = customData || {
    series1: [12,19,8,25,22,30,28,38,35,42,40,50,48,55,52,60],
    series2: [5,10,6,14,12,20,18,26,22,30,28,35,32,40,38,44],
  };

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: data.label1 || 'Linha 1',
          data: data.series1,
          borderColor: MYO_COLORS.cyan,
          backgroundColor: 'transparent',
          borderWidth: 2, tension: 0.4,
          pointRadius: 0, pointHoverRadius: 4,
        },
        {
          label: data.label2 || 'Linha 2',
          data: data.series2,
          borderColor: MYO_COLORS.purple,
          backgroundColor: 'transparent',
          borderWidth: 2, tension: 0.4,
          pointRadius: 0, pointHoverRadius: 4,
          borderDash: [4,4],
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { grid: { color: 'rgba(74,32,149,0.10)', drawBorder: false }, ticks: { color: '#8a6aaa', maxTicksLimit: 8 } },
        y: { grid: { color: 'rgba(74,32,149,0.15)', drawBorder: false }, ticks: { color: '#8a6aaa' } },
      },
      plugins: { legend: { display: false } }
    }
  });
}

// ── 5. HORIZONTAL BAR (ranking) ──────────────────────────────
function myoHBarChart(canvasId, customData = null) {
  const ctx = document.getElementById(canvasId)?.getContext('2d');
  if (!ctx) return;

  const labels = customData?.labels || ['Produto A','Produto B','Produto C','Produto D','Produto E'];
  const values = customData?.values || [92,78,85,67,54];

  const colors = [MYO_COLORS.purple, MYO_COLORS.cyan, MYO_COLORS.pink, MYO_COLORS.orange, MYO_COLORS.green];

  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Score',
        data: values,
        backgroundColor: colors.map(c => myoHexRgba(c, 0.7)),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { grid: { color: 'rgba(74,32,149,0.15)', drawBorder: false }, ticks: { color: '#8a6aaa' }, max: 100 },
        y: { grid: { display: false }, ticks: { color: '#b89ed8', font: { size: 11 } } },
      },
      plugins: { legend: { display: false } }
    }
  });
}

// ── 6. SPARKLINE (mini — KPI card) ──────────────────────────
function myoSparkline(canvasId, values, color = MYO_COLORS.cyan) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const grad = ctx.createLinearGradient(0,0,0,canvas.offsetHeight || 34);
  grad.addColorStop(0, myoHexRgba(color, 0.45));
  grad.addColorStop(1, myoHexRgba(color, 0.0));

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: values.map((_,i) => i),
      datasets: [{
        data: values,
        borderColor: color,
        backgroundColor: grad,
        borderWidth: 1.5,
        fill: true,
        tension: 0.4,
        pointRadius: 0,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: { x: { display: false }, y: { display: false } },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      animation: { duration: 500 },
    }
  });
}

/* ── ALIASES (compatibilidade com 06-demo.html) ──────────────
   Mantém os nomes originais apontando para as versões MYO     */
const createAreaChart  = myoAreaChart;
const createDonutChart = myoDonutChart;
const createBarChart   = myoBarChart;
const createLineChart  = myoLineChart;
const createHBarChart  = myoHBarChart;
const createSparkline  = myoSparkline;
const COLORS           = MYO_COLORS;
