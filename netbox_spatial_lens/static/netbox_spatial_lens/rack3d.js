/*
 * The rack in 3D.
 *
 * Drawn from the scene the server built (`scene.py`): device boxes wearing their device type
 * images, the cabinet around them, and every cable along the path the server routed through the
 * cable managers. Nothing here decides where anything goes. It draws on the stage `stage3d.js`
 * sets up, and keeps the selection, telling `rack_panel.js` what is selected so the column
 * beside the drawing can follow it.
 */

import { drawCabinet, drawDevice } from 'lens/cabinet3d';
import { PICK_LAYER, follow, isDark, openStage } from 'lens/stage3d';

const panel = window.lensRackPanel;
const element = document.querySelector('[data-lens-3d]');
const configNode = document.getElementById('lens-rack3d-config');

// Opacity of a device or cable that is out of focus: left out by a filter, or not part of the
// selection. A filter hides harder than a selection, which only puts the rest behind glass.
const FILTERED_OPACITY = 0.08;
const DIMMED_DEVICE_OPACITY = 0.2;
const RELATED_DEVICE_OPACITY = 0.5;
const DIMMED_CABLE_OPACITY = 0.1;
// A cable is thin and hard to hit, so it is picked by an invisible tube this much fatter.
const PICK_RADIUS = 11;
const CABLE_RADIUS = { power: 4.2, default: 3.2 };
// How far a cable's corners are rounded, in millimetres, where the segments are long enough.
const CORNER_RADIUS = 18;
// The names of the cables leaving the rack, stacked this far apart over the roof.
const END_LABEL_STEP = 70;

const VIEWS = {
  front: [0, 0.05, 1],
  rear: [0, 0.05, -1],
  side: [1, 0.05, 0],
  angle: [0.85, 0.42, 1.1],
};

function build(stage, config) {
  const { THREE, scene } = stage;
  const { rack, devices, cables, reservations, free } = config.scene;
  const colours = config.colours;
  const controlsBar = element.querySelector('[data-lens-3d-controls]');

  /* ----------------------------------------------------------------------
   * The cabinet
   * ------------------------------------------------------------------- */

  drawCabinet(stage, scene, rack);

  const interior = rack.interior;
  const interiorTop = rack.plinth + interior;
  const post = 26;
  const halfW = rack.width / 2;
  const halfD = rack.depth / 2;

  /* The unit numbers, on a strip beside the front rail and another beside the rear one. Drawn
     into a texture rather than as page elements, so they turn with the rack and stay where
     they are fixed. Redrawn when the theme changes. */
  function rulerTexture() {
    const units = rack.units.length;
    const perUnit = Math.max(16, Math.min(48, Math.floor(8192 / units)));
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = perUnit * units;
    const context = canvas.getContext('2d');
    context.fillStyle = isDark() ? 'rgba(229, 231, 235, .85)' : 'rgba(33, 37, 41, .8)';
    context.strokeStyle = isDark() ? 'rgba(229, 231, 235, .25)' : 'rgba(33, 37, 41, .22)';
    context.font = `600 ${Math.round(perUnit * 0.48)}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    rack.units.forEach(function ([unit, y]) {
      const row = ((interiorTop - y) / rack.unitHeight - 0.5) * perUnit;
      context.fillText(String(unit), 32, row + perUnit / 2);
      context.beginPath();
      context.moveTo(8, row);
      context.lineTo(56, row);
      context.stroke();
    });
    return stage.finishTexture(new THREE.CanvasTexture(canvas));
  }

  const rulerMaterials = [
    { z: rack.frontRailZ + 2, x: -(rack.faceplate / 2 + 14), turn: 0 },
    { z: rack.rearRailZ - 2, x: rack.faceplate / 2 + 14, turn: Math.PI },
  ].map(function ({ x, z, turn }) {
    const material = new THREE.MeshBasicMaterial({ map: rulerTexture(), transparent: true, depthWrite: false });
    const strip = new THREE.Mesh(new THREE.PlaneGeometry(22, interior), material);
    strip.position.set(x, rack.plinth + interior / 2, z);
    strip.rotation.y = turn;
    scene.add(strip);
    return material;
  });

  stage.onThemeChange(function () {
    rulerMaterials.forEach(function (material) {
      material.map.dispose();
      material.map = rulerTexture();
    });
    applyHighlightColour();
  });

  // The cable managers, as the outline of the space the lanes run in.
  const managerDepth = rack.rearRailZ - (-halfD + post);
  Object.values(rack.managers).forEach(function ([x, width]) {
    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(width, interior, managerDepth)),
      new THREE.LineBasicMaterial({ color: 0x8a94a3, transparent: true, opacity: 0.28 })
    );
    outline.position.set(x, rack.plinth + interior / 2, rack.rearRailZ - managerDepth / 2);
    scene.add(outline);
  });

  /* ----------------------------------------------------------------------
   * Devices
   * ------------------------------------------------------------------- */

  let mode = window.lensState && window.lensState.get('mode')[0] === 'colour' ? 'colour' : 'images';

  const highlight = new THREE.Color();
  function applyHighlightColour() {
    highlight.set(isDark() ? colours.highlightDark : colours.highlight);
    deviceViews.forEach((view) => view.outline.material.color.copy(highlight));
  }

  function deviceView(device) {
    const [x, y, z, w, h, d] = device.box;
    const tags = [];
    // The colouring, as a tag down the left ear of whichever face you are looking at, so it is
    // there in Images mode without painting over the photograph. Shown once an image is.
    const box = drawDevice(stage, scene, device, {
      onPaint: () => tags.forEach((tag) => (tag.visible = mode === 'images' && box.hasImage())),
    });
    box.mesh.userData.device = box;

    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(w + 2, h + 2, d + 2)),
      new THREE.LineBasicMaterial({ transparent: true, opacity: 0, depthTest: false })
    );
    outline.position.copy(box.mesh.position);
    outline.renderOrder = 5;
    scene.add(outline);

    const tagMaterial = new THREE.MeshBasicMaterial({ color: new THREE.Color(device.colour) });
    [
      [z + d / 2 + 0.6, -w / 2 + 5, 0],
      [z - d / 2 - 0.6, w / 2 - 5, Math.PI],
    ].forEach(function ([tagZ, tagX, turn]) {
      const tag = new THREE.Mesh(new THREE.PlaneGeometry(6, Math.max(4, h - 6)), tagMaterial);
      tag.position.set(x + tagX, y, tagZ);
      tag.rotation.y = turn;
      scene.add(tag);
      tags.push(tag);
    });

    // The name belongs to the face it is written on, so it is only shown while that face is
    // turned towards the camera; from the other side it would float over the wrong device.
    const name = stage.label(device.label, 'lens-3d__name');
    const facingZ = device.facing === 'rear' ? z - d / 2 - 1 : z + d / 2 + 1;
    const facingX = device.facing === 'rear' ? w / 2 - 36 : -w / 2 + 36;
    name.position.set(x + facingX, y, facingZ);
    name.center.set(device.facing === 'rear' ? 1 : 0, 0.5);
    scene.add(name);

    return Object.assign(box, { outline, tags, tagMaterial, name });
  }

  const deviceViews = devices.map(deviceView);
  const deviceById = new Map(deviceViews.map((view) => [String(view.device.id), view]));

  deviceViews.forEach((view) => view.paint(mode));

  const toCamera = new THREE.Vector3();
  stage.beforeLabels(function () {
    deviceViews.forEach(function (view) {
      toCamera.subVectors(stage.camera.position, view.name.position);
      view.name.visible = Boolean(view.name.userData.wanted) && toCamera.dot(view.normal) > 0;
    });
  });

  /* ----------------------------------------------------------------------
   * Reserved and free units
   * ------------------------------------------------------------------- */

  const reservedColour = new THREE.Color(colours.reserved);
  const reservationViews = reservations.map(function (band) {
    const [x, y, z, w, h, d] = band.box;
    const material = new THREE.MeshStandardMaterial({
      color: reservedColour,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
      roughness: 0.8,
    });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
    mesh.position.set(x, y, z);
    mesh.layers.enable(PICK_LAYER);
    scene.add(mesh);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(mesh.geometry),
      new THREE.LineBasicMaterial({ color: reservedColour, transparent: true, opacity: 0.8 })
    );
    edges.position.copy(mesh.position);
    scene.add(edges);
    const view = { band, mesh, material, edges };
    mesh.userData.reservation = view;
    return view;
  });

  const freeLabels = free.map(function (band) {
    const [x, y, z, w, , d] = band.box;
    const node = stage.label(band.label, 'lens-3d__free');
    node.position.set(x + w / 2 - 30, y, z + d / 2 + 1);
    node.center.set(1, 0.5);
    scene.add(node);
    return node;
  });

  /* ----------------------------------------------------------------------
   * Cables
   * ------------------------------------------------------------------- */

  const pickMaterial = new THREE.MeshBasicMaterial();

  const cableViews = cables.map(function (cable) {
    const path = stage.roundedPath(cable.points, CORNER_RADIUS);
    const segments = Math.max(24, Math.round(path.getLength() / 12));
    const radius = CABLE_RADIUS[cable.kind] || CABLE_RADIUS.default;
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(cable.colour),
      roughness: 0.5,
      metalness: 0.05,
      emissive: new THREE.Color(cable.colour),
      emissiveIntensity: 0,
    });
    scene.add(new THREE.Mesh(new THREE.TubeGeometry(path, segments, radius, 8, false), material));

    const pick = new THREE.Mesh(new THREE.TubeGeometry(path, Math.ceil(segments / 3), PICK_RADIUS, 5, false), pickMaterial);
    pick.layers.set(PICK_LAYER);
    scene.add(pick);

    let marker = null;
    let end = null;
    if (!cable.internal) {
      const last = cable.points[cable.points.length - 1];
      marker = new THREE.Mesh(new THREE.SphereGeometry(radius * 2.6, 20, 14), material);
      marker.position.set(last[0], last[1], last[2]);
      scene.add(marker);
      end = stage.label(cable.endLabel, 'lens-3d__end');
      end.center.set(0.5, 1);
      scene.add(end);
    }
    const view = { cable, pick, material, marker, end };
    pick.userData.cable = view;
    return view;
  });

  /* The names of the cables leaving the rack that are on show, one above the other over the
     roof. Their markers end at one height, so the names would otherwise print over each other;
     stacked in the order the lanes run, each name sits above the marker nearest it. */
  const roofY = rack.height + 60;

  function stackEndLabels() {
    const shown = cableViews.filter((view) => view.end && view.end.visible);
    shown.sort((a, b) => a.marker.position.x - b.marker.position.x || a.marker.position.z - b.marker.position.z);
    shown.forEach(function (view, index) {
      const marker = view.marker.position;
      view.end.position.set(marker.x, Math.max(roofY, marker.y) + 30 + index * END_LABEL_STEP, marker.z);
    });
  }

  /* ----------------------------------------------------------------------
   * Selection and filters
   * ------------------------------------------------------------------- */

  // { type: 'device' | 'cable' | 'reservation', id: string } or null
  let selection = null;

  function legendBands(group) {
    return new Set(window.lensLegendFilter ? window.lensLegendFilter.bands(group) : []);
  }

  function finderKeeps(group, ids) {
    if (!window.lensFinder) return true;
    const picked = window.lensFinder.picked(group);
    return !picked.size || ids.some((id) => picked.has(id));
  }

  /* Whether a device survives every narrowing: the colouring's legend, each finder that carries
     ids for it, and the find box. The drawing is a canvas, so it reads the picks from the legend
     and the finders rather than from the classes they set on the page. */
  function deviceInFocus(device, bands) {
    if (bands.size && !bands.has(device.band)) return false;
    const keptByFinders = Object.entries(device.filters).every(([group, ids]) =>
      finderKeeps(group, String(ids).split(/\s+/).filter(Boolean))
    );
    return keptByFinders && panel.matchesSearch(device.label, device.assetTag);
  }

  function cableInFocus(cable, bands) {
    return (!bands.size || bands.has(cable.kind)) && finderKeeps('cables', [String(cable.id)]);
  }

  function apply() {
    const deviceBands = legendBands('devices');
    const cableBands = legendBands('cables');
    const hovered = stage.hovered();
    const showNames = stage.showNames();

    const litCables = new Set();
    const litDevices = new Set();
    if (selection && selection.type !== 'reservation') {
      cableViews.forEach(function ({ cable }) {
        const ends = [String(cable.deviceId), cable.peerDeviceId ? String(cable.peerDeviceId) : null];
        const hit = selection.type === 'device' ? ends.includes(selection.id) : String(cable.id) === selection.id;
        if (!hit) return;
        litCables.add(String(cable.id));
        ends.filter(Boolean).forEach((id) => litDevices.add(id));
      });
      if (selection.type === 'device') litDevices.add(selection.id);
    }

    let shown = 0;
    deviceViews.forEach(function (view) {
      const id = String(view.device.id);
      const inFocus = deviceInFocus(view.device, deviceBands);
      if (inFocus) shown += 1;
      const primary = selection && selection.type === 'device' && selection.id === id;
      const related = litDevices.has(id) && !primary;
      // A cable's two ends are what a cable selection is about, so they stay solid. Around a
      // selected device everything else turns to glass, the devices it reaches less so, which
      // is what lets its cables be followed through the cabinet behind them.
      const solid = !selection || primary || (selection.type === 'cable' && related);

      let opacity = 1;
      if (!inFocus) opacity = FILTERED_OPACITY;
      else if (!solid) opacity = related ? RELATED_DEVICE_OPACITY : DIMMED_DEVICE_OPACITY;
      [view.faces.front, view.faces.rear, view.body, view.tagMaterial].forEach((m) => stage.setOpacity(m, opacity));
      view.mesh.castShadow = opacity === 1;

      const glow = primary ? 0.16 : related ? 0.1 : 0;
      [view.faces.front, view.faces.rear].forEach(function (material) {
        material.emissive.copy(highlight);
        material.emissiveIntensity = glow;
      });

      // Drawn over everything for the one selected device, so it can be found from any side;
      // the hovered one is outlined where it is visible, and nothing else is outlined at all.
      const outline = view.outline.material;
      outline.opacity = primary ? 1 : hovered === view ? 0.6 : 0;
      outline.depthTest = !primary;

      // On a colour face the name is already painted on, so the label is only added for the
      // device under the pointer or the one selected.
      view.name.userData.wanted = inFocus && ((showNames && mode === 'images') || primary || hovered === view);
    });

    cableViews.forEach(function (view) {
      const id = String(view.cable.id);
      const inFocus = cableInFocus(view.cable, cableBands);
      const lit = litCables.has(id);
      stage.setOpacity(view.material, !inFocus ? FILTERED_OPACITY : selection && !lit ? DIMMED_CABLE_OPACITY : 1);
      const primary = lit && selection.type === 'cable' && selection.id === id;
      view.material.emissiveIntensity = primary ? 0.75 : lit || hovered === view ? 0.35 : 0;
      // Only for the cables in hand: every uplink of a switch ends at the same roof, and their
      // names all at once are a pile of overlapping boxes.
      if (view.end) view.end.visible = inFocus && (lit || hovered === view);
    });
    stackEndLabels();

    reservationViews.forEach(function (view) {
      const inFocus = !deviceBands.size || deviceBands.has('reserved');
      const primary = selection && selection.type === 'reservation' && selection.id === String(view.band.id);
      view.material.opacity = !inFocus ? 0.04 : primary ? 0.45 : 0.22;
      view.edges.material.opacity = inFocus ? 0.8 : 0.1;
    });

    freeLabels.forEach((node) => (node.visible = showNames && !selection));

    panel.reportShown(shown);
    const selected = selection && selection.type === 'device' ? deviceById.get(selection.id) : null;
    panel.show(selection, { cableIds: litCables, label: selected ? selected.device.label : 'device' });
    stage.requestRender();
  }

  function select(type, id) {
    // Choosing the current selection again clears it, so there is always a way out.
    selection = selection && selection.type === type && selection.id === id ? null : { type, id };
    apply();
  }

  function clearSelection() {
    selection = null;
    panel.hideTrace();
    apply();
  }

  panel.onPick(function (type, id, termination) {
    select(type, id);
    return selection ? panel.showTrace(termination) : panel.hideTrace();
  });
  panel.onSearch(apply);
  stage.onNames(apply);
  document.addEventListener('lens:filter', apply);
  document.addEventListener('lens:finder', apply);

  /* ----------------------------------------------------------------------
   * The pointer
   * ------------------------------------------------------------------- */

  const pickable = [
    ...deviceViews.map((v) => v.mesh),
    ...reservationViews.map((v) => v.mesh),
    ...cableViews.map((v) => v.pick),
  ];

  stage.setPicking({
    objects: () => pickable,
    choose(hits) {
      const first = hits[0];
      if (!first) return null;
      // A cable in front of a device is what the pointer means, even where the device's box is
      // nearer: cables run behind the devices and would otherwise only be picked from the back.
      const cableHit = hits.find((hit) => hit.object.userData.cable);
      if (cableHit && cableHit.distance - first.distance < 40) return cableHit.object.userData.cable;
      const data = first.object.userData;
      return data.device || data.reservation || data.cable || null;
    },
    describe(target) {
      if (target.device) return { title: target.device.label, lines: target.device.facts };
      if (target.cable) {
        const lines = target.cable.endLabel ? [`leaves the rack to ${target.cable.endLabel}`] : [];
        return { title: target.cable.label, lines };
      }
      return { title: target.band.label };
    },
    hover: apply,
    click(target, event) {
      // The middle button is for opening in a new tab, which only a double click does here.
      if (event.button !== 0) return;
      if (!target) return clearSelection();
      if (target.device) {
        select('device', String(target.device.id));
        return panel.hideTrace();
      }
      if (target.cable) {
        select('cable', String(target.cable.id));
        return selection ? panel.showTrace(target.cable.termination) : panel.hideTrace();
      }
      select('reservation', String(target.band.id));
      return panel.hideTrace();
    },
    // A device opens on a double click, so a single click keeps its more useful meaning of
    // "show me what this connects to".
    open(target, event) {
      if (target && target.device) follow(target.device.url, event);
    },
  });

  document.addEventListener('click', function (event) {
    if (element.contains(event.target) || event.target.closest('.lens-cable') || panel.ownsClick(event.target)) return;
    if (selection) clearSelection();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape' || (!selection && !panel.searchTerm())) return;
    // One key, both narrowings: a reader pressing Escape wants the whole rack back, not to press
    // it twice and wonder which half it undid the first time.
    selection = null;
    panel.clearSearch();
    panel.hideTrace();
    apply();
  });

  /* ----------------------------------------------------------------------
   * Faces, and the first frame
   * ------------------------------------------------------------------- */

  function markMode() {
    controlsBar.querySelectorAll('[data-lens-mode]').forEach(function (button) {
      const on = button.dataset.lensMode === mode;
      button.classList.toggle('active', on);
      button.setAttribute('aria-pressed', String(on));
    });
  }

  function setMode(next) {
    mode = next;
    if (window.lensState) window.lensState.set('mode', mode === 'colour' ? ['colour'] : []);
    deviceViews.forEach((view) => view.paint(mode));
    markMode();
    apply();
  }

  controlsBar.addEventListener('click', function (event) {
    const modeButton = event.target.closest('[data-lens-mode]');
    if (modeButton) setMode(modeButton.dataset.lensMode);
  });

  // A band is a colour, so picking one over the device images shows the colours it is read by.
  document.addEventListener('lens:filter', function (event) {
    if (event.detail.group === 'devices' && event.detail.bands.length && mode === 'images') setMode('colour');
  });

  // The rack with the cables rising out of its roof: what the camera frames.
  const top = cables.reduce((high, cable) => Math.max(high, ...cable.points.map((p) => p[1])), rack.height) + 60;
  stage.setBounds([-halfW, 0, -halfD], [halfW, top, halfD]);
  // A little below the horizon, to look up at the underside of a device, and no further: from
  // under the floor the rack is upside down and the shadow is gone.
  stage.controls.maxPolarAngle = Math.PI * 0.56;

  applyHighlightColour();
  // A band restored from the link was picked before this drawing could hear it.
  if (legendBands('devices').size && mode === 'images') setMode('colour');
  markMode();
  // Starting the stage applies the names setting, which draws the first state through `apply`.
  stage.start(VIEWS, 'angle');
}

if (element && panel && configNode) {
  const config = JSON.parse(configNode.textContent);
  openStage(element, config, 'rack', (stage) => build(stage, config));
}
