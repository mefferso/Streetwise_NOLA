// Compatibility shim for cached app.js copies that still target Streetwise_Live.
// Redirect those requests to the City's Rainwater 21F service.
(() => {
  const LEGACY = 'https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer';
  const CURRENT = 'https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer';
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
