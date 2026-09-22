/*
 * A cabinet and the devices in it, as meshes.
 *
 * Shared by the rack's own view and by the floor's Devices view, so a rack looks the same
 * standing in its room as it does when you look inside it. Both draw from the same server
 * geometry (`scene.py`): a cabinet in its own millimetres, centred on its footprint with its
 * front towards +z, and each device's box inside it.
 *
 * Only the meshes are here. What a drawing does with them, selection, filters and names, is the
 * drawing's own.
 */

import { CABINET_FINISH, PICK_LAYER, textOn } from 'lens/stage3d';

// The cabinet's frame, in millimetres.
const POST = 26;
const FOOT = 50;

/*
 * The frame of a cabinet: plinth, corner posts, roof frame, feet, glass side panels and the four
 * mounting rails. The roof is a frame and not a lid, so what leaves through it, and what is
 * inside, stays visible from above. Returns the solid materials, so a drawing can fade the
 * cabinet; the glass is already faint.
 *
 * The pieces of each material are merged into one mesh. A cabinet is some twenty boxes, and a
 * floor of eighty cabinets drawn one box at a time spent most of every frame on draw calls.
 */
export function drawCabinet(stage, parent, cabinet) {
  const { THREE } = stage;
  const frame = new THREE.MeshStandardMaterial(CABINET_FINISH.frame);
  const rail = new THREE.MeshStandardMaterial(CABINET_FINISH.rail);
  const glass = new THREE.MeshStandardMaterial({
    color: 0xa9bccf,
    metalness: 0.1,
    roughness: 0.1,
    transparent: true,
    opacity: 0.035,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const frameParts = [];
  const railParts = [];
  const glassParts = [];

  function block(parts, w, h, d, x, y, z) {
    parts.push(new THREE.BoxGeometry(w, h, d).translate(x, y, z));
  }

  function merged(parts, material, shadow) {
    const mesh = new THREE.Mesh(stage.mergeGeometries(parts), material);
    parts.forEach((part) => part.dispose());
    mesh.castShadow = shadow;
    mesh.receiveShadow = shadow;
    parent.add(mesh);
    return mesh;
  }

  const { width, depth, height, plinth, interior, faceplate, frontRailZ, rearRailZ } = cabinet;
  const halfW = width / 2;
  const halfD = depth / 2;

  block(frameParts, width, plinth - 20, depth, 0, (plinth - 20) / 2 + 20, 0);
  [-1, 1].forEach(function (sx) {
    [-1, 1].forEach(function (sz) {
      block(frameParts, POST, height - 20, POST, sx * (halfW - POST / 2), (height + 20) / 2, sz * (halfD - POST / 2));
      block(frameParts, FOOT, 20, FOOT, sx * (halfW - 45), 10, sz * (halfD - 45));
    });
    block(frameParts, POST, POST, depth, sx * (halfW - POST / 2), height - POST / 2, 0);
  });
  [-1, 1].forEach(function (sz) {
    block(frameParts, width, POST, POST, 0, height - POST / 2, sz * (halfD - POST / 2));
  });

  [-1, 1].forEach(function (sx) {
    glassParts.push(
      new THREE.PlaneGeometry(depth - POST * 2, height - plinth - POST)
        .rotateY(Math.PI / 2)
        .translate(sx * (halfW - 2), (height + plinth - POST) / 2, 0)
    );
  });

  const railX = faceplate / 2 - 11;
  [frontRailZ + 1.5, rearRailZ - 1.5].forEach(function (z) {
    [-1, 1].forEach(function (sx) {
      block(railParts, 18, interior, 3, sx * railX, plinth + interior / 2, z);
    });
  });

  merged(frameParts, frame, true);
  merged(railParts, rail, false);
  merged(glassParts, glass, false).renderOrder = 2;

  return { materials: [frame, rail] };
}

/* A face with no image: the colouring, and the device's name on it, drawn on a canvas at the
   proportions of the face so the letters are not stretched. */
function nameTexture(stage, text, colour, width, height) {
  const canvasWidth = 1024;
  const canvasHeight = Math.max(64, Math.round((canvasWidth * height) / width));
  const canvas = document.createElement('canvas');
  canvas.width = canvasWidth;
  canvas.height = canvasHeight;
  const context = canvas.getContext('2d');

  const gradient = context.createLinearGradient(0, 0, 0, canvasHeight);
  gradient.addColorStop(0, colour);
  gradient.addColorStop(1, stage.shade(colour, -0.18));
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvasWidth, canvasHeight);

  // The ears, darker, so a colour face still reads as something bolted to rails.
  const ear = Math.round((22 / width) * canvasWidth);
  context.fillStyle = 'rgba(0, 0, 0, .22)';
  context.fillRect(0, 0, ear, canvasHeight);
  context.fillRect(canvasWidth - ear, 0, ear, canvasHeight);

  const size = Math.min(44, canvasHeight * 0.5);
  context.font = `600 ${size}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  context.fillStyle = textOn(colour);
  context.textBaseline = 'middle';
  context.fillText(text, ear + 24, canvasHeight / 2, canvasWidth - 2 * ear - 48);

  return stage.finishTexture(new stage.THREE.CanvasTexture(canvas));
}

/* A device's box, shared by every device of the same size on a stage. Three groups rather than
   BoxGeometry's six: the four sides of the chassis are one material, and six groups made each
   device six draw calls, twelve with its shadow. */
const deviceBoxes = new WeakMap();

function deviceBox(stage, w, h, d) {
  if (!deviceBoxes.has(stage)) deviceBoxes.set(stage, new Map());
  const boxes = deviceBoxes.get(stage);
  const key = `${w} ${h} ${d}`;
  if (!boxes.has(key)) {
    // BoxGeometry's groups run +x, -x, +y, -y, +z, -z, six indices each.
    const geometry = new stage.THREE.BoxGeometry(w, h, d);
    geometry.clearGroups();
    geometry.addGroup(0, 24, 0);
    geometry.addGroup(24, 6, 1);
    geometry.addGroup(30, 6, 2);
    boxes.set(key, geometry);
  }
  return boxes.get(key);
}

/* The chassis material, for a drawing that shares one between many devices. */
export function chassisMaterial(stage) {
  return new stage.THREE.MeshStandardMaterial(CABINET_FINISH.chassis);
}

/*
 * One device: a box whose front and rear faces wear its device type images, and the colouring
 * with its name where an image is missing. The mesh is pickable.
 *
 * Returns { device, mesh, faces, body, normal, hasImage(), paint(mode) }. `paint('images')`
 * shows the images where they have loaded, `paint('colour')` the colouring on both faces. The
 * images load in the background, once per image across the whole stage, and repaint the device
 * when they arrive; `onPaint`, if given, is called after every repaint. A face waiting for its
 * image shows the plain colouring, and the name is only drawn for a face that has no image to
 * show, because a canvas per device is the largest thing on the stage and most are never seen.
 *
 * `body` shares one chassis material between devices, and `castShadow: false` leaves the shadow
 * to the cabinet: a drawing of a whole room uses both, a single rack neither.
 */
export function drawDevice(stage, parent, device, { onPaint = null, body = null, castShadow = true } = {}) {
  const { THREE } = stage;
  const [x, y, z, w, h, d] = device.box;
  const faces = {
    front: new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.15 }),
    rear: new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.15 }),
  };
  const chassis = body || chassisMaterial(stage);
  // A device mounted on the rear shows its own front at the back of the cabinet.
  const plusZ = device.facing === 'rear' ? faces.rear : faces.front;
  const minusZ = device.facing === 'rear' ? faces.front : faces.rear;
  const mesh = new THREE.Mesh(deviceBox(stage, w, h, d), [chassis, plusZ, minusZ]);
  mesh.position.set(x, y, z);
  mesh.castShadow = castShadow;
  mesh.receiveShadow = true;
  mesh.layers.enable(PICK_LAYER);
  parent.add(mesh);

  let colourFace = null;
  const images = {};
  const pending = { front: Boolean(device.images.front), rear: Boolean(device.images.rear) };
  let mode = 'images';

  function paint(next) {
    mode = next || mode;
    ['front', 'rear'].forEach(function (side) {
      const material = faces[side];
      if (mode === 'images' && images[side]) {
        material.map = images[side];
        material.color.set(0xffffff);
      } else if (mode === 'images' && pending[side]) {
        material.map = null;
        material.color.set(device.colour);
      } else {
        colourFace = colourFace || nameTexture(stage, device.label, device.colour, w, h);
        material.map = colourFace;
        material.color.set(0xffffff);
      }
      material.needsUpdate = true;
    });
    if (onPaint) onPaint();
  }

  paint();
  ['front', 'rear'].forEach(function (side) {
    const url = device.images[side];
    if (!url) return;
    stage.imageTexture(url).then(function (texture) {
      pending[side] = false;
      images[side] = texture;
      paint();
      stage.requestRender();
    });
  });

  return {
    device,
    mesh,
    faces,
    body: chassis,
    // The side of the box the device's own front is on.
    normal: new THREE.Vector3(0, 0, device.facing === 'rear' ? -1 : 1),
    hasImage: () => Boolean(images.front || images.rear),
    paint,
  };
}
