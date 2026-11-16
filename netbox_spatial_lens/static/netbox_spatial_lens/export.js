/*
 * A drawing as a PNG: the drawing as it stands, under a title and over its legends.
 *
 * Each drawing registers how to capture itself: the 2D plan here, the 3D stages in stage3d.js
 * and the map in world.js. The button exports the one on show. The legends are read from the
 * page, so the image carries the counts and the picked bands the reader sees.
 *
 * Loaded before the scripts that register with it.
 */
(function () {
  'use strict';

  // Image pixels per CSS pixel, so text stays sharp when the image is enlarged in a report.
  const SCALE = 2;
  const PAD = 16;
  const LEGEND_WIDTH = 220;
  const ROW = 18;
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

  // What a stylesheet decides for an SVG element. An SVG drawn as an image has no stylesheet, so
  // these are written onto each element of the copy.
  const SVG_STYLES = [
    'display',
    'visibility',
    'opacity',
    'fill',
    'fill-opacity',
    'stroke',
    'stroke-width',
    'stroke-opacity',
    'stroke-dasharray',
    'stroke-linecap',
    'stroke-linejoin',
    'paint-order',
    'shape-rendering',
    'font-family',
    'font-size',
    'font-weight',
    'font-style',
    'letter-spacing',
    'text-anchor',
    'dominant-baseline',
    'filter',
  ];

  const sources = [];
  const button = document.querySelector('[data-lens-export]');

  function onShow(element) {
    // Not `offsetParent`, which an SVG element does not have.
    return element.getClientRects().length > 0;
  }

  function loadImage(url) {
    return new Promise(function (resolve, reject) {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = url;
    });
  }

  async function dataUrl(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} for ${url}`);
    const blob = await response.blob();
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  /* The plan as a canvas, at the zoom it is shown at. */
  async function captureSvg(svg) {
    const box = svg.getBoundingClientRect();
    const copy = svg.cloneNode(true);
    const originals = svg.querySelectorAll('*');
    copy.querySelectorAll('*').forEach(function (node, index) {
      const style = getComputedStyle(originals[index]);
      SVG_STYLES.forEach((name) => node.style.setProperty(name, style.getPropertyValue(name)));
    });
    copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    copy.setAttribute('width', box.width);
    copy.setAttribute('height', box.height);

    // An SVG drawn as an image may not fetch anything, so each background is embedded in it.
    const notes = [];
    await Promise.all(
      Array.from(copy.querySelectorAll('image')).map(async function (image) {
        try {
          image.setAttribute('href', await dataUrl(image.getAttribute('href')));
        } catch (error) {
          const title = image.querySelector('title');
          notes.push(`The background "${title ? title.textContent : 'layer'}" could not be read and is not in this image.`);
          image.remove();
        }
      })
    );

    const blob = new Blob([new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    try {
      const image = await loadImage(url);
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(box.width * SCALE);
      canvas.height = Math.round(box.height * SCALE);
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
      return { canvas, width: box.width, height: box.height, notes };
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function roundedRect(context, x, y, width, height, radius) {
    context.beginPath();
    context.roundRect(x, y, width, height, radius);
  }

  /* Draw the HTML labels of a layer onto a canvas of the same place, `scale` pixels per CSS pixel. */
  function drawLabels(context, layer, scale) {
    const origin = layer.getBoundingClientRect();
    context.save();
    context.scale(scale, scale);
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    Array.from(layer.children).forEach(function (node) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || !node.textContent) return;
      const box = node.getBoundingClientRect();
      if (!box.width) return;
      const x = box.left - origin.left;
      const y = box.top - origin.top;
      context.globalAlpha = parseFloat(style.opacity);
      context.fillStyle = style.backgroundColor;
      roundedRect(context, x, y, box.width, box.height, parseFloat(style.borderTopLeftRadius) || 0);
      context.fill();
      context.fillStyle = style.color;
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      context.fillText(node.textContent, x + box.width / 2, y + box.height / 2 + 0.5);
    });
    context.restore();
  }

  function legendTitle(list) {
    const onMap = list.closest('.lens-map-legend');
    if (onMap) return onMap.querySelector('.lens-map-legend__title').textContent.trim();
    const card = list.closest('.card');
    const header = card ? card.querySelector('.card-header') : null;
    if (!header) return '';
    return (header.firstElementChild || header).textContent.trim();
  }

  /* The legends of the page. One folded away on the map still explains the map, so it is kept. */
  function readLegends() {
    return Array.from(document.querySelectorAll('ul.lens-legend'))
      .filter((list) => onShow(list) || list.closest('.lens-map-legends'))
      .map(function (list) {
        const rows = Array.from(list.querySelectorAll('.lens-legend__row')).map(function (row) {
          const swatch = row.querySelector('.lens-swatch');
          const style = getComputedStyle(swatch);
          return {
            colour: style.backgroundColor,
            border: swatch.classList.contains('lens-swatch--reserved') ? style.borderTopColor : '',
            label: row.querySelector('.lens-legend__label').textContent.trim(),
            count: row.querySelector('.lens-legend__count').textContent.trim(),
            picked: row.getAttribute('aria-pressed') === 'true',
          };
        });
        return { title: legendTitle(list), rows, narrowed: rows.some((row) => row.picked) };
      })
      .filter((legend) => legend.rows.length);
  }

  function clip(context, text, width) {
    if (context.measureText(text).width <= width) return text;
    let cut = text;
    while (cut.length > 1 && context.measureText(`${cut}…`).width > width) cut = cut.slice(0, -1);
    return `${cut}…`;
  }

  function drawLegend(context, legend, x, y, colours) {
    context.textBaseline = 'middle';
    context.textAlign = 'left';
    context.fillStyle = colours.text;
    context.font = `600 12px ${FONT}`;
    context.fillText(clip(context, legend.title, LEGEND_WIDTH), x, y + ROW / 2);
    legend.rows.forEach(function (row, index) {
      const middle = y + ROW * (index + 1) + ROW / 2;
      // The bands the reader did not pick recede in the legend as they do on the drawing.
      context.globalAlpha = legend.narrowed && !row.picked ? 0.4 : 1;
      context.fillStyle = row.colour;
      roundedRect(context, x, middle - 5, 10, 10, 2);
      context.fill();
      if (row.border) {
        context.strokeStyle = row.border;
        context.setLineDash([2, 2]);
        context.stroke();
        context.setLineDash([]);
      }
      context.fillStyle = colours.text;
      context.font = `${row.picked ? 600 : 400} 12px ${FONT}`;
      context.textAlign = 'right';
      context.fillText(row.count, x + LEGEND_WIDTH - PAD, middle);
      const room = LEGEND_WIDTH - PAD - 24 - context.measureText(row.count).width;
      context.textAlign = 'left';
      context.fillText(clip(context, row.label, room), x + 18, middle);
      context.globalAlpha = 1;
    });
  }

  /* The first background that is a colour, from `element` outwards. */
  function backgroundOf(element) {
    for (let node = element; node; node = node.parentElement) {
      const colour = getComputedStyle(node).backgroundColor;
      if (colour && colour !== 'transparent' && !/, 0\)$/.test(colour)) return colour;
    }
    return '#ffffff';
  }

  function compose(drawing, heading, element) {
    const legends = readLegends();
    const width = Math.max(drawing.width, LEGEND_WIDTH * 2) + PAD * 2;
    const perRow = Math.max(1, Math.floor((width - PAD * 2) / LEGEND_WIDTH));

    // Legends side by side, wrapped into as many bands as the width needs.
    const bands = [];
    legends.forEach(function (legend, index) {
      if (index % perRow === 0) bands.push([]);
      bands[bands.length - 1].push(legend);
    });
    const bandHeights = bands.map((band) => Math.max(...band.map((legend) => legend.rows.length + 1)) * ROW + PAD);
    const footnotes = drawing.notes.concat(drawing.credit ? [drawing.credit] : []);

    const headerHeight = 56;
    const height =
      headerHeight + drawing.height + PAD + bandHeights.reduce((sum, h) => sum + h, 0) + footnotes.length * ROW + PAD / 2;

    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width * SCALE);
    canvas.height = Math.round(height * SCALE);
    const context = canvas.getContext('2d');
    context.scale(SCALE, SCALE);

    const colours = { text: getComputedStyle(element).color, background: backgroundOf(element) };
    context.fillStyle = colours.background;
    context.fillRect(0, 0, width, height);

    context.fillStyle = colours.text;
    context.textBaseline = 'middle';
    context.font = `600 16px ${FONT}`;
    context.fillText(clip(context, heading.title, width - PAD * 2), PAD, 22);
    context.globalAlpha = 0.65;
    context.font = `400 12px ${FONT}`;
    context.fillText(clip(context, heading.subtitle, width - PAD * 2), PAD, 42);
    context.globalAlpha = 1;

    context.drawImage(drawing.canvas, PAD, headerHeight, drawing.width, drawing.height);

    let y = headerHeight + drawing.height + PAD;
    bands.forEach(function (band, index) {
      band.forEach((legend, column) => drawLegend(context, legend, PAD + column * LEGEND_WIDTH, y, colours));
      y += bandHeights[index];
    });

    context.globalAlpha = 0.65;
    context.fillStyle = colours.text;
    context.font = `400 11px ${FONT}`;
    context.textAlign = 'left';
    footnotes.forEach(function (note) {
      context.fillText(clip(context, note, width - PAD * 2), PAD, y + ROW / 2);
      y += ROW;
    });
    context.globalAlpha = 1;
    return canvas;
  }

  function slug(text) {
    return text
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  function today() {
    const now = new Date();
    const two = (n) => String(n).padStart(2, '0');
    return `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`;
  }

  async function download() {
    const source = sources.find((candidate) => onShow(candidate.element));
    if (!source) return;
    const date = today();
    const { lensTitle: title, lensColouring: colouring } = button.dataset;
    button.disabled = true;
    try {
      const drawing = await source.capture();
      const canvas = compose(
        { notes: [], ...drawing },
        { title, subtitle: [colouring, date].filter(Boolean).join(' · ') },
        source.element
      );
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `${[slug(title), slug(colouring || ''), date].filter(Boolean).join('-')}.png`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (error) {
      console.warn('netbox-spatial-lens could not export the drawing:', error);
      button.title = 'The image could not be made. The browser console has the detail.';
    } finally {
      button.disabled = false;
    }
  }

  window.lensExport = {
    SCALE,
    drawLabels,
    /* `capture()` resolves to { canvas, width, height } in CSS pixels, with optional `notes`
       (what is missing from the image) and `credit` (whose data the drawing shows). */
    register: function (element, capture) {
      sources.push({ element, capture });
      if (button) button.disabled = false;
    },
  };

  if (!button) return;
  button.addEventListener('click', download);
  document.querySelectorAll('[data-lens-plan] svg.lens-floor').forEach(function (svg) {
    window.lensExport.register(svg, () => captureSvg(svg));
  });
})();
