/*
 * The floor in 3D.
 *
 * Drawn from the scene the server built (`floor_scene.py`): the room's floor with its metre
 * grid, every rack a cabinet standing where the plan puts it, coloured by the floor's colouring
 * with its roof in the same colour so the room reads like the plan from above, and the cabling
 * between racks and off the floor as tubes over their tops.
 *
 * Two ways to show a rack: a solid cabinet coloured by the floor's colouring, or the open cabinet
 * with its real devices in it, the way the rack's own view draws them. The devices are fetched
 * the first time the reader asks for them, since a floor of fifty racks is a thousand devices.
 *
 * Everything else on the page is the plan's: the legend, the finders, the find box and the
 * table narrow the plan's racks with classes, and this reads the same picks to fade its own.
 * `floor.js` owns the switch between the two views, and is told here when 3D cannot be drawn.
 */

import { chassisMaterial, drawCabinet, drawDevice } from 'lens/cabinet3d';
import { CABINET_FINISH, PICK_LAYER, follow, isDark, openStage } from 'lens/stage3d';

const element = document.querySelector('[data-lens-3d]');
const configNode = document.getElementById('lens-floor3d-config');

// Opacity of a rack left out by a filter.
const FILTERED_OPACITY = 0.12;
// How far a door stands off its cabinet, in millimetres: far enough to stay in front of it at
// room scale.
const DOOR_OFFSET = 6;
// How far a run of cabling to the wall is rounded at its corners, in millimetres.
const CORNER_RADIUS = 120;
// Cabling is thin at room scale, so it is picked by a tube at least this thick.
const MIN_PICK_RADIUS = 60;

const VIEWS = {
  top: [0, 1, 0.02],
  angle: [0.45, 0.8, 1],
  // Low, from the wall the plan draws at its foot, so left and right stay where the plan has them.
  side: [0, 0.28, 1],
};

function build(stage, config) {
  const { THREE, scene } = stage;
  const { room, racks, runs, exits } = config.scene;
  const colours = config.colours;
  const highlight = new THREE.Color();

  /* ----------------------------------------------------------------------
   * The room
   * ------------------------------------------------------------------- */

  const slabMaterial = new THREE.MeshStandardMaterial({ roughness: 0.9, metalness: 0 });
  const slab = new THREE.Mesh(new THREE.BoxGeometry(room.width, 20, room.depth), slabMaterial);
  slab.position.set(room.width / 2, -10, room.depth / 2);
  slab.receiveShadow = true;
  scene.add(slab);

  // The grid, ruled in the step the plan's scale is labelled in, so a square is a square
  // somebody can pace out.
  const gridPoints = [];
  for (let x = room.step; x < room.width; x += room.step) gridPoints.push(x, 1, 0, x, 1, room.depth);
  for (let z = room.step; z < room.depth; z += room.step) gridPoints.push(0, 1, z, room.width, 1, z);
  const gridGeometry = new THREE.BufferGeometry();
  gridGeometry.setAttribute('position', new THREE.Float32BufferAttribute(gridPoints, 3));
  const gridMaterial = new THREE.LineBasicMaterial({ transparent: true });
  scene.add(new THREE.LineSegments(gridGeometry, gridMaterial));

  const edgeMaterial = new THREE.LineBasicMaterial({ transparent: true });
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(room.width, 20, room.depth)), edgeMaterial);
  edge.position.copy(slab.position);
  scene.add(edge);

  /* The scale along the two edges the plan labels, in metres. Painted flat on the floor rather
     than as page elements, so a cabinet standing in front of a number hides it the way it would
     hide a mark on a real floor, instead of the number printing across the cabinet. */
  const markSize = Math.min(room.step * 0.3, 400);
  const marks = [];
  for (let x = 0; x <= room.width + 1; x += room.step) marks.push([x, -markSize, Math.round(x / 1000)]);
  for (let z = room.step; z <= room.depth + 1; z += room.step) marks.push([-markSize, z, Math.round(z / 1000)]);

  function markTexture(text) {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const context = canvas.getContext('2d');
    context.fillStyle = isDark() ? 'rgba(229, 231, 235, .8)' : 'rgba(33, 37, 41, .75)';
    context.font = '600 72px system-ui, -apple-system, "Segoe UI", sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(String(text), 64, 64);
    return stage.finishTexture(new THREE.CanvasTexture(canvas));
  }

  const markMaterials = marks.map(function ([x, z, text]) {
    const material = new THREE.MeshBasicMaterial({ map: markTexture(text), transparent: true, depthWrite: false });
    const mark = new THREE.Mesh(new THREE.PlaneGeometry(markSize, markSize), material);
    mark.rotation.x = -Math.PI / 2;
    mark.position.set(x, 2, z);
    scene.add(mark);
    return { material, text };
  });

  function paintRoom() {
    markMaterials.forEach(function (mark) {
      if (mark.material.map) mark.material.map.dispose();
      mark.material.map = markTexture(mark.text);
    });
    slabMaterial.color.set(isDark() ? 0x1f242b : 0xe9ecf0);
    gridMaterial.color.set(isDark() ? 0xe5e7eb : 0x212529);
    gridMaterial.opacity = isDark() ? 0.1 : 0.12;
    edgeMaterial.color.set(isDark() ? 0xe5e7eb : 0x212529);
    edgeMaterial.opacity = 0.35;
    highlight.set(isDark() ? colours.highlightDark : colours.highlight);
    rackViews.forEach((view) => view.outline.material.color.copy(highlight));
  }

  /* ----------------------------------------------------------------------
   * Racks
   * ------------------------------------------------------------------- */

  function rackView(rack) {
    const group = new THREE.Group();
    group.position.set(rack.x, 0, rack.z);
    group.rotation.y = rack.rotation;
    scene.add(group);
    // The cabinet as a solid, for the Cabinets view.
    const solid = new THREE.Group();
    group.add(solid);
    // The open cabinet and its devices, for the Devices view. Turned half round, because the
    // rack's own geometry has its front towards +z and the plan puts a rack's front on -z.
    const detail = new THREE.Group();
    detail.rotation.y = Math.PI;
    detail.visible = false;
    group.add(detail);

    const { width: w, depth: d, height: h } = rack;
    const colour = new THREE.Color(rack.colour || '#8a8f98');

    // The cabinet, in the rack view's finish, with its roof in the colouring: from above, the
    // room reads like the plan.
    const body = new THREE.MeshStandardMaterial(CABINET_FINISH.frame);
    const roof = new THREE.MeshStandardMaterial({ color: colour, metalness: 0.1, roughness: 0.6 });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), [body, body, roof, body, body, body]);
    mesh.position.y = h / 2;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.layers.enable(PICK_LAYER);
    solid.add(mesh);

    // A door front and rear, the front on the -z face the plan draws its front bar on. A
    // colouring that measures a quantity fills each from the bottom to the reading, so the
    // reading is there whichever side of the rack you look at; any other colouring fills it whole.
    const doorHeight = h - 140;
    const doorWidth = w - 40;
    const empty = new THREE.MeshStandardMaterial(CABINET_FINISH.door);
    const filled = new THREE.MeshStandardMaterial({ color: colour, metalness: 0.1, roughness: 0.55 });
    const materials = [body, roof, empty, filled];
    const fraction = rack.fraction === null ? 1 : Math.max(0, Math.min(1, rack.fraction));
    const fillHeight = fraction * doorHeight;
    [
      [-d / 2 - DOOR_OFFSET, Math.PI],
      [d / 2 + DOOR_OFFSET, 0],
    ].forEach(function ([z, turn]) {
      [
        [filled, fillHeight, 100 + fillHeight / 2],
        [empty, doorHeight - fillHeight, 100 + fillHeight + (doorHeight - fillHeight) / 2],
      ].forEach(function ([material, height, y]) {
        if (height <= 0) return;
        const panel = new THREE.Mesh(new THREE.PlaneGeometry(doorWidth, height), material);
        panel.position.set(0, y, z);
        panel.rotation.y = turn;
        solid.add(panel);
      });
    });

    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(w + 8, h + 8, d + 8)),
      new THREE.LineBasicMaterial({ transparent: true, opacity: 0 })
    );
    outline.position.y = h / 2;
    group.add(outline);

    const name = stage.label(rack.gauge ? `${rack.name} · ${rack.gauge}` : rack.name, 'lens-3d__name');
    name.position.set(rack.x, h + 60, rack.z);
    name.center.set(0.5, 1);
    scene.add(name);

    // The colouring stays on the roof when the devices are shown, so the room still reads like
    // the plan from above.
    const cap = new THREE.Mesh(new THREE.PlaneGeometry(w - 52, d - 52), roof);
    cap.rotation.x = -Math.PI / 2;
    cap.position.y = h - 13;
    detail.add(cap);

    const view = { rack, mesh, materials, outline, name, solid, detail, devices: [], detailMaterials: [] };
    mesh.userData.rack = view;
    return view;
  }

  const rackViews = racks.map(rackView);

  /* ----------------------------------------------------------------------
   * Devices
   * ------------------------------------------------------------------- */

  const rackSwitch = element.querySelector('[data-lens-3d-controls]');
  let showDevices = Boolean(window.lensState && window.lensState.get('racks')[0] === 'devices');
  let devicesLoaded = null;
  const deviceMeshes = [];

  /* Fetch every rack's devices, once, and build them into each rack's open cabinet. */
  function loadDevices() {
    if (!devicesLoaded) {
      const byId = new Map(rackViews.map((view) => [view.rack.id, view]));
      devicesLoaded = fetch(config.devicesUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (response) {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return response.json();
        })
        .then(function (data) {
          data.racks.forEach(function (entry) {
            const view = byId.get(entry.id);
            if (!view) return;
            // One chassis for the rack's devices, faded with its cabinet, and the shadow left to
            // the cabinet: a room of a thousand devices each casting its own is too many draws.
            const body = chassisMaterial(stage);
            view.detailMaterials.push(...drawCabinet(stage, view.detail, entry.cabinet).materials, body);
            entry.devices.forEach(function (device) {
              const box = drawDevice(stage, view.detail, device, { body, castShadow: false });
              box.mesh.userData.device = { box, rack: view };
              view.devices.push(box);
              deviceMeshes.push(box.mesh);
            });
          });
        });
    }
    return devicesLoaded;
  }

  function markRacks() {
    rackSwitch.querySelectorAll('[data-lens-rack-display]').forEach(function (button) {
      const on = (button.dataset.lensRackDisplay === 'devices') === showDevices;
      button.classList.toggle('active', on);
      button.setAttribute('aria-pressed', String(on));
    });
  }

  function showRacks() {
    rackViews.forEach(function (view) {
      view.solid.visible = !showDevices;
      view.detail.visible = showDevices;
    });
    markRacks();
    apply();
  }

  function setDevices(on) {
    showDevices = on;
    if (window.lensState) window.lensState.set('racks', on ? ['devices'] : []);
    if (!on) return showRacks();
    const button = rackSwitch.querySelector('[data-lens-rack-display="devices"]');
    button.disabled = true;
    loadDevices()
      .then(showRacks)
      .catch(function (error) {
        console.warn('netbox-spatial-lens could not load the devices:', error);
        devicesLoaded = null;
        button.title = 'The devices could not be loaded. The browser console has the detail.';
        showDevices = false;
        showRacks();
      })
      .finally(() => (button.disabled = false));
  }

  rackSwitch.addEventListener('click', function (event) {
    const button = event.target.closest('[data-lens-rack-display]');
    if (button) setDevices(button.dataset.lensRackDisplay === 'devices');
  });

  /* ----------------------------------------------------------------------
   * Cabling
   * ------------------------------------------------------------------- */

  const pickMaterial = new THREE.MeshBasicMaterial();

  function tube(path, radius, colour) {
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(colour),
      emissive: new THREE.Color(colour),
      emissiveIntensity: 0,
      roughness: 0.5,
      metalness: 0.05,
    });
    const segments = Math.max(32, Math.round(path.getLength() / 60));
    // No shadow: seen from above, a room's worth of cabling casts a second copy of itself across
    // the floor, and the copy is the louder of the two.
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(path, segments, radius, 10, false), material);
    scene.add(mesh);
    const pick = new THREE.Mesh(new THREE.TubeGeometry(path, Math.ceil(segments / 3), Math.max(radius, MIN_PICK_RADIUS), 6, false), pickMaterial);
    pick.layers.set(PICK_LAYER);
    scene.add(pick);
    return { mesh, material, pick };
  }

  const runViews = runs.map(function (run) {
    const [a, c, b] = run.points.map((p) => new THREE.Vector3(...p));
    const { mesh, material, pick } = tube(new THREE.QuadraticBezierCurve3(a, c, b), run.radius, run.colour);
    const view = { run, material, meshes: [mesh], pickables: [pick], rackIds: run.rackIds };
    pick.userData.run = view;
    return view;
  });

  const exitViews = exits.map(function (exit) {
    const { mesh, material, pick } = tube(stage.roundedPath(exit.points, CORNER_RADIUS), exit.radius, exit.colour);
    const last = exit.points[exit.points.length - 1];
    const marker = new THREE.Mesh(new THREE.SphereGeometry(exit.marker, 24, 16), material);
    marker.position.set(...last);
    marker.layers.enable(PICK_LAYER);
    scene.add(marker);
    const name = stage.label(exit.label, 'lens-3d__end');
    name.position.set(last[0], last[1] + exit.marker + 40, last[2]);
    name.center.set(0.5, 1);
    scene.add(name);
    const view = { exit, material, name, meshes: [mesh, marker], pickables: [pick, marker], rackIds: [exit.rackId] };
    pick.userData.exit = view;
    marker.userData.exit = view;
    return view;
  });

  /* ----------------------------------------------------------------------
   * Filters and the pointer
   * ------------------------------------------------------------------- */

  function legendBands(group) {
    return new Set(window.lensLegendFilter ? window.lensLegendFilter.bands(group) : []);
  }

  function finderKeeps(group, ids) {
    if (!window.lensFinder) return true;
    const picked = window.lensFinder.picked(group);
    return !picked.size || ids.some((id) => picked.has(id));
  }

  /* Whether a rack survives every narrowing: the colouring's legend, each finder that carries
     ids for it, and the find box. The same three the plan applies with classes. */
  function rackInFocus(rack, bands) {
    if (bands.size && !bands.has(rack.band)) return false;
    const kept = Object.entries(rack.filters).every(([group, ids]) =>
      finderKeeps(group, String(ids).split(/\s+/).filter(Boolean))
    );
    return kept && (!window.lensFloor || window.lensFloor.matchesSearch(rack.name, rack.assetTag));
  }

  function apply() {
    const bands = legendBands('racks');
    const hovered = stage.hovered();
    const showNames = stage.showNames();
    const inFocus = new Set();

    // Hovering a device lights the rack it is in, as hovering the rack does.
    const hoveredRack = hovered && hovered.box ? hovered.rack : hovered;
    rackViews.forEach(function (view) {
      const kept = rackInFocus(view.rack, bands);
      if (kept) inFocus.add(view.rack.id);
      const opacity = kept ? 1 : FILTERED_OPACITY;
      view.materials.concat(view.detailMaterials).forEach((material) => stage.setOpacity(material, opacity));
      view.devices.forEach(function (box) {
        [box.faces.front, box.faces.rear].forEach((material) => stage.setOpacity(material, opacity));
      });
      view.mesh.castShadow = kept;
      const lit = hoveredRack === view;
      view.outline.material.opacity = lit ? 1 : 0;
      view.name.visible = kept && (showNames || lit);
    });

    // Cabling belongs to the racks it joins: hovering a rack lights it, and a rack left out by a
    // filter takes its cabling with it. Hidden rather than faded, because cabling to the same
    // place off the floor ends on the same corner of the room, and six faded tubes drawn on one
    // path stack back up to a solid one.
    const hoveredRackId = hoveredRack && hoveredRack.rack ? hoveredRack.rack.id : null;
    runViews.concat(exitViews).forEach(function (view) {
      const kept = view.rackIds.every((id) => inFocus.has(id));
      view.meshes.concat(view.pickables).forEach((mesh) => (mesh.visible = kept));
      const lit = hovered === view || view.rackIds.includes(hoveredRackId);
      view.material.emissiveIntensity = lit ? 0.45 : 0;
      if (view.name) view.name.visible = kept && lit;
    });

    stage.requestRender();
  }

  document.addEventListener('lens:filter', apply);
  document.addEventListener('lens:finder', apply);
  if (window.lensFloor) window.lensFloor.onSearch(apply);
  stage.onNames(apply);

  const pickable = [...rackViews.map((v) => v.mesh), ...runViews.concat(exitViews).flatMap((v) => v.pickables)];

  stage.setPicking({
    objects: () => (showDevices ? pickable.concat(deviceMeshes) : pickable),
    choose(hits) {
      const first = hits[0];
      if (!first) return null;
      const data = first.object.userData;
      return data.device || data.rack || data.exit || data.run || null;
    },
    describe(target) {
      if (target.box) {
        const device = target.box.device;
        return { title: device.label, lines: [`in ${target.rack.rack.name}`, ...device.facts] };
      }
      if (target.run) return { title: target.run.label };
      if (target.exit) return { title: target.exit.title };
      const rack = target.rack;
      const lines = [];
      if (rack.value) lines.push(rack.value);
      rack.facts.forEach(([label, value]) => lines.push(`${label}: ${value}`));
      if (rack.estimated) lines.push('Footprint estimated');
      return { title: rack.name, lines };
    },
    hover: apply,
    // A rack leads inside it, as it does on the plan; an exit leads to what it reaches.
    click(target, event) {
      if (target && target.box) follow(target.rack.rack.url, event);
      else if (target && target.rack) follow(target.rack.url, event);
      else if (target && target.exit) follow(target.exit.url, event);
    },
  });

  stage.onThemeChange(paintRoom);

  /* ----------------------------------------------------------------------
   * The first frame
   * ------------------------------------------------------------------- */

  let lowX = 0;
  let lowZ = 0;
  let highX = room.width;
  let highZ = room.depth;
  let top = racks.reduce((high, rack) => Math.max(high, rack.height), 0);
  runs.concat(exits).forEach(function (cabling) {
    cabling.points.forEach(function ([x, y, z]) {
      lowX = Math.min(lowX, x);
      highX = Math.max(highX, x);
      lowZ = Math.min(lowZ, z);
      highZ = Math.max(highZ, z);
      top = Math.max(top, y);
    });
  });
  stage.setBounds([lowX, 0, lowZ], [highX, top + 200, highZ], { sun: [0.25, 1.8, 0.35] });
  // Not below the floor: the room is a slab, and from under it nothing is where it should be.
  stage.controls.maxPolarAngle = Math.PI * 0.49;

  paintRoom();
  stage.start(VIEWS, 'angle', { names: true });
  if (showDevices) setDevices(true);
  else markRacks();
}

if (element && configNode) {
  const config = JSON.parse(configNode.textContent);
  openStage(element, config, 'floor', (stage) => build(stage, config)).then(function (drawn) {
    if (drawn || !window.lensFloor) return;
    const message = element.querySelector('[data-lens-3d-message]');
    window.lensFloor.unavailable(message.textContent);
  });
}
