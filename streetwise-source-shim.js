// Compatibility shim for the Streetwise source migration in July 2026.
// app.js originally targeted eocgis.nola.gov:6443/Streetwise_Live, which now
// returns successful but empty flood-layer responses.  Redirect those requests
// to the City's current Flood_Events service without duplicating app logic.
(() => {
  const LEGACY = 'https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer';
  const CURRENT = 'https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/MapServer';
  const nativeFetch = window.fetch.bind(window);

  window.fetch = (input, init) => {
    if (typeof input === 'string' && input.startsWith(LEGACY)) {
      input = CURRENT + input.slice(LEGACY.length);
    } else if (input instanceof Request && input.url.startsWith(LEGACY)) {
      input = new Request(CURRENT + input.url.slice(LEGACY.length), input);
    }
    return nativeFetch(input, init);
  };
})();
