"""
A floor, as a 3D scene.

The same room the plan draws, in millimetres and standing up: every rack a cabinet at its real
footprint, position, rotation and height, coloured by the floor's colouring, and the cabling
between racks and off the floor as tubes over their tops. The browser only draws what this
decides, so the geometry tests without a browser, the way the rack's does.

Built from what the floor page has already worked out (`build_layout`, `build_floor_runs`,
`build_floor_exits`), which applied the reader's permissions and the colouring. A second walk
of the same rows would be a second answer that could disagree with the plan beside it.

The axes follow the renderer and the plan together: the plan's x is x, the plan's y (down the
page) is z, and y is up. The origin is the room's corner the plan puts at its top left.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from dcim.models import Device
from django.urls import reverse

from netbox_spatial_lens.elevation import mount_device
from netbox_spatial_lens.floor_cabling import RUN_COLOUR
from netbox_spatial_lens.geometry import floor_viewport
from netbox_spatial_lens.models import RackPlacement
from netbox_spatial_lens.scene import CabinetFrame, cabinet_height, scene_device
from netbox_spatial_lens.tags import tag_slugs

__all__ = (
    'FloorScene',
    'SceneExit',
    'SceneRack',
    'SceneRun',
    'build_floor_devices',
    'build_floor_scene',
)

MM_PER_CM = 10.0
# How far above the tallest cabinet a run between two racks rises, as a share of the distance
# between them, and within what limits. A long run arcs higher, so neighbouring arcs of
# different lengths nest instead of crossing at one height.
RUN_RISE_SHARE = 0.25
RUN_RISE_MIN_MM = 250.0
RUN_RISE_MAX_MM = 1500.0
# The cable tray the cabling leaving the floor runs in, above the tallest cabinet on the floor.
TRAY_ABOVE_MM = 350.0
# How thick a tube is drawn for each centimetre of the plan's line width, which already grows
# with the number of cables it stands for.
TUBE_MM_PER_PLAN_CM = 3.0
# How large an exit's marker is for each centimetre of the plan's dot.
MARKER_MM_PER_PLAN_CM = 5.0


def _mm(value) -> float:
    # A tenth of a millimetre is finer than anything drawn, and keeps the page's JSON short.
    return round(float(value) * MM_PER_CM, 1)


def _point(x: float, y: float, z: float) -> list[float]:
    return [round(x, 1), round(y, 1), round(z, 1)]


@dataclass
class SceneRack:
    """
    One placed rack, as a cabinet standing in the room.
    """

    placed: object
    height: float
    # Room-plan fields a finder narrows by -> the space-separated ids this rack carries.
    filters: dict[str, str] = field(default_factory=dict)

    @property
    def x(self) -> float:
        return _mm(self.placed.x)

    @property
    def z(self) -> float:
        return _mm(self.placed.y)

    @property
    def rotation(self) -> float:
        """
        The turn about the vertical axis, in radians.

        The plan rotates clockwise on a page whose y runs down, and the renderer turns
        counter-clockwise looking down its y axis, so the same rotation is the opposite sign.
        """
        return -math.radians(float(self.placed.rotation))

    @property
    def front(self) -> tuple[float, float]:
        """
        Which way the rack's front faces, as an (x, z) unit vector.

        The plan draws the front on the rack's -y edge; here that edge is -z, turned by the
        rack's rotation.
        """
        angle = self.rotation
        return (-math.sin(angle), -math.cos(angle))

    @property
    def top(self) -> list[float]:
        return _point(self.x, self.height, self.z)

    def as_json(self) -> dict:
        placed = self.placed
        rack = placed.rack
        return {
            'id': rack.pk,
            'name': rack.name,
            'assetTag': rack.asset_tag or '',
            'url': reverse('dcim:rack_lens', args=[rack.pk]),
            'x': self.x,
            'z': self.z,
            'rotation': round(self.rotation, 5),
            'width': _mm(placed.width),
            'depth': _mm(placed.depth),
            'height': round(self.height, 1),
            'colour': placed.colour,
            'band': placed.band,
            'hasData': placed.has_data,
            'value': placed.label,
            'fraction': placed.fraction,
            'gauge': placed.gauge_label,
            'estimated': placed.estimated,
            'facts': [[str(label), str(value)] for label, value in placed.facts],
            'filters': self.filters,
        }


@dataclass
class SceneRun:
    """
    The cabling between two racks on the floor, as an arc from the top of one to the top of the
    other: its two ends and the control point of the quadratic curve between them.
    """

    run: object
    points: list[list[float]]
    radius: float

    def as_json(self) -> dict:
        return {
            'label': self.run.label,
            'colour': RUN_COLOUR,
            'rackIds': [self.run.a.rack.pk, self.run.b.rack.pk],
            'points': self.points,
            'radius': round(self.radius, 1),
        }


@dataclass
class SceneExit:
    """
    The cabling leaving one rack for somewhere off the floor, up to the tray and along it to the
    wall the plan draws it to.
    """

    exit: object
    points: list[list[float]]
    radius: float
    marker: float

    def as_json(self) -> dict:
        exit_ = self.exit
        return {
            'label': exit_.label,
            'title': exit_.title,
            'url': exit_.url,
            'kind': exit_.kind,
            'colour': exit_.colour,
            'rackId': exit_.rack.rack.pk,
            'points': self.points,
            'radius': round(self.radius, 1),
            'marker': round(self.marker, 1),
        }


@dataclass
class FloorScene:
    """
    Everything the 3D drawing of one floor needs.
    """

    floor: object
    width: float
    depth: float
    # The grid, in millimetres: the same step the plan's scale is ruled in.
    step: float
    racks: list[SceneRack] = field(default_factory=list)
    runs: list[SceneRun] = field(default_factory=list)
    exits: list[SceneExit] = field(default_factory=list)

    def as_json(self) -> dict:
        return {
            'room': {'width': self.width, 'depth': self.depth, 'step': self.step},
            'racks': [r.as_json() for r in self.racks],
            'runs': [r.as_json() for r in self.runs],
            'exits': [e.as_json() for e in self.exits],
        }


def _scene_rack(placed) -> SceneRack:
    filters = {'rack-tags': ' '.join(tag.slug for tag in placed.rack.tags.all())}
    filters.update({cell.filter.group: cell.keys for cell in placed.field_cells})
    return SceneRack(placed=placed, height=cabinet_height(placed.rack.u_height), filters=filters)


def _run(run, racks: dict[int, SceneRack]) -> SceneRun:
    a, b = racks[run.a.rack.pk], racks[run.b.rack.pk]
    start, end = a.top, b.top
    distance = math.dist((start[0], start[2]), (end[0], end[2]))
    apex = max(start[1], end[1]) + min(RUN_RISE_MAX_MM, max(RUN_RISE_MIN_MM, distance * RUN_RISE_SHARE))
    # A quadratic curve passes through the midpoint of its ends and its control point halfway,
    # so the control point is set twice as far above the ends as the apex should be.
    control_y = 2 * apex - (start[1] + end[1]) / 2
    control = _point((start[0] + end[0]) / 2, control_y, (start[2] + end[2]) / 2)
    return SceneRun(run=run, points=[start, control, end], radius=run.width * TUBE_MM_PER_PLAN_CM)


def _exit(exit_, racks: dict[int, SceneRack], tray_y: float) -> SceneExit:
    rack = racks[exit_.rack.rack.pk]
    start = rack.top
    wall_x, wall_z = _mm(exit_.x), _mm(exit_.y)
    points = [start, _point(start[0], tray_y, start[2]), _point(wall_x, tray_y, wall_z)]
    return SceneExit(
        exit=exit_,
        points=points,
        radius=exit_.width * TUBE_MM_PER_PLAN_CM,
        marker=exit_.radius * MARKER_MM_PER_PLAN_CM,
    )


def build_floor_scene(floor, placed, runs=(), exits=()) -> FloorScene:
    """
    Stand a floor up in 3D, from the layout the reader is allowed to see.
    """
    racks = [_scene_rack(p) for p in placed]
    by_id = {r.placed.rack.pk: r for r in racks}
    tallest = max((r.height for r in racks), default=0.0)
    tray_y = tallest + TRAY_ABOVE_MM

    return FloorScene(
        floor=floor,
        width=_mm(floor.width_cm),
        depth=_mm(floor.depth_cm),
        step=_mm(floor_viewport(floor).step),
        racks=racks,
        runs=[_run(run, by_id) for run in runs if run.a.rack.pk in by_id and run.b.rack.pk in by_id],
        exits=[_exit(exit_, by_id, tray_y) for exit_ in exits if exit_.rack.rack.pk in by_id],
    )


def build_floor_devices(floor, racks, devices) -> dict:
    """
    The devices in every rack placed on a floor, for the floor's Devices view.

    Each rack comes with its cabinet and its devices laid out exactly as the rack's own view lays
    them out, in the cabinet's millimetres with its front towards +z, so the drawing places the
    whole cabinet on the floor with one turn and one move. Loaded only when the reader asks for
    the devices: a floor of fifty racks is a thousand devices, and the page does not need them
    to draw the cabinets.

    `racks` and `devices` are the querysets the reader may see. The cost is the same whatever the
    size of the floor: one query for the placements, one for the devices with their types and
    roles, and one for their tags. Ports are not loaded, so the hover card does not count them.
    """
    placements = RackPlacement.objects.filter(floor=floor, rack__in=racks).select_related('rack')
    by_rack = {placement.rack_id: placement.rack for placement in placements}

    mounted = defaultdict(list)
    queryset = (
        devices.filter(rack_id__in=by_rack, position__isnull=False)
        .select_related('device_type', 'role')
        .order_by('position')
    )
    for device in queryset:
        mounted[device.rack_id].append(mount_device(by_rack[device.rack_id], device))
    tags = tag_slugs(Device, [m.device.pk for rack_devices in mounted.values() for m in rack_devices])

    entries = []
    for rack_id, rack in by_rack.items():
        frame = CabinetFrame(rack)
        entries.append(
            {
                'id': rack_id,
                'cabinet': frame.as_json(),
                'devices': [
                    scene_device(frame, m, ports=False, tags=tags.get(m.device.pk, ())).as_json()
                    for m in mounted[rack_id]
                ],
            }
        )
    return {'racks': entries}
