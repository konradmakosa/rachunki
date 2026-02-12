const API_BASE = '/api';

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

export async function scanGdrive() {
  const res = await fetch(`${API_BASE}/scan-gdrive`, { method: 'POST' });
  return res.json();
}

export async function processFile(filepath, useAi = false) {
  const params = new URLSearchParams({ filepath, use_ai: useAi });
  const res = await fetch(`${API_BASE}/process?${params}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Processing failed');
  }
  return res.json();
}

export async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
  return res.json();
}

export async function fetchDocuments(provider = null) {
  const params = provider ? `?provider=${provider}` : '';
  const res = await fetch(`${API_BASE}/documents${params}`);
  return res.json();
}

export async function fetchConsumption({ provider, utilityType, location, includeEstimates } = {}) {
  const params = new URLSearchParams();
  if (provider) params.set('provider', provider);
  if (utilityType) params.set('utility_type', utilityType);
  if (location) params.set('location', location);
  if (includeEstimates !== undefined) params.set('include_estimates', includeEstimates);
  const res = await fetch(`${API_BASE}/consumption?${params}`);
  return res.json();
}

export async function fetchChartData({ utilityType, location } = {}) {
  const params = new URLSearchParams();
  if (utilityType) params.set('utility_type', utilityType);
  if (location) params.set('location', location);
  try {
    const res = await fetch(`${API_BASE}/consumption/chart?${params}`);
    if (res.ok) return res.json();
  } catch (_) { /* API unavailable — fall back to static data */ }
  // Static fallback for GitHub Pages
  const res = await fetch(`${import.meta.env.BASE_URL}chart-data.json`);
  const data = await res.json();
  // Client-side filtering when using static data
  if (location) {
    data.series = data.series.filter(s => s.location === location);
  }
  if (utilityType) {
    data.series = data.series.filter(s => s.utility_type === utilityType);
  }
  return data;
}

export async function fetchCostComponents(recordId) {
  const res = await fetch(`${API_BASE}/cost-components/${recordId}`);
  return res.json();
}

export async function resetData() {
  const res = await fetch(`${API_BASE}/data/reset`, { method: 'DELETE' });
  return res.json();
}
