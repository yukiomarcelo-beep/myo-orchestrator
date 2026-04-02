const BASE = '/api';

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export const api = {
  kpis:     () => get('/kpis'),
  pipeline: () => get('/pipeline'),
  status:   () => get('/status'),
  log:      (n = 20) => get(`/log?n=${n}`)
};
