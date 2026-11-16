/*
 * Rack placement editor.
 *
 * Plain JavaScript against the SVG the server already rendered. There is no framework, no
 * build step and no second model of the floor: a rack's position lives in its data attributes
 * and its transform, and those are the only state the editor keeps.
 *
 * Nothing is written until Save. Every change is collected and sent as one batch through the
 * ordinary REST API, so the editor has no private endpoint and no permission of its own.
 */
(function () {
  'use strict';

  const config = JSON.parse(document.getElementById('lens-editor-config').textContent);
  const svg = document.querySelector('.lens-floor');
  if (!svg) return;

  svg.classList.add('lens-floor--editing');

  const status = document.querySelector('[data-lens-status]');
  const saveButton = document.querySelector('[data-lens-save]');
  const removeButton = document.querySelector('[data-lens-remove]');
  const rotateButtons = document.querySelectorAll('[data-lens-rotate]');
  const unplacedPanel = document.querySelector('[data-lens-unplaced]');

  const floorWidth = parseFloat(svg.dataset.width);
  const floorDepth = parseFloat(svg.dataset.depth);
  const grid = config.gridSize || 0;

  // rackId -> 'update' | 'create' | 'delete'. A rack created and then deleted before saving
  // cancels out, which is why intent is tracked per rack rather than as a list of edits.
  const pending = new Map();
  let selected = null;
  let pendingRack = null; // a rack chosen from the unplaced panel, waiting for a click

  const racksLayer = svg.querySelector('.lens-racks');
  const position = document.querySelector('[data-lens-position]');
  const undoButton = document.querySelector('[data-lens-undo]');
  const redoButton = document.querySelector('[data-lens-redo]');

  // Every rack drawn and every panel row made in this session, by rack id, on the page or off
  // it: undo puts back the element that was taken away, not a copy of it.
  const rackNodes = new Map();
  svg.querySelectorAll('.lens-rack').forEach((node) => rackNodes.set(node.dataset.rackId, node));
  const panelItems = new Map();
  unplacedPanel.querySelectorAll('[data-lens-rack]').forEach((item) => panelItems.set(item.dataset.lensRack, item));

  /* ----------------------------------------------------------------------
   * Undo and redo
   *
   * A step is the whole layout as it stood before a change: where every rack on the floor is, and
   * what is waiting to be saved. Whole states rather than inverse operations, because a removal,
   * a placement and a move each touch the floor, the panel and the pending set, and one restore
   * that sets all three cannot leave them disagreeing. Saving empties both stacks: what is on
   * the server cannot be undone from here.
   * ------------------------------------------------------------------- */

  const undone = [];
  const redone = [];
  // What else on the floor is edited here and saved with the racks, such as the background
  // layers. A part gives `snapshot()`, `restore(state)`, `pending()`, the number of its unsaved
  // changes, `claims(event)`, true when a press on the plan is its own, `position()`, the text for what it has
  // selected, and `save(failures)`.
  const parts = [];
  // The rack and the time of the last arrow-key move, so a run of presses is one step.
  let lastNudge = { id: null, at: 0 };

  function snapshot() {
    const placed = new Map();
    svg.querySelectorAll('.lens-rack').forEach(function (node) {
      placed.set(node.dataset.rackId, { x: node.dataset.x, y: node.dataset.y, rotation: node.dataset.rotation });
    });
    return { placed: placed, pending: new Map(pending), parts: parts.map((part) => part.snapshot()) };
  }

  function restore(state) {
    rackNodes.forEach(function (node, rackId) {
      const at = state.placed.get(rackId);
      const item = panelItems.get(rackId);
      if (at) {
        Object.assign(node.dataset, at);
        applyTransform(node);
        if (!node.isConnected) racksLayer.appendChild(node);
        if (item) item.remove();
      } else {
        node.remove();
        if (item && !item.isConnected) unplacedPanel.prepend(item);
      }
      node.classList.toggle('is-dirty', state.pending.has(rackId));
    });
    pending.clear();
    state.pending.forEach((intent, rackId) => pending.set(rackId, intent));
    pendingRack = null;
    unplacedPanel.querySelectorAll('.is-selected').forEach((node) => node.classList.remove('is-selected'));
    parts.forEach((part, index) => part.restore(state.parts[index]));
    if (selected && !selected.isConnected) select(null);
    refreshControls();
  }

  // Called before every change, so the state it leaves behind is the one undo returns to.
  function checkpoint() {
    undone.push(snapshot());
    redone.length = 0;
    lastNudge = { id: null, at: 0 };
  }

  function undo() {
    if (!undone.length) return;
    redone.push(snapshot());
    restore(undone.pop());
  }

  function redo() {
    if (!redone.length) return;
    undone.push(snapshot());
    restore(redone.pop());
  }

  /* Where the selected rack stands, in the numbers the placement stores. */
  function showPosition() {
    if (!position) return;
    if (!selected) {
      position.textContent = parts.map((part) => part.position()).find(Boolean) || '';
      return;
    }
    const data = selected.dataset;
    const cm = (value) => String(Math.round(parseFloat(value) * 10) / 10);
    position.textContent = `${data.name || ''} · x ${cm(data.x)} cm · y ${cm(data.y)} cm · ${cm(data.rotation)}°`;
  }

  function snap(value) {
    return grid > 0 ? Math.round(value / grid) * grid : Math.round(value * 10) / 10;
  }

  function clamp(value, half, limit) {
    return Math.min(Math.max(value, half), limit - half);
  }

  /* Convert a pointer event to room coordinates. getScreenCTM accounts for the viewBox, the
     current page zoom and any scrolling, so this stays correct without tracking any of them. */
  function toRoom(event) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse());
  }

  function applyTransform(node) {
    const x = parseFloat(node.dataset.x);
    const y = parseFloat(node.dataset.y);
    const rotation = parseFloat(node.dataset.rotation);
    node.setAttribute('transform', `translate(${x} ${y}) rotate(${rotation})`);
    // The text turns with the rack, so a rack that faces down the plan gets its text turned back.
    const upsideDown = rotation > 90 && rotation <= 270;
    node.querySelectorAll('text').forEach(function (text) {
      if (upsideDown) text.setAttribute('transform', 'rotate(180)');
      else text.removeAttribute('transform');
    });
  }

  function markDirty(node, intent) {
    const rackId = node.dataset.rackId;
    // A rack placed in this session stays a create even after it is dragged again.
    if (!(pending.get(rackId) === 'create' && intent === 'update')) {
      pending.set(rackId, intent);
    }
    node.classList.add('is-dirty');
    refreshControls();
  }

  function select(node) {
    if (selected) selected.classList.remove('is-selected');
    selected = node;
    if (node) node.classList.add('is-selected');
    refreshControls();
  }

  function changeCount() {
    return parts.reduce((count, part) => count + part.pending(), pending.size);
  }

  function refreshControls() {
    const hasSelection = Boolean(selected);
    const changes = changeCount();
    // A rack placed in this session can always be taken off again: there is nothing to delete
    // on the server yet. A saved one needs the delete permission.
    const removable = selected && (config.canDelete || pending.get(selected.dataset.rackId) === 'create');
    removeButton.disabled = !removable;
    rotateButtons.forEach((b) => { b.disabled = !hasSelection; });
    saveButton.disabled = changes === 0;
    if (undoButton) undoButton.disabled = undone.length === 0;
    if (redoButton) redoButton.disabled = redone.length === 0;
    showPosition();
    status.textContent = changes ? `${changes} unsaved change${changes === 1 ? '' : 's'}` : '';
  }

  /* ----------------------------------------------------------------------
   * Dragging
   * ------------------------------------------------------------------- */

  let drag = null;

  svg.addEventListener('pointerdown', function (event) {
    if (parts.some((part) => part.claims(event))) return;
    const node = event.target.closest('.lens-rack');
    if (!node) {
      if (pendingRack) placeRack(event);
      return;
    }
    event.preventDefault();
    select(node);
    const point = toRoom(event);
    drag = {
      node: node,
      // Remember where in the rack it was grabbed, so it does not jump to the cursor.
      offsetX: point.x - parseFloat(node.dataset.x),
      offsetY: point.y - parseFloat(node.dataset.y),
      moved: false,
    };
    node.classList.add('is-dragging');
    svg.setPointerCapture(event.pointerId);
  });

  svg.addEventListener('pointermove', function (event) {
    if (!drag) return;
    const point = toRoom(event);
    const node = drag.node;
    const halfW = parseFloat(node.dataset.width) / 2;
    const halfD = parseFloat(node.dataset.depth) / 2;

    if (!drag.moved) checkpoint();
    node.dataset.x = clamp(snap(point.x - drag.offsetX), halfW, floorWidth);
    node.dataset.y = clamp(snap(point.y - drag.offsetY), halfD, floorDepth);
    applyTransform(node);
    drag.moved = true;
    showPosition();
  });

  function endDrag(event) {
    if (!drag) return;
    drag.node.classList.remove('is-dragging');
    if (drag.moved) markDirty(drag.node, 'update');
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    drag = null;
  }

  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);

  /* ----------------------------------------------------------------------
   * Rotate, remove, place
   * ------------------------------------------------------------------- */

  rotateButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      if (!selected) return;
      const by = parseFloat(button.dataset.lensRotate);
      checkpoint();
      // Kept in [0, 360) because the model validates that range.
      const next = (parseFloat(selected.dataset.rotation) + by + 360) % 360;
      selected.dataset.rotation = next;
      applyTransform(selected);
      markDirty(selected, 'update');
    });
  });

  removeButton.addEventListener('click', function () {
    if (!selected || removeButton.disabled) return;
    const node = selected;
    const rackId = node.dataset.rackId;
    checkpoint();

    if (pending.get(rackId) === 'create') {
      // Never saved, so there is nothing on the server to delete.
      pending.delete(rackId);
    } else {
      pending.set(rackId, 'delete');
    }
    // The drawn label may be trimmed to fit its cabinet, so the name comes from the data
    // attribute that carries it whole; otherwise a rack put back on the panel keeps the
    // ellipsis, and is placed again under a name that is not its own.
    unplacedPanel.prepend(
      panelItems.get(rackId) ||
        unplacedItem(
          rackId,
          node.dataset.name || node.querySelector('.lens-rack-label').textContent,
          node.dataset.width,
          node.dataset.depth
        )
    );
    node.remove();
    select(null);
    refreshControls();
  });

  function unplacedItem(rackId, name, width, depth) {
    const item = document.createElement('div');
    item.className = 'lens-unplaced__item';
    item.dataset.lensRack = rackId;
    item.dataset.rackName = name;
    item.dataset.width = width;
    item.dataset.depth = depth;
    // textContent, not innerHTML. A rack name is free text somebody types, so putting it in
    // markup here would run whatever they typed, for everyone who opens the editor.
    const label = document.createElement('span');
    label.textContent = name;
    item.appendChild(label);
    panelItems.set(rackId, item);
    return item;
  }

  unplacedPanel.addEventListener('click', function (event) {
    const item = event.target.closest('[data-lens-rack]');
    if (!item) return;
    // Placing a rack is a create, unless it was taken off in this session and goes back down.
    if (!config.canAdd && pending.get(item.dataset.lensRack) !== 'delete') {
      status.textContent = 'You may not place racks on this floor.';
      return;
    }
    unplacedPanel.querySelectorAll('.is-selected').forEach((n) => n.classList.remove('is-selected'));
    if (pendingRack && pendingRack.id === item.dataset.lensRack) {
      pendingRack = null;
      status.textContent = '';
      return;
    }
    item.classList.add('is-selected');
    pendingRack = { id: item.dataset.lensRack, name: item.dataset.rackName, node: item };
    status.textContent = `Click the floor to place ${pendingRack.name}`;
  });

  /* A rack placed here is drawn at its own footprint, which the server resolved from the rack's
     outer dimensions and put on the panel item, so it is the size it will be after a reload. */
  function placeRack(event) {
    const point = toRoom(event);
    const width = parseFloat(pendingRack.node.dataset.width);
    const depth = parseFloat(pendingRack.node.dataset.depth);
    checkpoint();
    // A rack that stood on the floor earlier in this session goes back as the element it was.
    const group = rackNodes.get(pendingRack.id) || newRackNode(pendingRack.id, pendingRack.name, width, depth);
    group.classList.add('is-dirty');
    group.dataset.x = clamp(snap(point.x), width / 2, floorWidth);
    group.dataset.y = clamp(snap(point.y), depth / 2, floorDepth);
    group.dataset.rotation = 0;
    applyTransform(group);
    racksLayer.appendChild(group);

    // A rack taken off the floor in this session still has its placement on the server until
    // Save, so putting it back down moves that placement rather than creating a second one.
    pending.set(pendingRack.id, pending.get(pendingRack.id) === 'delete' ? 'update' : 'create');
    pendingRack.node.remove();
    pendingRack = null;
    select(group);
  }

  function newRackNode(rackId, name, width, depth) {
    const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    group.setAttribute('class', 'lens-rack');
    group.dataset.rackId = rackId;
    group.dataset.name = name;
    group.dataset.width = width;
    group.dataset.depth = depth;
    /* Built as nodes rather than as markup, so the name goes in as text.
     *
     * A rack name is free text somebody types. Interpolated into `innerHTML` it is markup, and
     * a rack named after an <img> tag would run its onerror for everyone who opens the layout
     * editor. The same rule the trace panel and the hover cards already follow. */
    const svgNS = 'http://www.w3.org/2000/svg';
    const shape = (tag, attrs) => {
      const node = document.createElementNS(svgNS, tag);
      Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
      return node;
    };

    group.appendChild(
      shape('rect', {
        class: 'lens-rack-body',
        x: -width / 2,
        y: -depth / 2,
        width: width,
        height: depth,
        rx: 4,
      })
    );
    group.appendChild(
      shape('rect', {
        class: 'lens-rack-front',
        x: -width / 2,
        y: -depth / 2,
        width: width,
        height: 7,
      })
    );
    const label = shape('text', {
      class: 'lens-rack-label',
      x: 0,
      y: 0,
      'dominant-baseline': 'middle',
      'text-anchor': 'middle',
    });
    // The size every other name on this plan is drawn at, so the new rack matches its neighbours.
    const sibling = svg.querySelector('.lens-rack-label');
    if (sibling && sibling.style.fontSize) label.style.fontSize = sibling.style.fontSize;
    label.textContent = name;
    group.appendChild(label);
    rackNodes.set(rackId, group);
    return group;
  }

  /* ----------------------------------------------------------------------
   * The keyboard
   *
   * The arrows move the selected rack by one grid step, or by one centimetre with Shift, which is
   * how a row is put in line without a steady hand. Ctrl + Z undoes and Ctrl + Shift + Z or
   * Ctrl + Y redoes; Cmd on a Mac.
   * ------------------------------------------------------------------- */

  const NUDGES = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  // Presses closer together than this, in milliseconds, are one step to undo.
  const NUDGE_RUN = 800;

  document.addEventListener('keydown', function (event) {
    const typing = event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable]');
    if (typing) return;

    if ((event.ctrlKey || event.metaKey) && !event.altKey) {
      const key = event.key.toLowerCase();
      if (key === 'z' || key === 'y') {
        event.preventDefault();
        if (key === 'y' || event.shiftKey) redo();
        else undo();
      }
      return;
    }

    const direction = NUDGES[event.key];
    if (!direction || !selected) return;
    event.preventDefault();
    const rackId = selected.dataset.rackId;
    const now = Date.now();
    if (lastNudge.id !== rackId || now - lastNudge.at > NUDGE_RUN) checkpoint();
    lastNudge = { id: rackId, at: now };

    const step = event.shiftKey ? 1 : grid || 10;
    const halfW = parseFloat(selected.dataset.width) / 2;
    const halfD = parseFloat(selected.dataset.depth) / 2;
    selected.dataset.x = clamp(parseFloat(selected.dataset.x) + direction[0] * step, halfW, floorWidth);
    selected.dataset.y = clamp(parseFloat(selected.dataset.y) + direction[1] * step, halfD, floorDepth);
    applyTransform(selected);
    markDirty(selected, 'update');
  });

  if (undoButton) undoButton.addEventListener('click', undo);
  if (redoButton) redoButton.addEventListener('click', redo);

  /* ----------------------------------------------------------------------
   * Saving
   * ------------------------------------------------------------------- */

  /* NetBox sets CSRF_COOKIE_HTTPONLY, so document.cookie cannot see the token and the write
     comes back 403 "CSRF Failed". The hidden input Django renders is the readable copy. */
  function csrfToken() {
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  async function request(method, url, body) {
    const response = await fetch(url, {
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
      },
      credentials: 'same-origin',
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      throw new Error(`${method} ${url} returned ${response.status}`);
    }
    return response.status === 204 ? null : response.json();
  }

  /* The REST API keys a placement by its own id, not by the rack, so an update and a delete
     both need one. The whole floor is read in one request rather than one per rack: saving a
     row of twenty racks was forty round trips, half of them asking the same question twenty
     times. Read at save time rather than carried in the markup, which would go stale the
     moment somebody edited a placement in another tab.

     Paged, because a large hall can hold more placements than the API returns at once and a
     truncated map would report every rack past the first page as "no longer exists". */
  async function placementIdsByRack() {
    const byRack = new Map();
    let url = `${config.placementsUrl}?floor_id=${config.floorId}&limit=500`;
    while (url) {
      const page = await request('GET', url);
      page.results.forEach((row) => byRack.set(String(row.rack.id), row.id));
      url = page.next;
    }
    return byRack;
  }

  saveButton.addEventListener('click', async function () {
    undone.length = 0;
    redone.length = 0;
    saveButton.disabled = true;
    status.textContent = 'Saving...';
    const failures = [];

    // One read for the whole floor, before any write, so the loop below spends a request per
    // change rather than two.
    let placementIds;
    try {
      placementIds = await placementIdsByRack();
    } catch (error) {
      status.textContent = 'Could not read the current layout. See the console.';
      status.classList.add('text-danger');
      console.error('netbox-spatial-lens could not read placements:', error);
      saveButton.disabled = false;
      return;
    }

    // A copy, because a change that is saved leaves `pending` inside the loop.
    for (const [rackId, intent] of Array.from(pending)) {
      const node = svg.querySelector(`.lens-rack[data-rack-id="${rackId}"]`);
      try {
        if (intent === 'create') {
          await request('POST', config.placementsUrl, {
            floor: config.floorId,
            rack: Number(rackId),
            x: parseFloat(node.dataset.x),
            y: parseFloat(node.dataset.y),
            rotation: parseFloat(node.dataset.rotation),
          });
        } else if (intent === 'update') {
          const id = placementIds.get(rackId);
          if (id === undefined) throw new Error('placement no longer exists');
          await request('PATCH', `${config.placementsUrl}${id}/`, {
            x: parseFloat(node.dataset.x),
            y: parseFloat(node.dataset.y),
            rotation: parseFloat(node.dataset.rotation),
          });
        } else if (intent === 'delete') {
          const id = placementIds.get(rackId);
          if (id !== undefined) await request('DELETE', `${config.placementsUrl}${id}/`);
        }
        // A second Save after a failure must not send a create twice: the API refuses it.
        pending.delete(rackId);
        if (node) node.classList.remove('is-dirty');
      } catch (error) {
        failures.push(`${rackId}: ${error.message}`);
      }
    }

    for (const part of parts) await part.save(failures);

    if (failures.length) {
      refreshControls();
      status.textContent = `${failures.length} change${failures.length === 1 ? '' : 's'} failed. See the console.`;
      status.classList.add('text-danger');
      console.error('netbox-spatial-lens could not save:', failures);
      return;
    }

    status.classList.remove('text-danger');
    // After refreshControls, which clears the message when nothing is pending. Setting it
    // first meant "Saved" was wiped in the same breath and the save looked like it did
    // nothing at all.
    refreshControls();
    status.textContent = 'Saved';
  });

  window.addEventListener('beforeunload', function (event) {
    if (changeCount()) event.preventDefault();
  });

  window.lensEditor = {
    svg: svg,
    status: status,
    showPosition: showPosition,
    grid: grid,
    toRoom: toRoom,
    checkpoint: checkpoint,
    refreshControls: refreshControls,
    request: request,
    select: select,
    addPart: function (part) {
      parts.push(part);
      refreshControls();
    },
  };

  refreshControls();
})();
