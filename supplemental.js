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
  function details(item) {
    if (item.type === 'sensor') {
      const reading = typeof item.measurement === 'number' && Number.isFinite(item.measurement)
        ? item.measurement.toFixed(2) + ' (source units unverified)'
        : 'Not available';
      const age = sensorTime(item.recorded);
      const stale = !age || (Date.now() - age.getTime() > 30 * 60 * 1000) || (age.getTime() > Date.now() + 5 * 60 * 1000);
      return [
        item.sensor ? 'Sensor: ' + item.sensor : 'Water-level monitoring',
        'Reading: ' + reading,
        'Observed: ' + formatSensorTime(item.recorded) + (stale ? ' · STALE/UNKNOWN' : ''),
        'Quality: ' + (item.quality ?? 'Not provided'),
        'Monitoring only — NOT a confirmed flood or road closure',
      ];
    }
    return [item.description ?? 'City alert — details not supplied', 'Reported: ' + formatSensorTime(item.recorded)];
  }
  function render() {
    list.innerHTML = latest.length ? latest.map(item => {
      return '<article class="report-card"><div class="report-title">' + safe(item.location) + '</div>' +
        '<div class="report-time">' + safe(item.source) + '</div>' +
        details(item).map(line => '<div class="report-time">' + safe(line) + '</div>').join('') + '</article>';
    }).join('') : '<p class="muted">No supplemental records returned by available sources.</p>';
    supplementalMarkers.clearLayers();
    latest.forEach(item => {
      if (!item.loc || !item.loc.every(Number.isFinite)) return;
      const marker = L.circleMarker(item.loc, {radius:6,color:'#fff',weight:1,fillColor:item.type === 'sensor' ? '#ffd600' : '#ff8a50',fillOpacity:0.9});
      marker.bindPopup('<strong>' + safe(item.location) + '</strong>' +
        details(item).map(line => '<div>' + safe(line) + '</div>').join(''));
      marker.addTo(supplementalMarkers);
    });
  }
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
      status.textContent = successes + '/' + sources.length + ' sources responding · ' + latest.length + ' supplemental records' +
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
