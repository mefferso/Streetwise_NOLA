/* Supplemental information is intentionally NEVER added to the 21F incident archive.
 * Public service availability/schema may change; fail closed rather than imply no flooding.
 */
(() => {
  'use strict';
  const underpassUrl = 'https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/FWS_WaterLevel/MapServer/0/query';
  const alertsUrl = 'https://gis.nola.gov/apps/flood_alerts/api/get_alerts';
  const status = document.getElementById('supplementalStatus');
  const list = document.getElementById('supplementalList');
  if (!status || !list) return;
  let latest = [];
  let busy = false;
  const safe = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const first = (obj, keys) => keys.map(k => obj?.[k]).find(v => v != null && v !== '');
  const point = (g) => {
    if (!g) return null;
    if (typeof g.x === 'number' && typeof g.y === 'number') {
      if (Math.abs(g.x) <= 180 && Math.abs(g.y) <= 90) return [g.y, g.x];
      return [(180 / Math.PI) * (2 * Math.atan(Math.exp(g.y / 6378137)) - Math.PI / 2), g.x / 6378137 * 180 / Math.PI];
    }
    const c = g.coordinates || g.geometry?.coordinates;
    return Array.isArray(c) && c.length >= 2 && c.every((n, i) => i > 1 || typeof n === 'number') ? [c[1], c[0]] : null;
  };
  async function json(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, {cache:'no-store', signal:controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const payload = await response.json();
      if (payload?.error) throw new Error(payload.error.message || 'Service error');
      return payload;
    } finally { clearTimeout(timeout); }
  }
  function features(payload) {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.features)) return payload.features;
    if (Array.isArray(payload?.alerts)) return payload.alerts;
    if (Array.isArray(payload?.data?.features)) return payload.data.features;
    if (Array.isArray(payload?.data?.alerts)) return payload.data.alerts;
    // Unknown schema is not proof of zero alerts.
    throw new Error('Unrecognized response format');
  }
  const sources = [
    {name:'Underpass water-level observations', type:'sensor', url:underpassUrl + '?' + new URLSearchParams({f:'json',where:'1=1',outFields:'*',returnGeometry:'true',outSR:'4326',resultRecordCount:'1000'})},
    {name:'City flood alerts', type:'alert', url:alertsUrl},
  ];
  const sensorTime = value => {
    if (value == null || value === '') return null;
    const n = typeof value === 'number' ? value : Number(value);
    const d = Number.isFinite(n) && String(value).trim() !== '' ? new Date(n < 1e11 ? n * 1000 : n) : new Date(value);
    return Number.isFinite(d.getTime()) ? d : null;
  };
  const formatSensorTime = value => {
    const d = sensorTime(value);
    return d ? d.toLocaleString('en-US', {timeZone:'America/Chicago',dateStyle:'short',timeStyle:'short'}) + ' CT' : 'Not provided';
  };
  function normalize(raw, source) {
    const a = raw.attributes || raw.properties || raw;
    const loc = point(raw.geometry || raw);
    const location = first(a, source.type === 'sensor'
      ? ['Site','site_name','site','Site_Name','siteName','CommonName','Name','Location','Address']
      : ['CommonName','Name','name','Location','location','Address','address','Site','site_name']) || 'Location unspecified';
    const description = first(a, ['Status','status','Message','message','Description','description','Alert','alert','Level','level']);
    const recorded = first(a, source.type === 'sensor'
      ? ['reading_time','Reading_Time','timestamp','TimeCreateUTC','TimeCreate','time','DateTime']
      : ['TimeCreateUTC','TimeCreate','timestamp','time','DateTime','Date','last_updated']);
    const measurement = source.type === 'sensor' ? first(a, ['rounded_float_value','water_level']) : null;
    const sensor = source.type === 'sensor' ? first(a, ['Sensor','sensor']) : null;
    const quality = source.type === 'sensor' ? first(a, ['data_quality','site_status']) : null;
    return {source:source.name,type:source.type,location,description,recorded,measurement,sensor,quality,loc};
  }

  const supplementalMarkers = L.layerGroup().addTo(map);
  const gaugeCount = document.getElementById('gaugeCount');
  const gaugeSummary = document.getElementById('gaugeSummary');
  const showMarkers = document.getElementById('showGaugeMarkers');
  const currentOnly = document.getElementById('showOnlyCurrent');
  const markersById = new Map();
  let selectedId = null;
  const observationState = item => {
    const time = sensorTime(item.recorded);
    if (!time || time.getTime() > Date.now() + 5 * 60_000 || Date.now() - time.getTime() > 30 * 60_000) return 'stale';
    return 'current';
  };
  const keyFor = (item, index) => item.type + '-' + index;
  const numeric = item => typeof item.measurement === 'number' && Number.isFinite(item.measurement);
  function details(item) {
    if (item.type === 'sensor') return [
      (item.sensor || 'Water-level observation') + ': ' + (numeric(item) ? item.measurement.toFixed(2) : 'N/A') + ' (units unverified)',
      'Observed ' + formatSensorTime(item.recorded),
      'City quality: ' + (item.quality ?? 'Not provided'),
      'Monitoring only — closure not confirmed',
    ];
    return [item.description ?? 'City alert — details unavailable', 'Reported ' + formatSensorTime(item.recorded)];
  }
  function selectGauge(id) {
    selectedId = id;
    document.querySelectorAll('[data-gauge-id]').forEach(el => {
      const active = el.dataset.gaugeId === id;
      el.classList.toggle('selected', active);
      el.setAttribute('aria-pressed', String(active));
    });
    const marker = markersById.get(id);
    if (marker) {
      if (!map.hasLayer(supplementalMarkers)) supplementalMarkers.addTo(map);
      showMarkers.checked = true;
      const coordinates = marker.getLatLng();
      map.setView(coordinates, Math.max(map.getZoom(), 14));
      marker.openPopup();
    }
  }
  function render() {
    const gauges = latest.filter(item => item.type === 'sensor');
    const alerts = latest.filter(item => item.type === 'alert');
    const current = gauges.filter(item => observationState(item) === 'current').length;
    const stale = gauges.length - current;
    gaugeCount.textContent = String(gauges.length);
    gaugeSummary.innerHTML = '<span><strong>' + current + '</strong> current</span><span><strong>' + stale +
      '</strong> stale/unknown</span><span><strong>' + alerts.length + '</strong> City alerts</span>';
    const visible = latest.filter(item => !currentOnly.checked || item.type !== 'sensor' || observationState(item) === 'current');
    list.innerHTML = visible.length ? visible.map(item => {
      const id = keyFor(item, latest.indexOf(item));
      const isGauge = item.type === 'sensor';
      const staleReading = isGauge && observationState(item) !== 'current';
      const value = numeric(item) ? item.measurement.toFixed(2) + ' ft' : '—';
      const main = isGauge ? '<span class="gauge-reading">' + safe(value) + '</span>' : '<span class="gauge-reading">Alert</span>';
      const age = isGauge ? (staleReading ? 'Stale / unknown' : 'Current') : 'City alert';
      return '<button type="button" class="gauge-item' + (selectedId === id ? ' selected' : '') +
        '" data-gauge-id="' + safe(id) + '" aria-pressed="' + (selectedId === id) + '">' +
        '<span class="gauge-item-top"><span class="gauge-name">' + safe(item.location) +
        '</span>' + main + '</span><span class="gauge-item-bottom"><span class="gauge-indicator ' +
        (staleReading ? 'stale' : isGauge ? 'current' : 'alert') + '">' + safe(age) +
        '</span><span>' + safe(formatSensorTime(item.recorded)) +
        '</span></span><span class="gauge-subline">' +
        safe(isGauge ? ((item.sensor || 'Water level') + ' · ft' + (item.quality ? ' · quality ' + item.quality : '')) : (item.description || 'Alert details unavailable')) +
        '</span></button>';
    }).join('') : '<p class="muted">No matching observations.</p>';
    supplementalMarkers.clearLayers();
    markersById.clear();
    latest.forEach((item,index) => {
      if (!item.loc || !item.loc.every(Number.isFinite)) return;
      const id = keyFor(item,index);
      const state = item.type === 'alert' ? 'alert' : observationState(item);
      const marker = L.circleMarker(item.loc, {
        radius:state === 'alert' ? 8 : 6,
        color:'#fff',weight:1.3,
        fillColor: state === 'alert' ? '#ff8a50' : state === 'stale' ? '#888888' : '#ffd600',
        fillOpacity:0.9
      });
      marker.bindPopup('<strong>' + safe(item.location) + '</strong>' +
        details(item).map(line => '<div>' + safe(line) + '</div>').join(''));
      marker.addTo(supplementalMarkers);
      marker.on('click', () => { selectGauge(id); Array.from(list.querySelectorAll('[data-gauge-id]')).find(el => el.dataset.gaugeId === id)?.scrollIntoView({block:'nearest'}); });
      markersById.set(id,marker);
    });
    if (showMarkers.checked) supplementalMarkers.addTo(map);
    else map.removeLayer(supplementalMarkers);
    list.querySelectorAll('[data-gauge-id]').forEach(el => el.addEventListener('click', () => selectGauge(el.dataset.gaugeId)));
  }
  showMarkers.addEventListener('change', () => {
    if (showMarkers.checked) supplementalMarkers.addTo(map);
    else map.removeLayer(supplementalMarkers);
  });
  currentOnly.addEventListener('change', render);
  async function refresh() {
    if (busy) return;
    busy = true;
    status.textContent = 'Checking independent sources…';
    try {
      const responses = await Promise.allSettled(sources.map(async source => features(await json(source.url)).map(raw => normalize(raw, source))));
      latest = responses.flatMap(result => result.status === 'fulfilled' ? result.value : []);
      const successes = responses.filter(r => r.status === 'fulfilled').length;
      const failures = responses.map((r,i) => r.status === 'rejected' ? sources[i].name + ': unavailable or unsupported' : null).filter(Boolean);
      render();
      status.textContent = successes + '/' + sources.length + ' sources responding · ' + latest.filter(item => item.type === 'sensor').length + ' gauges · ' + latest.filter(item => item.type === 'alert').length + ' alerts' +
        (failures.length ? ' · DATA INCOMPLETE (' + failures.join('; ') + ')' : '') +
        ' · Checked ' + new Date().toLocaleTimeString();
      status.style.color = failures.length ? '#ffba55' : '';
    } finally { busy = false; }
  }
  document.getElementById('refreshBtn')?.addEventListener('click', refresh);
  // Keep independent from the 21F map's live/archive mode and its clearMap().
  refresh();
  setInterval(refresh, 120000);
})();
