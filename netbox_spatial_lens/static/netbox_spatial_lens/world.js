/*
 * World map.
 *
 * One renderer: a MapLibre globe. It needs WebGL, and MapLibre itself, which is loaded from the
 * `map_js` and `map_css` settings. Tiles are optional: without a tile server the globe is drawn
 * on a plain ground, with the same sites and circuits on it. Where the map cannot run, the page
 * says which of the two is missing; the figures, the legends and the finders work either way.
 *
 * Clicking a site goes into it. Clicking a circuit highlights it and both of its ends, and
 * ticking a single site in the Sites finder highlights every circuit reaching it.
 */
(function () {
  'use strict';

  const mapEl = document.querySelector('[data-lens-map]');
  if (!mapEl) return;

  const message = document.querySelector('[data-lens-map-message]');
  const config = JSON.parse(document.getElementById('lens-map-config').textContent);
  // Handed down from palette.py, so the map, the legend and the server agree. The dark theme has
  // its own label and highlight colours, because its ground is dark.
  const palette = isDark() ? { ...config.colours, ...config.colours.dark } : config.colours;

  // The estate, indexed once: node key -> node, and circuit id -> { link, a, z } for every
  // circuit with both ends on the map.
  const byKey = {};
  config.nodes.forEach((node) => {
    byKey[node.key] = node;
  });
  const lines = new Map();
  config.links.forEach((link) => {
    const a = byKey[link.a];
    const z = byKey[link.z];
    if (a && z) lines.set(String(link.id), { link, a, z });
  });

  let map = null;

  // How long to wait for MapLibre, its style or the estate before saying the map failed.
  const ASSET_TIMEOUT = 8000;

  const status = document.querySelector('[data-lens-world-status]');
  let selection = null;
  // The site bands picked out, empty for all of them. Kept here rather than read back off the DOM
  // because a map feature has no DOM node of its own to carry the answer.
  let bands = [];

  // The picked provider bands, empty for all of them. A second, independent narrowing: the site
  // legend answers "which of these places" and this one "whose circuits", and a reader wanting
  // "which of my branches does Level 3 reach" needs both to hold at once.
  let circuitBands = [];

  /* What the site band wants the status line to say, or '' for nothing.
   *
   * Kept because two things write that line and one of them, apply(), runs on every change and
   * would otherwise reset it: picking a provider called apply() and wiped the message the site
   * band had put there a moment earlier. Held here, the line survives whatever else redraws. */
  let bandStatus = '';

  // "4 of 29": every point on the map, provider networks included, which is what a band counts.
  const totalPoints = config.nodes.length;

  /* Whether a node survives the legend filter.
   *
   * Two filters act on this map and they compose rather than replace: picking a group narrows
   * the map to it, and selecting a site or a circuit then lights the paths inside that group.
   * A node failing the band is receded whatever the selection says about it. */
  function inBand(node) {
    return !bands.length || bands.includes(node.band);
  }

  /* Whether a circuit survives the provider filter. The provider legend keys its bands on the
   * provider names. */
  function inCircuitBand(link) {
    return !circuitBands.length || circuitBands.includes(link.band);
  }

  function inFocus(group, id) {
    return !window.lensFinder || window.lensFinder.inFocus(group, id);
  }

  /* The map's three states, written as feature state rather than as styles.
   *
   * MapLibre owns its geometry on the GPU and gives no per-feature handle to restyle, so the
   * paint properties are expressions written once at layer creation and each feature carries
   * `dim` and `lit` for them to read. Setting a flag on a feature is also far cheaper than
   * rebuilding a source, which is what a naive filter would do on every click. */
  function paint(kind, key, state) {
    if (!map || !map.getSource('estate')) return;
    const id = (kind === 'sites' ? siteIds : linkIds).get(key);
    if (id === undefined) return;
    map.setFeatureState({ source: 'estate', id: id }, state);
  }

  function resetLayers() {
    lines.forEach(function (entry, key) {
      // A circuit belongs to the band only if both of its ends do, so narrowing to one group
      // leaves the links inside that group and drops the ones reaching out of it.
      const lit =
        inBand(entry.a) &&
        inBand(entry.z) &&
        inCircuitBand(entry.link) &&
        inFocus('circuits', key) &&
        inFocus('sites', entry.a.key) &&
        inFocus('sites', entry.z.key);
      paint('links', key, { dim: !lit, lit: false });
    });
    config.nodes.forEach(function (node) {
      const lit = inBand(node) && inFocus('sites', node.key);
      paint('sites', node.key, { dim: !lit, lit: false, primary: false });
    });
  }

  function apply() {
    document.body.classList.toggle('lens-has-selection', Boolean(selection));
    if (!selection) {
      status.textContent = bandStatus;
      resetLayers();
      return;
    }

    const { type, id } = selection;
    const circuitIds = new Set();
    const nodeKeys = new Set();

    lines.forEach(function (entry, key) {
      const hit = type === 'node' ? entry.a.key === id || entry.z.key === id : key === id;
      if (!hit) return;
      circuitIds.add(key);
      nodeKeys.add(entry.a.key);
      nodeKeys.add(entry.z.key);
    });
    if (type === 'node') nodeKeys.add(id);

    lines.forEach(function (entry, key) {
      const lit =
        circuitIds.has(key) &&
        inBand(entry.a) &&
        inBand(entry.z) &&
        inCircuitBand(entry.link) &&
        inFocus('circuits', key);
      paint('links', key, { dim: !lit, lit: lit });
    });
    config.nodes.forEach(function (node) {
      const lit = nodeKeys.has(node.key) && inBand(node) && inFocus('sites', node.key);
      paint('sites', node.key, { dim: !lit, lit: lit, primary: node.key === id });
    });

    const reached = nodeKeys.size - (type === 'node' ? 1 : 0);
    status.textContent =
      type === 'node'
        ? `${circuitIds.size} circuit${circuitIds.size === 1 ? '' : 's'}, reaching ${reached} other${reached === 1 ? '' : 's'}`
        : '1 circuit';
  }

  function select(type, id) {
    selection = selection && selection.type === type && selection.id === id ? null : { type, id };
    apply();
  }

  /* Clicking away from the map clears the selection.
   *
   * The legend and the finders are in this list because using either is an act on the map, not a
   * click on empty space beside it. Left out, this handler ran straight after them and undid what
   * they had just done: a band lost the status line it had written, and ticking a single site in a
   * finder selected it and then cleared the selection in the same click, so it never traced. */
  document.addEventListener('click', function (event) {
    if (!event.target.closest('.lens-map, .lens-legend, [data-lens-finder]')) {
      selection = null;
      apply();
    }
  });

  document.addEventListener('lens:filter', function (event) {
    if (event.detail.group === 'circuits') {
      circuitBands = event.detail.bands;
      // The provider narrows the lines and nothing else, so the status line, which counts
      // points on the map, is left to the site legend that owns it.
      apply();
      return;
    }
    if (event.detail.group !== 'sites') return;
    bands = event.detail.bands;
    // "4 of 29", the same idiom the rack's cabling badge uses, and no noun: a provider network
    // is on this map and is not a site, so "of 29 sites" would have been a small lie.
    bandStatus = bands.length ? `${event.detail.label}: ${event.detail.count} of ${totalPoints}` : '';
    apply();
    // After apply(), which rewrites the status line for a selection and would otherwise wipe
    // this in the same breath.
    if (bands.length) status.textContent = bandStatus;
  });

  /* ----------------------------------------------------------------------
   * The finders
   *
   * The control itself is `finder.js`, shared with the rack. This is only what the map has to
   * do that a class on an element cannot: the markers and links are drawn on a canvas, so a
   * pick has to be repainted rather than restyled.
   *
   * Ticking one thing also selects it, which traces it and pans the map there, because that is
   * the only case where a single path exists to show. Ticking several narrows the map to them.
   * ------------------------------------------------------------------- */

  document.addEventListener('lens:finder', function (event) {
    const { group, picked } = event.detail;

    if (picked.length === 1) {
      const only = picked[0];
      select(group === 'sites' ? 'node' : 'link', only);
      const node = group === 'sites' ? byKey[only] : null;
      if (map && node) map.panTo([node.lon, node.lat]);
    } else if (selection) {
      selection = null;
      apply();
    } else {
      resetLayers();
    }
  });

  const legends = document.querySelector('[data-lens-legends]');
  const legendsToggle = document.querySelector('[data-lens-legends-toggle]');
  if (legends && legendsToggle) {
    legendsToggle.addEventListener('click', function () {
      const collapsed = legends.classList.toggle('is-collapsed');
      legendsToggle.setAttribute('aria-expanded', String(!collapsed));
      legendsToggle.title = collapsed ? 'Show the legends' : 'Hide the legends';
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && selection) {
      selection = null;
      apply();
    }
  });

  /* ------------------------------------------------------------------------
   * The map
   * --------------------------------------------------------------------- */

  function esc(value) {
    const node = document.createElement('span');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

  /* What hovering a node shows.
   *
   * A name and a rack count is not enough to decide whether to click: the question at this
   * zoom is "which of these is the one I want", and that is answered by where it is, who owns
   * it and how big it is. Facts come from the server, already filtered to what is recorded,
   * so a sparse inventory shows a short card rather than a column of dashes. */
  function hoverCard(node) {
    const rows = (node.facts || [])
      .map(([label, value]) => `<tr><th>${esc(label)}</th><td>${esc(value)}</td></tr>`)
      .join('');
    const state = node.status ? `<span class="lens-card__status">${esc(node.status)}</span>` : '';
    const links = node.links
      ? `<div class="lens-card__links">${node.links} circuit${node.links === 1 ? '' : 's'}</div>`
      : '';
    return (
      `<div class="lens-card__head"><strong>${esc(node.label)}</strong>${state}</div>` +
      (rows ? `<table class="lens-card__facts">${rows}</table>` : '') +
      links +
      `<div class="lens-card__action">Click to ${esc(node.action.toLowerCase())}</div>`
    );
  }

  /* Handlers before the URL, and a timeout after it.
   *
   * Assigning href or src starts the fetch, so a handler attached afterwards can miss a load
   * that finishes first: the promise then never settles and the page waits for a map that has
   * already arrived. The timeout covers the other end, a host that accepts the connection and
   * never answers, so a slow network ends in a message instead of a page that waits for ever. */
  function loadAsset(tag, url, attrs) {
    return new Promise(function (resolve, reject) {
      const el = document.createElement(tag);
      Object.assign(el, attrs);
      el.onload = () => resolve();
      el.onerror = () => reject(new Error(`could not load ${url}`));
      const timer = setTimeout(() => reject(new Error(`timed out loading ${url}`)), ASSET_TIMEOUT);
      const settle = () => clearTimeout(timer);
      el.addEventListener('load', settle);
      el.addEventListener('error', settle);
      document.head.appendChild(el);
      // Last, so nothing can complete before the listeners above are in place.
      el[tag === 'link' ? 'href' : 'src'] = url;
    });
  }

  /* A basemap may ship a light and a dark style. NetBox marks its theme on <html>, so the map
     can follow it rather than being a bright rectangle in a dark page. */
  function tileUrl() {
    if (!config.tileUrl.includes('{theme}')) return config.tileUrl;
    return config.tileUrl.replace('{theme}', isDark() ? 'dark' : 'light');
  }

  function isDark() {
    return (
      document.documentElement.dataset.bsTheme === 'dark' ||
      document.documentElement.classList.contains('dark')
    );
  }

  /* Whether this browser can draw the map at all, asked before anything is downloaded. */
  function hasWebGL() {
    try {
      const canvas = document.createElement('canvas');
      return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
    } catch (error) {
      return false;
    }
  }

  /* A style built here rather than fetched from a style server.
   *
   * The plugin's one basemap setting is a raster tile URL, which is what a deployment already
   * has and what an air-gapped one can point at its own server. A vector style would mean a
   * second service to run, so the globe is drawn with raster tiles reprojected onto it. With no
   * tile URL the basemap layer is left out and the globe is the plain ground alone. */
  function mapStyle() {
    const dark = isDark();
    const style = {
      version: 8,
      projection: { type: 'globe' },
      sources: {},
      layers: [{ id: 'ground', type: 'background', paint: { 'background-color': dark ? '#12161c' : '#f4f5f7' } }],
    };
    /* Where the letters come from.
     *
     * A raster style carries no fonts, and a symbol layer without them draws nothing and says
     * why only in the console. This is the one asset the plugin cannot serve itself, so it is a
     * setting like the tiles are: point it at your own if the estate has no egress, and the
     * names are left out if it is not set. */
    if (config.glyphs) style.glyphs = config.glyphs;
    if (config.tileUrl) {
      style.sources.basemap = {
        type: 'raster',
        tiles: [tileUrl()],
        tileSize: 256,
        maxzoom: 19,
        attribution: config.attribution,
      };
      /* A basemap is background.
       *
       * OpenStreetMap's own tiles are the only keyless ones worth having and they are drawn for
       * reading a map, not for sitting under data: full-colour roads and landuse compete with
       * the circuits over them. Desaturating gives the pale basemap without a key, a second
       * provider or a tile server of our own.
       *
       * Done here rather than as a CSS filter because MapLibre draws everything into one canvas,
       * so a filter on the element would grey the circuits with the roads. In the dark theme the
       * tiles are dropped to a third over a dark ground instead of inverted: the renderer has no
       * invert, and a faint grey map under bright circuits reads as well. */
      style.layers.push({
        id: 'basemap',
        type: 'raster',
        source: 'basemap',
        paint: {
          'raster-saturation': -1,
          'raster-opacity': dark ? 0.32 : 0.9,
          'raster-contrast': dark ? 0.1 : -0.08,
        },
      });
    }
    return style;
  }

  /* key -> the feature's numeric id.
   *
   * A feature id has to be a number. MapLibre's GeoJSON worker indexes on it, and given the
   * plugin's own keys, which are strings like "site:12", it does not fail loudly: the source
   * simply never finishes loading, so the map draws its basemap and none of the estate on it.
   * The keys therefore live in `properties` and the ids are positions in the array. */
  const siteIds = new Map();
  const linkIds = new Map();
  let nextFeatureId = 0;

  function siteFeatures() {
    return config.nodes.map((node) => {
      const index = nextFeatureId++;
      siteIds.set(node.key, index);
      return {
        type: 'Feature',
        id: index,
        geometry: { type: 'Point', coordinates: [node.lon, node.lat] },
        properties: { key: node.key, label: node.label, colour: node.colour, radius: node.radius * 0.6 },
      };
    });
  }

  function linkFeatures() {
    return [...lines].map(([key, { link, a, z }]) => {
      const index = nextFeatureId++;
      linkIds.set(key, index);
      return {
        type: 'Feature',
        id: index,
        geometry: {
          type: 'LineString',
          // Two points only. MapLibre draws the segment along the globe, so a transatlantic
          // circuit curves the way the earth does without a great circle computed here.
          coordinates: [
            [a.lon, a.lat],
            [z.lon, z.lat],
          ],
        },
        properties: { id: key, label: link.label, colour: link.colour, width: link.width },
      };
    });
  }

  /* Read as: dimmed by a filter, lit by a selection, or the ordinary state. Written as an
     expression because MapLibre evaluates paint on the GPU, per feature, per frame. */
  function byState(dim, lit, ordinary) {
    return [
      'case',
      ['boolean', ['feature-state', 'dim'], false],
      dim,
      ['boolean', ['feature-state', 'lit'], false],
      lit,
      ordinary,
    ];
  }

  function addLayers() {
    /* One source, three layers.
     *
     * The circuits and the sites are one FeatureCollection and the layers pick their half out
     * by geometry type. Two sources would read more plainly, and the reason not to is that a
     * feature id has to be unique per source and both halves are numbered from the same
     * counter here, which keeps `paint` a single lookup rather than two that can drift. */
    map.addSource('estate', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: linkFeatures().concat(siteFeatures()) },
    });

    map.addLayer({
      id: 'links',
      type: 'line',
      source: 'estate',
      filter: ['==', ['geometry-type'], 'LineString'],
      layout: { 'line-cap': 'round' },
      paint: {
        'line-color': byState(['get', 'colour'], palette.highlight, ['get', 'colour']),
        'line-width': byState(['get', 'width'], ['+', ['get', 'width'], 2], ['get', 'width']),
        'line-opacity': byState(0.12, 1, 0.6),
      },
    });

    map.addLayer({
      id: 'sites',
      type: 'circle',
      source: 'estate',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': ['get', 'radius'],
        'circle-color': ['get', 'colour'],
        'circle-opacity': byState(0.15, 0.9, 0.85),
        'circle-stroke-color': ['get', 'colour'],
        'circle-stroke-width': ['case', ['boolean', ['feature-state', 'primary'], false], 4, 2],
        'circle-stroke-opacity': byState(0.2, 1, 1),
      },
    });

    if (!config.glyphs) return;

    /* The names, decluttered by the renderer.
     *
     * MapLibre collides symbols natively and against the basemap's own labels, so a name appears
     * wherever there is room and nowhere there is not. */
    map.addLayer({
      id: 'site-labels',
      type: 'symbol',
      source: 'estate',
      filter: ['==', ['geometry-type'], 'Point'],
      layout: {
        'text-field': ['get', 'label'],
        'text-size': 12,
        'text-offset': [0.9, 0],
        'text-anchor': 'left',
        /* One font, not a stack.
         *
         * MapLibre asks the glyph server for the whole stack at once, comma-joined, and the
         * usual public server answers that path with an HTML 404 carrying a 200 status. The
         * renderer then parses the HTML as a protobuf, the symbol bucket throws, and it takes
         * the tile down with it: the markers disappear along with the names they were beside.
         * Asking for one font that exists is both simpler and the only thing that works. */
        'text-font': ['Open Sans Regular'],
        'text-allow-overlap': false,
        'text-optional': true,
      },
      paint: {
        'text-color': palette.label,
        'text-halo-color': palette.halo,
        'text-halo-width': 1.6,
        'text-opacity': byState(0, 1, 1),
      },
    });
  }

  function bindMapEvents() {
    const popup = new maplibregl.Popup({ closeButton: false, className: 'lens-card', offset: 12 });

    map.on('mousemove', 'sites', function (event) {
      map.getCanvas().style.cursor = 'pointer';
      const node = byKey[event.features[0].properties.key];
      if (node) popup.setLngLat([node.lon, node.lat]).setHTML(hoverCard(node)).addTo(map);
    });
    map.on('mouseleave', 'sites', function () {
      map.getCanvas().style.cursor = '';
      popup.remove();
    });

    // Clicking a site goes into it. This map is the outermost level, so moving
    // inward is the action the view exists for. A provider network has nowhere to go, so it
    // traces instead.
    map.on('click', 'sites', function (event) {
      const node = byKey[event.features[0].properties.key];
      if (!node) return;
      if (node.url) {
        window.location.href = node.url;
        return;
      }
      select('node', node.key);
    });

    map.on('mousemove', 'links', function () {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'links', function () {
      map.getCanvas().style.cursor = '';
    });
    map.on('click', 'links', function (event) {
      select('link', String(event.features[0].properties.id));
    });
  }

  /* A failure the reader can act on, with the words to show them. Anything else thrown on the
   * way is a failure of the map itself, and gets the generic message. */
  function readerError(text) {
    const error = new Error(text);
    error.forReader = true;
    return error;
  }

  async function buildMap() {
    if (!config.mapJs) {
      throw readerError('The world map is turned off: the map_js setting is empty.');
    }
    if (!hasWebGL()) {
      throw readerError('The world map needs WebGL, and this browser has none. Turn on hardware acceleration, or use another browser.');
    }

    try {
      await loadAsset('link', config.mapCss, { rel: 'stylesheet' });
      await loadAsset('script', config.mapJs, {});
    } catch (error) {
      console.warn('netbox-spatial-lens:', error.message);
    }
    if (!window.maplibregl) {
      throw readerError(
        `The world map could not load MapLibre from ${config.mapJs}. Point the map_js and map_css settings at a copy this browser can reach.`
      );
    }

    const bounds = config.nodes.reduce(
      (box, node) => box.extend([node.lon, node.lat]),
      new maplibregl.LngLatBounds([config.nodes[0].lon, config.nodes[0].lat], [config.nodes[0].lon, config.nodes[0].lat])
    );

    /* The camera is framed after the estate is on the map, never in the constructor.
     *
     * Passing `bounds` here fits the camera before the sources exist, and on a globe an estate
     * spanning half the world fits to a zoom so low that the GeoJSON source is asked for no
     * tiles at all. It then never loads: the globe turns, and not one site is drawn on it.
     * Constructing at the centre and fitting afterwards costs one animation frame and works. */
    map = new maplibregl.Map({
      container: mapEl,
      style: mapStyle(),
      center: bounds.getCenter(),
      // Not lower. On a globe, below roughly this zoom MapLibre asks the GeoJSON source for no
      // tiles at all and it never loads, so the world turns with nothing drawn on it.
      zoom: 2,
      attributionControl: config.tileUrl ? { compact: true } : false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');

    // A tile that 404s is not fatal, so errors are reported rather than thrown.
    map.on('error', function (event) {
      console.warn('netbox-spatial-lens map:', (event && event.error && event.error.message) || event);
    });

    /* The layers go on inside the `style.load` handler, not after awaiting it.
     *
     * The style here is an inline object rather than a URL, so `isStyleLoaded()` is already true
     * the instant the map is constructed; short-circuiting on it, or adding the layers in a
     * microtask chained off the event, both put `addSource` a beat too early. MapLibre accepts
     * the call, reports the source, and then never tiles it: the globe draws and the estate is
     * simply absent. */
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('the map style did not load')), ASSET_TIMEOUT);
      map.once('style.load', function () {
        clearTimeout(timer);
        addLayers();
        bindMapEvents();
        resolve();
      });
    });

    /* The map is not accepted until the estate is actually on it.
     *
     * A globe that draws with no sites on it reads as "we have no sites" rather than as a map
     * that did not load, so that case ends in the failure message instead. It also fixes the
     * ordering: painting is `setFeatureState`, and calling that on a source whose worker has not
     * finished leaves the source stuck for good.
     *
     * Measured as "are there features on the map", not as `isSourceLoaded`, which has been seen
     * false on a source whose features were already drawn, and true on one that had tiled
     * nothing. */
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('the map drew no sites')), ASSET_TIMEOUT);
      const settle = () => {
        if (!map.getLayer('sites') || !map.querySourceFeatures('estate').length) return;
        clearTimeout(timer);
        map.off('sourcedata', settle);
        map.off('idle', settle);
        resolve();
      };
      map.on('sourcedata', settle);
      map.on('idle', settle);
      settle();
    });

    map.fitBounds(bounds, { padding: 60, maxZoom: 9, animate: false });
    message.hidden = true;
    apply();
  }

  if (!config.nodes.length) return;

  buildMap().catch(function (error) {
    // Dropped as well as removed: a live handle to a map nobody can see would be read by the
    // rest of this file as "the map is up" and called straight into.
    if (map) map.remove();
    map = null;
    message.textContent = error.forReader
      ? error.message
      : 'The world map could not draw the estate. The browser console has the detail.';
    message.classList.add('is-error');
    message.hidden = false;
    if (!error.forReader) console.warn('netbox-spatial-lens could not draw the map:', error);
  });
})();
