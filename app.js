const SERVICE_URL = 'https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer';
const AUTO_REFRESH_MS = 120_000;

const DEFAULT_LAYERS = [
  {
    id: 1,
    key: 'flooding',
    label: 'Reported Street Flooding',
    color: '#42a5ff',
    enabled: true,
    probable: false,
  },
];

const state = {
  layers: structuredClone(DEFAULT_LAYERS),
  layerGroups: new Map(),
  reports: [],
  metadata: null,
  lastQueryUrl: null,
  timer: null,
};

const map = L.map('map', {
  zoomControl: true,
  preferCanvas: true,
}).setView([29.9511, -90.0715], 12);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  maxZoom: 20,
  attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
}).addTo(map);

const els = {
  refreshBtn: document.getElementById('refreshBtn'),
  autoRefreshToggle: document.getElementById('autoRefreshToggle'),
  statusLine: document.getElementById('statusLine'),
  updatedLine: document.getElementById('updatedLine'),
  layerControls: document.getElementById('layerControls'),
  reportCount: document.getElementById('reportCount'),
  reportList: document.getElementById('reportList'),
  serviceUrlCode: document.getElementById('serviceUrlCode'),
  lastQueryCode: document.getElementById('lastQueryCode'),
  metadataPreview: document.getElementById('metadataPreview'),
};

els.serviceUrlCode.textContent = SERVICE_URL;
els.refreshBtn.addEventListener('click', () => refreshAll({ fitBounds: false }));
els.autoRefreshToggle.addEventListener('change', configureAutoRefresh);

init();

async function init() {
  renderLayerControls();
  configureAutoRefresh();
  await refreshAll({ fitBounds: true });
}

async function refreshAll({ fitBounds = false } = {}) {
  setStatus('Loading Streetwise flood layer…');
  clearMap();

  try {
    await loadMetadata();
    const enabledLayers = state.layers.filter((layer) => layer.enabled);
    const responses = await Promise.allSettled(enabledLayers.map(queryLayer));
    const reports = [];
    const errors = [];

    responses.forEach((response, index) => {
      const layer = enabledLayers[index];
      if (response.status === 'fulfilled') reports.push(...response.value);
      else errors.push(`${layer.label}: ${response.reason?.message || response.reason}`);
    });

    reports.sort((a, b) => (b.timeValue || 0) - (a.timeValue || 0));
    state.reports = reports;
    renderReports();
    renderLayerControls();
    if (fitBounds) fitToReports(reports);

    const activeText = `${reports.length} active flood report${reports.length === 1 ? '' : 's'}`;
    if (errors.length) {
      setStatus(`${activeText}; ${errors.length} layer error${errors.length === 1 ? '' : 's'}`, true);
      console.warn('Streetwise layer errors:', errors);
    } else {
      setStatus(activeText);
    }

    els.updatedLine.textContent = `Last update: ${new Date().toLocaleString()}`;
  } catch (error) {
    console.error(error);
    setStatus(`Error: ${error.message}`, true);
  }
}

async function loadMetadata() {
  if (state.metadata) return state.metadata;
  const url = `${SERVICE_URL}?f=pjson`;
  const metadata = await fetchJson(url);
  state.metadata = metadata;

  if (Array.isArray(metadata.layers)) {
    state.layers = state.layers.map((layer) => {
      const metaLayer = metadata.layers.find((candidate) => candidate.id === layer.id);
      return { ...layer, serviceName: metaLayer?.name || null };
    });
    els.metadataPreview.textContent = metadata.layers.map((layer) => `${layer.id}: ${layer.name}`).join('\n');
  } else {
    els.metadataPreview.textContent = JSON.stringify(metadata, null, 2).slice(0, 2400);
  }
  return metadata;
}

async function queryLayer(layer) {
  const params = new URLSearchParams({
    f: 'json',
    where: '1=1',
    returnGeometry: 'true',
    spatialRel: 'esriSpatialRelIntersects',
    outFields: '*',
    outSR: '4326',
  });
  const url = `${SERVICE_URL}/${layer.id}/query?${params.toString()}`;
  state.lastQueryUrl = url;
  els.lastQueryCode.textContent = url;

  const data = await fetchJson(url);
  if (data.error) throw new Error(data.error.message || JSON.stringify(data.error));

  const features = Array.isArray(data.features) ? data.features : [];
  layer.count = features.length;
  return features.map((feature) => normalizeFeature(feature, layer)).filter(Boolean).map((report) => {
    addReportToMap(report);
    return report;
  });
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function normalizeFeature(feature, layer) {
  const attrs = feature.attributes || {};
  const geometry = feature.geometry || {};
  const latLng = getLatLng(geometry);
  if (!latLng) return null;

  const title = firstPresent(attrs, ['CommonName', 'commonname', 'Type', 'type', 'Description', 'description', 'Address', 'address']) || layer.label;
  const address = firstPresent(attrs, ['Address', 'address', 'Location', 'location', 'Street', 'street', 'Block', 'block']);
  const timeRaw = firstPresent(attrs, ['TimeCreate', 'timecreate', 'CreateDate', 'created_date', 'Created', 'created', 'Updated', 'LastUpdate']);
  const timeValue = parseArcGisTime(timeRaw);
  const id = firstPresent(attrs, ['OBJECTID', 'ObjectId', 'objectid', 'FID']) || `${layer.id}-${latLng.lat}-${latLng.lng}`;

  return {
    id,
    layerId: layer.id,
    layerKey: layer.key,
    layerLabel: layer.serviceName || layer.label,
    layerColor: layer.color,
    title: cleanValue(title),
    address: cleanValue(address),
    timeRaw,
    timeValue,
    lat: latLng.lat,
    lng: latLng.lng,
    attributes: attrs,
  };
}

function getLatLng(geometry) {
  if (typeof geometry.y !== 'number' || typeof geometry.x !== 'number') return null;
  if (Math.abs(geometry.x) <= 180 && Math.abs(geometry.y) <= 90) return { lat: geometry.y, lng: geometry.x };
  return webMercatorToLatLng(geometry.x, geometry.y);
}

function webMercatorToLatLng(x, y) {
  const lng = (x / 20037508.34) * 180;
  let lat = (y / 20037508.34) * 180;
  lat = (180 / Math.PI) * (2 * Math.atan(Math.exp((lat * Math.PI) / 180)) - Math.PI / 2);
  return { lat, lng };
}

function addReportToMap(report) {
  let group = state.layerGroups.get(report.layerId);
  if (!group) {
    group = L.layerGroup().addTo(map);
    state.layerGroups.set(report.layerId, group);
  }
  const marker = L.circleMarker([report.lat, report.lng], {
    radius: 8,
    color: '#ffffff',
    weight: 1.5,
    fillColor: report.layerColor,
    fillOpacity: 0.9,
  });
  marker.bindPopup(renderPopup(report));
  marker.on('click', () => highlightReport(report.id));
  marker.addTo(group);
  report.marker = marker;
}

function renderPopup(report) {
  const time = formatTime(report.timeValue, report.timeRaw);
  const rows = [
    `<div class="popup-title">${escapeHtml(report.title)}</div>`,
    `<div class="popup-row"><strong>Layer:</strong> ${escapeHtml(report.layerLabel)}</div>`,
  ];
  if (report.address) rows.push(`<div class="popup-row"><strong>Address:</strong> ${escapeHtml(report.address)}</div>`);
  if (time) rows.push(`<div class="popup-row"><strong>Time:</strong> ${escapeHtml(time)}</div>`);
  rows.push(`<div class="popup-row"><strong>Lat/Lon:</strong> ${report.lat.toFixed(5)}, ${report.lng.toFixed(5)}</div>`);
  return rows.join('');
}

function renderReports() {
  els.reportCount.textContent = String(state.reports.length);
  if (!state.reports.length) {
    els.reportList.innerHTML = '<p class="muted">No active flood reports returned.</p>';
    return;
  }
  els.reportList.innerHTML = state.reports.map((report) => {
    const time = formatTime(report.timeValue, report.timeRaw) || 'Time unavailable';
    const extra = pickInterestingAttributes(report.attributes);
    return `
      <article class="report-card" data-report-id="${escapeHtml(String(report.id))}">
        <div class="report-title">
          <span class="layer-dot" style="background:${report.layerColor}"></span>
          <span>${escapeHtml(report.title)}</span>
        </div>
        <div class="report-address">${escapeHtml(report.address || report.layerLabel)}</div>
        <div class="report-time">${escapeHtml(time)}</div>
        ${extra ? `<div class="report-extra">${escapeHtml(extra)}</div>` : ''}
      </article>`;
  }).join('');

  document.querySelectorAll('.report-card').forEach((card) => {
    card.addEventListener('click', () => {
      const report = state.reports.find((candidate) => String(candidate.id) === card.dataset.reportId);
      if (!report) return;
      map.setView([report.lat, report.lng], Math.max(map.getZoom(), 15));
      report.marker?.openPopup();
    });
  });
}

function renderLayerControls() {
  els.layerControls.innerHTML = state.layers.map((layer) => {
    const count = typeof layer.count === 'number' ? layer.count : '—';
    const label = layer.serviceName || layer.label;
    const note = `Layer ${layer.id}; flood reports only`;
    return `
      <label class="layer-row">
        <input type="checkbox" data-layer-id="${layer.id}" ${layer.enabled ? 'checked' : ''} />
        <span>
          <span class="layer-name">${escapeHtml(label)}</span>
          <span class="layer-meta">${escapeHtml(note)}</span>
        </span>
        <span class="layer-count">${count}</span>
      </label>`;
  }).join('');

  els.layerControls.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener('change', () => {
      const layer = state.layers.find((candidate) => String(candidate.id) === input.dataset.layerId);
      if (!layer) return;
      layer.enabled = input.checked;
      refreshAll({ fitBounds: false });
    });
  });
}

function clearMap() {
  for (const group of state.layerGroups.values()) {
    group.clearLayers();
    map.removeLayer(group);
  }
  state.layerGroups.clear();
  state.layers.forEach((layer) => { layer.count = undefined; });
}

function fitToReports(reports) {
  const points = reports.map((report) => [report.lat, report.lng]);
  if (points.length) map.fitBounds(points, { padding: [30, 30], maxZoom: 14 });
}

function highlightReport(reportId) {
  document.querySelectorAll('.report-card').forEach((card) => {
    card.style.borderColor = card.dataset.reportId === String(reportId) ? 'var(--yellow)' : 'var(--border)';
  });
}

function configureAutoRefresh() {
  if (state.timer) window.clearInterval(state.timer);
  state.timer = els.autoRefreshToggle.checked ? window.setInterval(() => refreshAll({ fitBounds: false }), AUTO_REFRESH_MS) : null;
}

function setStatus(message, isError = false) {
  els.statusLine.textContent = message;
  els.statusLine.classList.toggle('error-text', isError);
}

function firstPresent(object, keys) {
  for (const key of keys) {
    const value = object[key];
    if (value !== null && value !== undefined && value !== '') return value;
  }
  return null;
}

function cleanValue(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/\s+/g, ' ').trim();
}

function parseArcGisTime(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') {
    const ms = value < 10_000_000_000 ? value * 1000 : value;
    const date = new Date(ms);
    return Number.isNaN(date.getTime()) ? null : date.getTime();
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.getTime();
}

function formatTime(timeValue, raw) {
  if (timeValue) return new Date(timeValue).toLocaleString();
  if (raw) return String(raw);
  return '';
}

function pickInterestingAttributes(attrs) {
  const skip = new Set(['OBJECTID', 'ObjectId', 'objectid', 'Shape', 'Shape_Length', 'Shape_Area', 'Address', 'CommonName', 'TimeCreate']);
  const item = Object.entries(attrs).find(([key, value]) => !skip.has(key) && value !== null && value !== undefined && value !== '' && (typeof value === 'string' || typeof value === 'number'));
  return item ? `${item[0]}: ${item[1]}` : '';
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
