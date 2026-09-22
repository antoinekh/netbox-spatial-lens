/*
 * A 3D stage: what every Three.js drawing in the plugin has in common.
 *
 * The rack and the floor draw different things, and set them up the same way: Three.js loaded
 * through the page's import map, a renderer with the same light and the same shadow on the
 * ground, labels as page elements over the canvas, a hover card, a click that is not a drag, a
 * camera that frames what is drawn and moves between named views, and the buttons on the stage
 * for those views, the names and full screen. That is all here, once. A drawing builds its own
 * meshes on the stage it is handed and says what the pointer can pick.
 *
 * Three.js is never imported statically. A page whose `three_base` setting is empty, or whose
 * copy cannot be reached, still loads this module, and the stage then says why it is empty
 * rather than staying blank.
 *
 * It draws on demand: a frame is rendered when the camera moves, a texture arrives or a drawing
 * asks for one, and not otherwise, so a stage nobody is moving costs nothing.
 */

// How long a camera move takes, in milliseconds.
const CAMERA_MOVE = 650;
// A press that moves further than this, in pixels, is a drag of the camera and not a click.
const CLICK_TOLERANCE = 5;
// The layer the pointer is tested against. Only pickable meshes are on it, and the camera does
// not draw it, so a drawing can add fat invisible meshes to make thin things easy to hit.
export const PICK_LAYER = 1;

/* The finish of a cabinet, shared by every drawing of one so a rack looks the same in the room as
 * it does when you look inside it. A mid graphite, and only half metallic: the environment the
 * stage lights with is dim, and a fully metallic surface reflects that dimness back as black
 * whatever its colour. */
export const CABINET_FINISH = {
  frame: { color: 0x6b7480, metalness: 0.35, roughness: 0.5 },
  rail: { color: 0x8a939f, metalness: 0.45, roughness: 0.4 },
  // A device's chassis, a shade darker than the frame it is bolted into.
  chassis: { color: 0x59616c, metalness: 0.4, roughness: 0.45 },
  // The part of a door a reading has not filled.
  door: { color: 0x4b535e, metalness: 0.2, roughness: 0.5 },
};

/* Go to a URL the way a link would: in a new tab for a middle click or with Ctrl or Cmd held,
   since a drawing on a canvas has no link for the browser to do that itself. */
export function follow(url, event) {
  if (!url) return;
  if (event && (event.button === 1 || event.ctrlKey || event.metaKey)) window.open(url, '_blank', 'noopener');
  else window.location.href = url;
}

/* A failure the reader can act on, shown on the stage as it is worded. */
export class ReaderError extends Error {}

function hasWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch (error) {
    return false;
  }
}

export function isDark() {
  return document.documentElement.getAttribute('data-bs-theme') === 'dark';
}

export function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* Whether white or near-black text reads better on a colour, by its relative luminance. */
export function textOn(hex) {
  const value = parseInt(hex.replace('#', ''), 16);
  const channel = (shift) => {
    const c = ((value >> shift) & 255) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0);
  return luminance > 0.36 ? '#111827' : '#ffffff';
}

async function loadThree(config, noun) {
  if (!config.enabled) {
    throw new ReaderError(`The ${noun} drawing is turned off: the three_base setting is empty.`);
  }
  if (!hasWebGL()) {
    throw new ReaderError(
      `The ${noun} view needs WebGL, and this browser has none. Turn on hardware acceleration, or use another browser.`
    );
  }
  try {
    const [THREE, controls, labels, environment, geometryUtils] = await Promise.all([
      import('three'),
      import('three/addons/controls/OrbitControls.js'),
      import('three/addons/renderers/CSS2DRenderer.js'),
      import('three/addons/environments/RoomEnvironment.js'),
      import('three/addons/utils/BufferGeometryUtils.js'),
    ]);
    return { THREE, ...controls, ...labels, ...environment, mergeGeometries: geometryUtils.mergeGeometries };
  } catch (error) {
    console.warn('netbox-spatial-lens:', error);
    throw new ReaderError(
      `The ${noun} view could not load Three.js from ${config.threeBase}. Point the three_base setting at a copy this browser can reach.`
    );
  }
}

/*
 * Load Three.js, build a drawing on the stage, and uncover it.
 *
 * `build(stage)` draws on the stage it is given and ends by calling `stage.start(view)`.
 * Resolves to true when the drawing is up, and to false when it could not be drawn, with the
 * reason left on the stage.
 */
export async function openStage(element, config, noun, build) {
  const message = element.querySelector('[data-lens-3d-message]');
  try {
    const lib = await loadThree(config, noun);
    build(createStage(element, lib));
    message.hidden = true;
    return true;
  } catch (error) {
    message.textContent =
      error instanceof ReaderError
        ? error.message
        : `The ${noun} view could not be drawn. The browser console has the detail.`;
    message.classList.add('is-error');
    message.hidden = false;
    if (!(error instanceof ReaderError)) console.warn(`netbox-spatial-lens could not draw the ${noun}:`, error);
    return false;
  }
}

function createStage(element, lib) {
  const { THREE, OrbitControls, CSS2DRenderer, CSS2DObject, RoomEnvironment, mergeGeometries } = lib;

  const host = element.querySelector('[data-lens-3d-canvas]');
  const tip = element.querySelector('[data-lens-3d-tip]');
  const controlsBar = element.querySelector('[data-lens-3d-controls]');

  /* ----------------------------------------------------------------------
   * Renderer, light, camera
   * ------------------------------------------------------------------- */

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  // Neutral rather than filmic: device images are photographs of real faceplates, and a filmic
  // curve shifts their colours away from what is printed on the hardware.
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  host.appendChild(renderer.domElement);

  const labelRenderer = new CSS2DRenderer();
  labelRenderer.domElement.classList.add('lens-3d__labels');
  host.appendChild(labelRenderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;
  scene.add(new THREE.HemisphereLight(0xdfe8f5, 0x3a3f47, 0.7));

  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.0004;
  scene.add(key, key.target);

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({ opacity: 0.2 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  const camera = new THREE.PerspectiveCamera(32, 1, 10, 80000);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.screenSpacePanning = true;

  /* ----------------------------------------------------------------------
   * Drawing on demand
   * ------------------------------------------------------------------- */

  let frame = 0;
  let tween = null;
  const beforeLabels = [];

  function requestRender() {
    if (!frame) frame = requestAnimationFrame(render);
  }

  function render(now) {
    frame = 0;
    if (tween) stepTween(now);
    const moving = controls.update();
    renderer.render(scene, camera);
    beforeLabels.forEach((hook) => hook());
    labelRenderer.render(scene, camera);
    if (moving || tween) requestRender();
  }

  controls.addEventListener('change', requestRender);

  /* ----------------------------------------------------------------------
   * Materials, textures and labels
   * ------------------------------------------------------------------- */

  const anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const loader = new THREE.TextureLoader();
  const imageTextures = new Map();

  function finishTexture(texture) {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = anisotropy;
    return texture;
  }

  /* One texture per image URL, shared by everything that shows it. Resolves to null when the
     image cannot be loaded, so the caller can fall back to a colour. */
  function imageTexture(url) {
    if (!imageTextures.has(url)) {
      imageTextures.set(
        url,
        new Promise(function (resolve) {
          loader.load(
            url,
            (texture) => resolve(finishTexture(texture)),
            undefined,
            function () {
              console.warn(`netbox-spatial-lens: could not load ${url}`);
              resolve(null);
            }
          );
        })
      );
    }
    return imageTextures.get(url);
  }

  function shade(hex, amount) {
    const colour = new THREE.Color(hex);
    colour.offsetHSL(0, 0, amount);
    return `#${colour.getHexString()}`;
  }

  function setOpacity(material, opacity) {
    const transparent = opacity < 1;
    // Blending is part of the compiled material, so a change of `transparent` has to recompile
    // it; a change of the opacity alone does not.
    if (material.transparent !== transparent) material.needsUpdate = true;
    material.transparent = transparent;
    material.opacity = opacity;
    material.depthWrite = !transparent;
  }

  function label(text, className) {
    const node = document.createElement('div');
    node.className = className;
    node.textContent = text;
    return new CSS2DObject(node);
  }

  /* A polyline with its corners rounded. Each corner is cut back along both of its segments,
     never by more than half of either, and bridged with a quadratic curve. */
  function roundedPath(points, radius) {
    const vectors = points.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
    const path = new THREE.CurvePath();
    let from = vectors[0];
    for (let i = 1; i < vectors.length - 1; i += 1) {
      const corner = vectors[i];
      const before = vectors[i - 1];
      const after = vectors[i + 1];
      const cut = Math.min(radius, corner.distanceTo(before) / 2, corner.distanceTo(after) / 2);
      const entry = corner.clone().lerp(before, cut / Math.max(corner.distanceTo(before), 1e-6));
      const exit = corner.clone().lerp(after, cut / Math.max(corner.distanceTo(after), 1e-6));
      if (from.distanceTo(entry) > 0.01) path.add(new THREE.LineCurve3(from, entry));
      if (cut > 0.01) path.add(new THREE.QuadraticBezierCurve3(entry, corner, exit));
      from = exit;
    }
    path.add(new THREE.LineCurve3(from, vectors[vectors.length - 1]));
    return path;
  }

  const themeHandlers = [];
  new MutationObserver(function () {
    themeHandlers.forEach((handler) => handler());
    requestRender();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-bs-theme'] });

  /* ----------------------------------------------------------------------
   * What is drawn, and the camera framing it
   * ------------------------------------------------------------------- */

  const corners = [];
  const boundsCentre = new THREE.Vector3();
  let views = {};

  /* The box everything drawn fits in, in scene units. Places the light, the shadow and the
     ground around it, and is what every view frames. `sun` is the direction the light comes
     from: a tall cabinet reads best lit from the side, a room from nearly overhead, where its
     shadows stay inside it. */
  function setBounds(min, max, { sun = [0.9, 1.4, 1.1] } = {}) {
    corners.length = 0;
    [min[0], max[0]].forEach(function (x) {
      [min[1], max[1]].forEach(function (y) {
        [min[2], max[2]].forEach((z) => corners.push(new THREE.Vector3(x, y, z)));
      });
    });
    boundsCentre.set((min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2);
    const size = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2]);

    key.position.set(boundsCentre.x + size * sun[0], max[1] + size * sun[1], boundsCentre.z + size * sun[2]);
    key.target.position.set(boundsCentre.x, 0, boundsCentre.z);
    const reach = size * 1.2;
    Object.assign(key.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, near: 10, far: size * 6 });
    key.shadow.camera.updateProjectionMatrix();

    ground.scale.set(size * 12, size * 12, 1);
    ground.position.set(boundsCentre.x, 0, boundsCentre.z);

    controls.minDistance = size * 0.15;
    controls.maxDistance = size * 8;
    // The near plane scales with what is drawn. Fixed at a few millimetres, a room ten metres
    // across has too little depth precision left to tell a door from the cabinet behind it, and
    // the two flicker through each other in stripes.
    camera.near = size * 0.005;
    camera.far = size * 40;
    camera.updateProjectionMatrix();
    controls.target.copy(boundsCentre);
  }

  /* Where the camera stands to fit every corner when looking along `direction`.
   *
   * Fitted to the box rather than to a sphere round it: a sphere is the box's diagonal in every
   * direction, which left a front view of a tall narrow cabinet with most of the stage empty.
   * Each corner needs the camera far enough back that it falls inside both halves of the view,
   * counting how much nearer to the camera the corner already is. */
  function framing(direction) {
    const forward = direction.clone().normalize();
    const worldUp = Math.abs(forward.y) > 0.999 ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(0, 1, 0);
    const right = new THREE.Vector3().crossVectors(worldUp, forward).normalize();
    const up = new THREE.Vector3().crossVectors(forward, right);
    const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
    const tanH = tanV * camera.aspect;
    let distance = 0;
    corners.forEach(function (corner) {
      const offset = corner.clone().sub(boundsCentre);
      const towards = offset.dot(forward);
      distance = Math.max(distance, Math.abs(offset.dot(right)) / tanH + towards, Math.abs(offset.dot(up)) / tanV + towards);
    });
    return {
      position: boundsCentre.clone().add(forward.multiplyScalar(distance * 1.08)),
      target: boundsCentre.clone(),
    };
  }

  function easeInOut(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  }

  function stepTween(now) {
    const t = Math.min(1, (now - tween.start) / CAMERA_MOVE);
    const k = easeInOut(t);
    camera.position.lerpVectors(tween.fromPosition, tween.to.position, k);
    controls.target.lerpVectors(tween.fromTarget, tween.to.target, k);
    if (t >= 1) tween = null;
  }

  function markView(name) {
    controlsBar.querySelectorAll('[data-lens-view]').forEach(function (button) {
      button.classList.toggle('active', button.dataset.lensView === name);
    });
  }

  function lookFrom(name, { animate = true } = {}) {
    const to = framing(views[name]);
    markView(name);
    if (!animate || prefersReducedMotion()) {
      tween = null;
      camera.position.copy(to.position);
      controls.target.copy(to.target);
      controls.update();
      return requestRender();
    }
    tween = { start: performance.now(), fromPosition: camera.position.clone(), fromTarget: controls.target.clone(), to };
    requestRender();
  }

  // A drag of the camera leaves every preset: none of them describes the view any more.
  controls.addEventListener('start', function () {
    tween = null;
    markView(null);
  });

  /* ----------------------------------------------------------------------
   * The pointer
   * ------------------------------------------------------------------- */

  const raycaster = new THREE.Raycaster();
  raycaster.layers.set(PICK_LAYER);
  const pointer = new THREE.Vector2();
  let picking = null;
  let hovered = null;
  let pendingMove = null;
  let pressed = null;

  function shown(object) {
    for (let node = object; node; node = node.parent) if (!node.visible) return false;
    return true;
  }

  function hitAt(clientX, clientY) {
    const box = renderer.domElement.getBoundingClientRect();
    pointer.set(((clientX - box.left) / box.width) * 2 - 1, -((clientY - box.top) / box.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    // A raycaster tests hidden meshes too, and something hidden, or inside a hidden group, must
    // not take the pointer.
    const hits = raycaster.intersectObjects(picking.objects(), false).filter((hit) => shown(hit.object));
    return picking.choose(hits);
  }

  function showTip(target, clientX, clientY) {
    const card = target ? picking.describe(target) : null;
    if (!card) {
      tip.hidden = true;
      return;
    }
    tip.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = card.title;
    tip.appendChild(title);
    (card.lines || []).forEach(function (line) {
      const row = document.createElement('div');
      row.textContent = line;
      tip.appendChild(row);
    });
    tip.hidden = false;
    const box = element.getBoundingClientRect();
    tip.style.left = `${Math.min(clientX - box.left + 14, box.width - tip.offsetWidth - 8)}px`;
    tip.style.top = `${Math.min(clientY - box.top + 14, box.height - tip.offsetHeight - 8)}px`;
  }

  function setHovered(target) {
    if (target === hovered) return;
    hovered = target;
    picking.hover(target);
  }

  renderer.domElement.addEventListener('pointermove', function (event) {
    if (pressed || !picking) return;
    const first = !pendingMove;
    pendingMove = event;
    if (!first) return;
    requestAnimationFrame(function () {
      const { clientX, clientY } = pendingMove;
      pendingMove = null;
      const target = hitAt(clientX, clientY);
      renderer.domElement.style.cursor = target ? 'pointer' : 'grab';
      showTip(target, clientX, clientY);
      setHovered(target);
    });
  });

  renderer.domElement.addEventListener('pointerleave', function () {
    tip.hidden = true;
    if (picking) setHovered(null);
  });

  renderer.domElement.addEventListener('pointerdown', function (event) {
    pressed = { x: event.clientX, y: event.clientY, button: event.button };
    tip.hidden = true;
  });

  renderer.domElement.addEventListener('pointerup', function (event) {
    const press = pressed;
    pressed = null;
    // The main button, or the middle one, which is how a link is opened in a new tab.
    if (!press || (press.button !== 0 && press.button !== 1) || !picking) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) > CLICK_TOLERANCE) return;
    picking.click(hitAt(event.clientX, event.clientY), event);
  });

  renderer.domElement.addEventListener('dblclick', function (event) {
    if (picking && picking.open) picking.open(hitAt(event.clientX, event.clientY), event);
  });

  /* ----------------------------------------------------------------------
   * The buttons on the stage
   * ------------------------------------------------------------------- */

  let showNames = false;
  const namesHandlers = [];

  function markNames() {
    const names = controlsBar.querySelector('[data-lens-labels]');
    if (!names) return;
    names.classList.toggle('active', showNames);
    names.setAttribute('aria-pressed', String(showNames));
  }

  controlsBar.addEventListener('click', function (event) {
    const view = event.target.closest('[data-lens-view]');
    if (view) return lookFrom(view.dataset.lensView);

    if (event.target.closest('[data-lens-labels]')) {
      showNames = !showNames;
      if (window.lensState) window.lensState.set('names', [showNames ? 'on' : 'off']);
      markNames();
      return namesHandlers.forEach((handler) => handler(showNames));
    }

    if (event.target.closest('[data-lens-fullscreen]')) {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (element.requestFullscreen) element.requestFullscreen();
    }
  });

  document.addEventListener('fullscreenchange', function () {
    const icon = controlsBar.querySelector('[data-lens-fullscreen] .mdi');
    if (!icon) return;
    icon.classList.toggle('mdi-fullscreen', !document.fullscreenElement);
    icon.classList.toggle('mdi-fullscreen-exit', Boolean(document.fullscreenElement));
  });

  /* ----------------------------------------------------------------------
   * Size, and the first frame
   * ------------------------------------------------------------------- */

  let firstView = null;

  function resize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    // A stage that is hidden, such as the floor's while the 2D plan is on show, has no size;
    // it is framed the first time it has one.
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    labelRenderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (firstView) {
      lookFrom(firstView, { animate: false });
      firstView = null;
    }
    requestRender();
  }

  return {
    THREE,
    mergeGeometries,
    scene,
    camera,
    controls,
    requestRender,
    finishTexture,
    imageTexture,
    shade,
    setOpacity,
    label,
    roundedPath,
    setBounds,
    lookFrom,
    // Called after each frame is drawn and before its labels are, to decide which to show.
    beforeLabels: (hook) => beforeLabels.push(hook),
    onThemeChange: (handler) => themeHandlers.push(handler),
    showNames: () => showNames,
    onNames: (handler) => namesHandlers.push(handler),
    hovered: () => hovered,

    /* What the pointer can reach.
     *
     * `objects()` lists the meshes to test, `choose(hits)` turns the sorted hits into a target
     * or null, `describe(target)` gives the hover card as { title, lines }, `hover(target)` and
     * `click(target, event)` react, and `open(target, event)`, if given, answers a double click. */
    setPicking(options) {
      picking = options;
    },

    /* Uncover the stage, framed on `view`: `views` names each preset's direction. Names are
       shown from the start when `names` is true, unless the URL says otherwise. */
    start(viewDirections, view, { names = false } = {}) {
      views = Object.fromEntries(Object.entries(viewDirections).map(([name, v]) => [name, new THREE.Vector3(...v)]));
      firstView = view;
      const kept = window.lensState ? window.lensState.get('names')[0] : undefined;
      showNames = kept ? kept === 'on' : names;
      markNames();
      namesHandlers.forEach((handler) => handler(showNames));
      controlsBar.hidden = false;
      new ResizeObserver(resize).observe(host);
      resize();
    },
  };
}
