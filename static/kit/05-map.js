// ============================================================
// 05-map.js — adaptado para MYO
// Dark tiles Stadia + popups com tema roxo MYO
// Requer: Leaflet CSS + JS carregados antes deste arquivo
// ============================================================

const MYO_TILE_URL  = 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png';
const MYO_TILE_ATTR = '&copy; Stadia Maps &copy; OpenMapTiles &copy; OpenStreetMap';

const MYO_MAP_STYLES = `
  .leaflet-container {
    background: #0e0228 !important;
    border-radius: 12px;
    border: 1px solid rgba(74,32,149,0.4);
  }
  .leaflet-tile-pane {
    filter: brightness(0.75) saturate(0.5) hue-rotate(230deg);
  }
  .myo-map-popup {
    background: #1f0a4e;
    border: 1px solid rgba(112,64,200,0.6);
    border-radius: 10px;
    padding: 10px 14px;
    min-width: 160px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.6);
  }
  .myo-map-popup-title {
    font-size: 12px;
    font-weight: 700;
    color: #f0e8ff;
    margin-bottom: 6px;
    letter-spacing: 0.04em;
  }
  .myo-map-popup-row {
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: #8a6aaa;
    margin-bottom: 3px;
  }
  .myo-map-popup-value {
    color: #00e5ff;
    font-weight: 600;
  }
  .leaflet-popup-content-wrapper {
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
  }
  .leaflet-popup-content { margin: 0 !important; }
  .leaflet-popup-tip-container { display: none; }
  .leaflet-control-zoom a {
    background: #1f0a4e !important;
    color: #b89ed8 !important;
    border-color: rgba(112,64,200,0.4) !important;
  }
  .leaflet-control-zoom a:hover {
    background: #280d60 !important;
    color: #00e5ff !important;
  }
`;

function myoInjectMapStyles() {
  if (document.getElementById('myo-map-styles')) return;
  const style = document.createElement('style');
  style.id = 'myo-map-styles';
  style.textContent = MYO_MAP_STYLES;
  document.head.appendChild(style);
}

// Pontos padrão com dados MYO
const MYO_DEFAULT_POINTS = [
  {
    name: 'São Paulo',
    lat: -23.5505, lng: -46.6333,
    color: '#c060ff', radius: 18,
    data: { Receita: 'R$ 84k', Leads: '1.240', Status: 'Ativo' }
  },
  {
    name: 'Rio de Janeiro',
    lat: -22.9068, lng: -43.1729,
    color: '#00e5ff', radius: 14,
    data: { Receita: 'R$ 52k', Leads: '870', Status: 'Ativo' }
  },
  {
    name: 'Brasília',
    lat: -15.7801, lng: -47.9292,
    color: '#00ffc8', radius: 10,
    data: { Receita: 'R$ 28k', Leads: '430', Status: 'Crescendo' }
  },
  {
    name: 'Florianópolis',
    lat: -27.5954, lng: -48.5480,
    color: '#ffb800', radius: 10,
    data: { Receita: 'R$ 18k', Leads: '280', Status: 'Imóveis SC' }
  },
  {
    name: 'Belo Horizonte',
    lat: -19.9167, lng: -43.9345,
    color: '#ff4db8', radius: 10,
    data: { Receita: 'R$ 14k', Leads: '210', Status: 'Expansão' }
  },
];

// ── FUNÇÃO PRINCIPAL ─────────────────────────────────────────
function initDashboardMap(containerId, points, options = {}) {
  myoInjectMapStyles();

  const pts = points || MYO_DEFAULT_POINTS;

  const cfg = {
    center: [-15.5, -52.0],
    zoom: 4, minZoom: 3, maxZoom: 10,
    ...options,
  };

  const map = L.map(containerId, {
    center: cfg.center,
    zoom: cfg.zoom,
    minZoom: cfg.minZoom,
    maxZoom: cfg.maxZoom,
    zoomControl: false,
    attributionControl: false,
  });

  L.tileLayer(MYO_TILE_URL, { attribution: MYO_TILE_ATTR }).addTo(map);
  L.control.zoom({ position: 'bottomright' }).addTo(map);

  pts.forEach(pt => {
    // Halo externo (glow)
    L.circleMarker([pt.lat, pt.lng], {
      radius: (pt.radius || 10) + 8,
      color: pt.color, fillColor: pt.color,
      fillOpacity: 0.08, weight: 1, opacity: 0.3,
    }).addTo(map);

    // Círculo principal
    const marker = L.circleMarker([pt.lat, pt.lng], {
      radius: pt.radius || 10,
      color: pt.color, fillColor: pt.color,
      fillOpacity: 0.8, weight: 2,
    }).addTo(map);

    // Popup
    const rows = Object.entries(pt.data || {})
      .map(([k,v]) => `<div class="myo-map-popup-row">
        <span>${k}</span>
        <span class="myo-map-popup-value">${v}</span>
      </div>`).join('');

    marker.bindPopup(`
      <div class="myo-map-popup">
        <div class="myo-map-popup-title">${pt.name}</div>
        ${rows}
      </div>
    `, { className: 'myo-map-popup-wrapper', maxWidth: 210 });

    marker.on('add', () => {
      const el = marker.getElement();
      if (el) {
        el.style.transition = 'transform 0.15s ease';
        el.addEventListener('mouseenter', () => { el.style.transform = 'scale(1.3)'; });
        el.addEventListener('mouseleave', () => { el.style.transform = 'scale(1)'; });
      }
    });
  });

  return map;
}

// Atualiza pontos no mapa existente
function updateMapPoints(map, newPoints) {
  map.eachLayer(layer => {
    if (layer instanceof L.CircleMarker) map.removeLayer(layer);
  });
  newPoints.forEach(pt => {
    L.circleMarker([pt.lat, pt.lng], {
      radius: pt.radius || 10,
      color: pt.color || '#c060ff',
      fillColor: pt.color || '#c060ff',
      fillOpacity: 0.8, weight: 2,
    }).addTo(map);
  });
}
