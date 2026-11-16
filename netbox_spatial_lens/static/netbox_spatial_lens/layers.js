/*
 * The background layers in the layout editor: show, order, fade and calibrate them.
 *
 * A layer is the <image> the server drew, and its numbers live on its data attributes, as a
 * rack's do. Calibrating one makes it the thing the pointer moves: drag it, pull a corner to
 * resize it, or click two points a known distance apart to set its scale. Changes join the
 * editor's own undo, redo and Save, and are written through the REST API.
 *
 * Loaded after editor.js, which it registers with.
 */
(function () {
  'use strict';

  const editor = window.lensEditor;
  const panel = document.querySelector('[data-lens-layers]');
  if (!editor || !panel) return;

  const svg = editor.svg;
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const FIELDS = ['x', 'y', 'width', 'height', 'rotation', 'opacity', 'weight', 'enabled'];
  // The smallest side a layer can be pulled to, in centimetres.
  const SMALLEST = 10;
  // Presses closer together than this, in milliseconds, are one step to undo.
  const RUN = 800;
  const unitCm = parseFloat(panel.dataset.unitCm);
  const unit = panel.dataset.unit;

  const images = new Map();
  svg.querySelectorAll('.lens-layers image[data-layer-id]').forEach((image) => images.set(image.dataset.layerId, image));
  const rows = new Map();
  panel.querySelectorAll('[data-lens-layer]').forEach((row) => rows.set(row.dataset.lensLayer, row));

  const dirty = new Set();
  // Width over height of each image file, once it is known.
  const ratios = new Map();
  let calibrating = null;
  let drag = null;
  // The two points of a scale being set: null, or a list of zero, one or two room points.
  let scale = null;
  let lastRun = { key: null, at: 0 };

  const round = (value, places) => Math.round(value * 10 ** places) / 10 ** places;
  const number = (image, field) => parseFloat(image.dataset[field]);

  function centre(image) {
    return { x: number(image, 'x') + number(image, 'width') / 2, y: number(image, 'y') + number(image, 'height') / 2 };
  }

  /* Turn a vector by the rotation of a layer, or back with `sign` -1. */
  function turn(vector, degrees, sign) {
    const angle = (sign * degrees * Math.PI) / 180;
    return {
      x: vector.x * Math.cos(angle) - vector.y * Math.sin(angle),
      y: vector.x * Math.sin(angle) + vector.y * Math.cos(angle),
    };
  }

  /* ----------------------------------------------------------------------
   * Drawing a layer from its data, and the frame round the one being calibrated
   * ------------------------------------------------------------------- */

  const frame = document.createElementNS(SVG_NS, 'g');
  frame.setAttribute('class', 'lens-calibration');
  const outline = document.createElementNS(SVG_NS, 'rect');
  outline.setAttribute('class', 'lens-calibration__outline');
  frame.appendChild(outline);
  const handles = [
    [-1, -1],
    [1, -1],
    [1, 1],
    [-1, 1],
  ].map(function ([sx, sy]) {
    const handle = document.createElementNS(SVG_NS, 'circle');
    handle.setAttribute('class', 'lens-calibration__handle');
    handle.dataset.sx = sx;
    handle.dataset.sy = sy;
    frame.appendChild(handle);
    return handle;
  });
  const measure = document.createElementNS(SVG_NS, 'g');
  measure.setAttribute('class', 'lens-calibration__measure');

  function apply(image) {
    const data = image.dataset;
    ['x', 'y', 'width', 'height', 'opacity'].forEach((field) => image.setAttribute(field, data[field]));
    const at = centre(image);
    const rotation = number(image, 'rotation');
    const transform = rotation ? `rotate(${rotation} ${at.x} ${at.y})` : '';
    if (transform) image.setAttribute('transform', transform);
    else image.removeAttribute('transform');
    if (data.enabled === 'true') image.removeAttribute('display');
    else image.setAttribute('display', 'none');

    const row = rows.get(data.layerId);
    row.classList.toggle('is-dirty', dirty.has(data.layerId));
    row.querySelector('[data-lens-layer-enabled]').checked = data.enabled === 'true';
    row.querySelector('[data-lens-layer-opacity]').value = data.opacity;
    const rotationInput = row.querySelector('[data-lens-layer-rotation]');
    if (document.activeElement !== rotationInput) rotationInput.value = round(rotation, 1);
    if (image === calibrating) drawFrame();
  }

  /* The frame is sized in room centimetres, so its lines and handles are scaled to stay the same
     size on screen at any zoom. */
  function drawFrame() {
    if (!calibrating) return frame.remove();
    const perPixel = 1 / svg.getScreenCTM().a;
    const width = number(calibrating, 'width');
    const height = number(calibrating, 'height');
    const at = centre(calibrating);
    frame.setAttribute('transform', `translate(${at.x} ${at.y}) rotate(${number(calibrating, 'rotation')})`);
    outline.setAttribute('x', -width / 2);
    outline.setAttribute('y', -height / 2);
    outline.setAttribute('width', width);
    outline.setAttribute('height', height);
    outline.style.strokeWidth = 1.5 * perPixel;
    handles.forEach(function (handle) {
      handle.setAttribute('cx', (handle.dataset.sx * width) / 2);
      handle.setAttribute('cy', (handle.dataset.sy * height) / 2);
      handle.setAttribute('r', 6 * perPixel);
      handle.style.strokeWidth = 1.5 * perPixel;
    });

    measure.replaceChildren();
    (scale || []).forEach(function (point) {
      const dot = document.createElementNS(SVG_NS, 'circle');
      dot.setAttribute('cx', point.x);
      dot.setAttribute('cy', point.y);
      dot.setAttribute('r', 4 * perPixel);
      measure.appendChild(dot);
    });
    if (scale && scale.length === 2) {
      const line = document.createElementNS(SVG_NS, 'line');
      line.setAttribute('x1', scale[0].x);
      line.setAttribute('y1', scale[0].y);
      line.setAttribute('x2', scale[1].x);
      line.setAttribute('y2', scale[1].y);
      line.style.strokeWidth = 2 * perPixel;
      measure.appendChild(line);
    }
    if (!frame.isConnected) svg.append(frame, measure);
  }

  new MutationObserver(drawFrame).observe(svg, { attributes: true, attributeFilter: ['viewBox'] });

  /* ----------------------------------------------------------------------
   * Changing a layer
   * ------------------------------------------------------------------- */

  /* Called before a change. `run` names a change made in small steps, such as a slider being
     pulled or an arrow key held, so the whole run is one step to undo. */
  function begin(run) {
    const now = Date.now();
    if (!run || lastRun.key !== run || now - lastRun.at > RUN) editor.checkpoint();
    lastRun = { key: run || null, at: now };
  }

  function changed(image) {
    dirty.add(image.dataset.layerId);
    apply(image);
    editor.refreshControls();
  }

  /* Resize about `anchor`, a room point that stays where it is, to `width` at the image's own
     proportions. `offset` is where the centre sits from the anchor, in the layer's own axes and
     in units of the new size. */
  function resize(image, anchor, width, offset) {
    const ratio = ratios.get(image.dataset.layerId) || number(image, 'width') / number(image, 'height');
    const height = width / ratio;
    const toCentre = turn({ x: offset.x * width, y: offset.y * height }, number(image, 'rotation'), 1);
    image.dataset.width = round(width, 1);
    image.dataset.height = round(height, 1);
    image.dataset.x = round(anchor.x + toCentre.x - width / 2, 1);
    image.dataset.y = round(anchor.y + toCentre.y - height / 2, 1);
  }

  /* The proportions of the file itself: a layer created by typing a width and a height is
     seldom at them, and a drawing stretched one way cannot be put to scale. */
  function loadRatio(image) {
    const id = image.dataset.layerId;
    if (ratios.has(id)) return;
    const probe = new Image();
    probe.onload = function () {
      if (probe.naturalWidth && probe.naturalHeight) ratios.set(id, probe.naturalWidth / probe.naturalHeight);
    };
    probe.src = image.getAttribute('href');
  }

  /* ----------------------------------------------------------------------
   * Calibration
   * ------------------------------------------------------------------- */

  function calibrate(image) {
    calibrating = image;
    scale = null;
    svg.classList.toggle('lens-floor--calibrating', Boolean(image));
    images.forEach((other) => other.classList.toggle('is-calibrating', other === image));
    rows.forEach(function (row, id) {
      const on = Boolean(image) && id === image.dataset.layerId;
      row.classList.toggle('is-calibrating', on);
      row.querySelector('[data-lens-layer-tools]').hidden = !on;
      row.querySelector('[data-lens-layer-scale-form]').hidden = true;
      const button = row.querySelector('[data-lens-layer-calibrate]');
      button.classList.toggle('active', on);
      button.setAttribute('aria-pressed', String(on));
    });
    if (image) {
      editor.select(null);
      loadRatio(image);
    }
    drawFrame();
    editor.refreshControls();
  }

  function scaleForm() {
    return rows.get(calibrating.dataset.layerId).querySelector('[data-lens-layer-scale-form]');
  }

  function startScale() {
    scale = [];
    scaleForm().hidden = true;
    editor.status.textContent = 'Click the first of two points a known distance apart';
    drawFrame();
  }

  function addScalePoint(point) {
    scale.push({ x: point.x, y: point.y });
    drawFrame();
    if (scale.length === 1) {
      editor.status.textContent = 'Click the second point';
      return;
    }
    editor.status.textContent = '';
    const form = scaleForm();
    form.hidden = false;
    form.querySelector('input').focus();
  }

  function applyScale(distance) {
    const [first, second] = scale;
    const drawn = Math.hypot(second.x - first.x, second.y - first.y);
    if (!(distance > 0) || !drawn) return;
    const factor = (distance * unitCm) / drawn;
    const image = calibrating;
    begin();
    // The first point stays where it is on the room, and the drawing grows or shrinks about it.
    const at = centre(image);
    const width = number(image, 'width') * factor;
    const height = ratios.has(image.dataset.layerId)
      ? width / ratios.get(image.dataset.layerId)
      : number(image, 'height') * factor;
    image.dataset.width = round(width, 1);
    image.dataset.height = round(height, 1);
    image.dataset.x = round(first.x + (at.x - first.x) * factor - width / 2, 1);
    image.dataset.y = round(first.y + (at.y - first.y) * factor - height / 2, 1);
    scale = null;
    scaleForm().hidden = true;
    changed(image);
  }

  /* ----------------------------------------------------------------------
   * The pointer and the keyboard, while a layer is calibrated
   * ------------------------------------------------------------------- */

  function claims(event) {
    if (!calibrating || event.button !== 0) return false;
    const point = editor.toRoom(event);
    if (scale && scale.length < 2) {
      event.preventDefault();
      addScalePoint(point);
      return true;
    }
    const handle = event.target.closest('.lens-calibration__handle');
    if (!handle && event.target !== calibrating) return true;
    event.preventDefault();
    const at = centre(calibrating);
    if (handle) {
      // The corner opposite the one being pulled is the one that stays put.
      const sx = Number(handle.dataset.sx);
      const sy = Number(handle.dataset.sy);
      const corner = turn(
        { x: (-sx * number(calibrating, 'width')) / 2, y: (-sy * number(calibrating, 'height')) / 2 },
        number(calibrating, 'rotation'),
        1
      );
      drag = { anchor: { x: at.x + corner.x, y: at.y + corner.y }, sx: sx, sy: sy, moved: false };
    } else {
      drag = { offsetX: point.x - number(calibrating, 'x'), offsetY: point.y - number(calibrating, 'y'), moved: false };
    }
    svg.setPointerCapture(event.pointerId);
    return true;
  }

  svg.addEventListener('pointermove', function (event) {
    if (!drag || !calibrating) return;
    const point = editor.toRoom(event);
    if (!drag.moved) begin();
    drag.moved = true;
    if (drag.anchor) {
      const pulled = turn({ x: point.x - drag.anchor.x, y: point.y - drag.anchor.y }, number(calibrating, 'rotation'), -1);
      const ratio = number(calibrating, 'width') / number(calibrating, 'height');
      const width = Math.max(Math.abs(pulled.x), Math.abs(pulled.y) * ratio, SMALLEST);
      resize(calibrating, drag.anchor, width, { x: drag.sx / 2, y: drag.sy / 2 });
    } else {
      calibrating.dataset.x = round(point.x - drag.offsetX, 1);
      calibrating.dataset.y = round(point.y - drag.offsetY, 1);
    }
    dirty.add(calibrating.dataset.layerId);
    apply(calibrating);
    editor.showPosition();
  });

  function endDrag(event) {
    if (!drag) return;
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    const moved = drag.moved;
    drag = null;
    if (moved) editor.refreshControls();
  }

  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);

  const NUDGES = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

  document.addEventListener('keydown', function (event) {
    if (!calibrating) return;
    const typing = event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable]');
    if (event.key === 'Escape') {
      if (scale) {
        scale = null;
        scaleForm().hidden = true;
        editor.status.textContent = '';
        return drawFrame();
      }
      return calibrate(null);
    }
    const direction = NUDGES[event.key];
    if (!direction || typing || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    begin(`nudge-${calibrating.dataset.layerId}`);
    const step = event.shiftKey ? 1 : editor.grid || 10;
    calibrating.dataset.x = round(number(calibrating, 'x') + direction[0] * step, 1);
    calibrating.dataset.y = round(number(calibrating, 'y') + direction[1] * step, 1);
    changed(calibrating);
  });

  /* ----------------------------------------------------------------------
   * The panel
   * ------------------------------------------------------------------- */

  /* The rows in the order the layers are drawn, and the weights that keep them in it. */
  function reorder(row, by) {
    const order = Array.from(panel.querySelectorAll('[data-lens-layer]'));
    const from = order.indexOf(row);
    const to = from + by;
    if (to < 0 || to >= order.length) return;
    begin();
    order.splice(to, 0, order.splice(from, 1)[0]);
    order.forEach(function (item, index) {
      const image = images.get(item.dataset.lensLayer);
      const weight = String((index + 1) * 10);
      if (image.dataset.weight !== weight) {
        image.dataset.weight = weight;
        dirty.add(image.dataset.layerId);
      }
    });
    placeInOrder();
    editor.refreshControls();
  }

  function placeInOrder() {
    const byWeight = (a, b) => number(images.get(a), 'weight') - number(images.get(b), 'weight');
    const ids = Array.from(images.keys()).sort(byWeight);
    const list = panel.querySelector('[data-lens-layer-list]');
    ids.forEach(function (id) {
      list.appendChild(rows.get(id));
      images.get(id).parentNode.appendChild(images.get(id));
      apply(images.get(id));
    });
  }

  panel.addEventListener('click', function (event) {
    const row = event.target.closest('[data-lens-layer]');
    if (!row) return;
    const image = images.get(row.dataset.lensLayer);
    if (event.target.closest('[data-lens-layer-calibrate]')) return calibrate(image === calibrating ? null : image);
    if (event.target.closest('[data-lens-layer-up]')) return reorder(row, -1);
    if (event.target.closest('[data-lens-layer-down]')) return reorder(row, 1);
    if (event.target.closest('[data-lens-layer-scale]')) return startScale();
  });

  panel.addEventListener('input', function (event) {
    const row = event.target.closest('[data-lens-layer]');
    if (!row) return;
    const image = images.get(row.dataset.lensLayer);
    if (event.target.matches('[data-lens-layer-enabled]')) {
      begin();
      image.dataset.enabled = String(event.target.checked);
    } else if (event.target.matches('[data-lens-layer-opacity]')) {
      begin(`opacity-${row.dataset.lensLayer}`);
      image.dataset.opacity = event.target.value;
    } else if (event.target.matches('[data-lens-layer-rotation]')) {
      const degrees = parseFloat(event.target.value);
      if (Number.isNaN(degrees)) return;
      begin(`rotation-${row.dataset.lensLayer}`);
      // Kept in [0, 360) because the model validates that range.
      image.dataset.rotation = round(((degrees % 360) + 360) % 360, 1) % 360;
    } else {
      return;
    }
    changed(image);
  });

  panel.addEventListener('submit', function (event) {
    const form = event.target.closest('[data-lens-layer-scale-form]');
    if (!form) return;
    event.preventDefault();
    applyScale(parseFloat(form.querySelector('input').value));
  });

  /* ----------------------------------------------------------------------
   * What the editor asks of a part
   * ------------------------------------------------------------------- */

  editor.addPart({
    snapshot: function () {
      const state = new Map();
      images.forEach(function (image, id) {
        state.set(id, Object.fromEntries(FIELDS.map((field) => [field, image.dataset[field]])));
      });
      return { layers: state, dirty: new Set(dirty) };
    },

    restore: function (state) {
      dirty.clear();
      state.dirty.forEach((id) => dirty.add(id));
      state.layers.forEach((fields, id) => Object.assign(images.get(id).dataset, fields));
      scale = null;
      placeInOrder();
    },

    pending: () => dirty.size,
    claims: claims,

    position: function () {
      if (!calibrating) return '';
      const data = calibrating.dataset;
      return `${data.name} · x ${data.x} cm · y ${data.y} cm · ${data.width} × ${data.height} cm · ${data.rotation}°`;
    },

    save: async function (failures) {
      for (const id of Array.from(dirty)) {
        const image = images.get(id);
        try {
          await editor.request('PATCH', rows.get(id).dataset.url, {
            x: number(image, 'x'),
            y: number(image, 'y'),
            width: number(image, 'width'),
            height: number(image, 'height'),
            rotation: number(image, 'rotation'),
            opacity: number(image, 'opacity'),
            weight: number(image, 'weight'),
            enabled: image.dataset.enabled === 'true',
          });
          dirty.delete(id);
          rows.get(id).classList.remove('is-dirty');
        } catch (error) {
          failures.push(`layer ${image.dataset.name}: ${error.message}`);
        }
      }
    },
  });

  // A link from the layer form asks for the layer just made, which is the newest one.
  if (new URLSearchParams(window.location.hash.slice(1)).get('calibrate') === 'latest' && images.size) {
    const newest = String(Math.max(...Array.from(images.keys()).map(Number)));
    calibrate(images.get(newest));
  }
})();
