const SERVICE_URL = 'https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer';
const AUTO_REFRESH_MS = 120_000;

const DEFAULT_LAYERS = [
  {
    id: 1,
    key: 'flooding',
    label: 'Flooded Streets',
    color: '#42a5ff',
    enabled: true,
  },
];

const state = {
  layers: structuredClone(DEFAULT_LAYERS),
  layerGroups: new Map(),
  reports: [],
  timer: null,
  mode: 'live',
  archiveDate: null,
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
  liveViewBtn: document.getElementById('liveViewBtn'),
  archiveViewBtn: document.getElementById('archiveViewBtn'),
  archiveControls: document.getElementById('archiveControls'),
  archiveDate: document.getElementById('archiveDate'),
  loadArchiveBtn: document.getElementById('loadArchiveBtn'),
  archiveStatus: document.getElementById('archiveStatus'),
};

els.refreshBtn.addEventListener('click', () => refreshAll({ fitBounds: false }));
els.autoRefreshToggle.addEventListener('change', configureAutoRefresh);
els.liveViewBtn.addEventListener('click', () => setViewMode('live'));
els.archiveViewBtn.addEventListener('click', () => setViewMode('archive'));
els.loadArchiveBtn.addEventListener('click', () => loadArchive(els.archiveDate.value, { fitBounds: true }));
els.archiveDate.addEventListener('change', () => loadArchive(els.archiveDate.value, { fitBounds: true }));

init();

async function init() {
  state.archiveDate = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Chicago',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
  els.archiveDate.value = state.archiveDate;
  renderLayerControls();
  configureAutoRefresh();
  await refreshAll({ fitBounds: true });
}

async function refreshAll({ fitBounds = false } = {}) {
  if (state.mode === 'archive') {
    await loadArchive(els.archiveDate.value, { fitBounds });
    return;
  }
  setStatus('Loading Streetwise flood layer…');
  clearMap();

  try {
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

function setViewMode(mode) {
  state.mode = mode;
  els.liveViewBtn.classList.toggle('active', mode === 'live');
  els.archiveViewBtn.classList.toggle('active', mode === 'archive');
  els.archiveControls.hidden = mode !== 'archive';
  els.autoRefreshToggle.disabled = mode === 'archive';
  configureAutoRefresh();
  if (mode === 'archive') loadArchive(els.archiveDate.value, { fitBounds: true });
  else refreshAll({ fitBounds: true });
}

async function loadArchive(date, { fitBounds = false } = {}) {
  if (!date) return;
  state.archiveDate = date;
  setStatus(`Loading archive for ${date}…`);
  clearMap();

  try {
    const response = await fetch(`data/events/${date}.json?ts=${Date.now()}`, { cache: 'no-store' });
    if (response.status === 404) throw new Error('No archived reports were captured for this date.');
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const catalog = await response.json();
    const reports = (catalog.events || []).map(normalizeArchivedEvent).filter(Boolean);
    reports.forEach(addReportToMap);
    state.reports = reports;
    state.layers[0].count = reports.length;
    renderReports();
    renderLayerControls();
    if (fitBounds) fitToReports(reports);

    const activeCount = reports.filter((report) => report.active).length;
    setStatus(`${reports.length} archived flood report${reports.length === 1 ? '' : 's'} for ${date}`);
    els.updatedLine.textContent = `Archive through: ${formatActualTime(catalog.last_archive_run_utc) || '—'}`;
    els.archiveStatus.textContent = `${reports.length} unique; ${activeCount} still active at the last capture.`;
  } catch (error) {
    state.reports = [];
    state.layers[0].count = 0;
    renderReports();
    renderLayerControls();
    setStatus(error.message, true);
    els.updatedLine.textContent = 'Archive: unavailable';
    els.archiveStatus.textContent = error.message;
  }
}

function normalizeArchivedEvent(event) {
  if (typeof event.lat !== 'number' || typeof event.lon !== 'number') return null;
  return {
    id: event.event_id,
    layerId: 1,
    layerKey: 'flooding',
    layerLabel: 'Flooded Streets',
    layerColor: '#42a5ff',
    title: cleanValue(event.title || event.attributes?.Type || 'Flood report'),
    address: cleanValue(event.address),
    timeRaw: event.time_create,
    timeValue: parseArcGisTime(event.time_create),
    lat: event.lat,
    lng: event.lon,
    attributes: event.attributes || {},
    archive: true,
    active: Boolean(event.active),
    firstSeen: event.first_seen_utc,
    lastSeen: event.last_seen_utc,
    observations: event.observations || 1,
  };
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
    layerLabel: layer.label,
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
    `<div class="popup-title">${escapeHtml(report.address || report.layerLabel)}</div>`,
  ];
  if (time) rows.push(`<div class="popup-row"><strong>Time:</strong> ${escapeHtml(time)}</div>`);
  if (report.archive) {
    rows.push(`<div class="popup-row"><strong>Status:</strong> ${report.active ? 'Active at last capture' : 'Cleared from live layer'}</div>`);
    rows.push(`<div class="popup-row"><strong>First seen:</strong> ${escapeHtml(formatActualTime(report.firstSeen))}</div>`);
    rows.push(`<div class="popup-row"><strong>Last seen:</strong> ${escapeHtml(formatActualTime(report.lastSeen))}</div>`);
  }
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
    const archiveStatus = report.archive
      ? `<div class="report-archive-status ${report.active ? 'active' : 'cleared'}">${report.active ? 'Active at last capture' : 'Cleared'} · Last seen ${escapeHtml(formatActualTime(report.lastSeen))}</div>`
      : '';
    return `
      <article class="report-card" data-report-id="${escapeHtml(String(report.id))}">
        <div class="report-title">
          <span class="layer-dot" style="background:${report.layerColor}"></span>
          <span>${escapeHtml(report.address || report.layerLabel)}</span>
        </div>
        <div class="report-time">${escapeHtml(time)}</div>
        ${archiveStatus}
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
    return `
      <label class="layer-row">
        <input type="checkbox" data-layer-id="${layer.id}" ${layer.enabled ? 'checked' : ''} />
        <span>
          <span class="layer-name">${escapeHtml(layer.label)}</span>
          <span class="layer-meta">Streetwise MapServer/${layer.id}</span>
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
  state.timer = state.mode === 'live' && els.autoRefreshToggle.checked
    ? window.setInterval(() => refreshAll({ fitBounds: false }), AUTO_REFRESH_MS)
    : null;
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
  const ms = typeof value === 'number'
    ? (value < 10_000_000_000 ? value * 1000 : value)
    : new Date(value).getTime();
  if (Number.isNaN(ms)) return null;

  // Streetwise stores New Orleans wall-clock time in a UTC-shaped ArcGIS value.
  // Reinterpret it in America/Chicago so CDT/CST are handled automatically.
  return reinterpretUtcWallClock(ms, 'America/Chicago');
}

function reinterpretUtcWallClock(ms, timeZone) {
  let corrected = ms;
  for (let index = 0; index < 2; index += 1) {
    corrected = ms - getTimeZoneOffsetMs(new Date(corrected), timeZone);
  }
  return corrected;
}

function getTimeZoneOffsetMs(date, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  const representedAsUtc = Date.UTC(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day),
    Number(values.hour),
    Number(values.minute),
    Number(values.second),
  );
  return Math.round((representedAsUtc - date.getTime()) / 60_000) * 60_000;
}

function formatTime(timeValue, raw) {
  if (timeValue) return new Date(timeValue).toLocaleString('en-US', { timeZone: 'America/Chicago' });
  if (raw) return String(raw);
  return '';
}

function formatActualTime(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString('en-US', { timeZone: 'America/Chicago' });
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
