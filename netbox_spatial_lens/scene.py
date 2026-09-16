"""
The inside of a rack, as a 3D scene.

The rack `elevation` describes in rack units, in millimetres: where each device box sits in the
cabinet, which images go on its faces, and the path every cable takes through the cable
managers. The browser only draws what this decides, so the routing tests without a browser.

Built from a `RackElevation` rather than from the database. The elevation has already applied
the reader's permissions, resolved the cables in bulk, placed the devices in rack units and
coloured them, and a second walk of the same rows would be a second answer that could disagree
with the first.

The axes follow the renderer: x to the right when facing the front of the rack, y up, and z
towards the reader standing at the front. The origin is the centre of the cabinet's footprint
on the floor.
"""

from dataclasses import dataclass, field

from netbox_spatial_lens.elevation import RackElevation, unit_offset
from netbox_spatial_lens.geometry import MM_PER_INCH, natural_key, rack_footprint_cm

__all__ = (
    'Box',
    'CabinetFrame',
    'RackScene',
    'SceneBand',
    'SceneCable',
    'SceneDevice',
    'build_scene',
    'cabinet_height',
    'device_box',
    'scene_device',
)

# One rack unit, by the EIA-310 standard.
UNIT_MM = 44.45
# The cabinet below the lowest unit and above the highest one.
PLINTH_MM = 100.0
ROOF_MM = 60.0
# How far each mounting rail sits inside the cabinet, front and rear. The space behind the rear
# rail is where the cables are laced.
RAIL_SETBACK_MM = 100.0
# The gap between two stacked devices, so a stack of 1U boxes reads as boxes and not as a wall.
DEVICE_GAP_MM = 1.0
# How far in from each end of the faceplate a cable can leave, clear of the rack ears.
EAR_MM = 22.0
# A cable manager needs room for at least a few lanes, whatever the cabinet claims its width is.
MIN_MANAGER_MM = 40.0
# The side panel, which the managers must not run through.
PANEL_MM = 12.0
# Between one lane and the next, in both directions. Close enough to read as one bundle, far
# enough apart that a tube of its own can be picked.
LANE_PITCH_MM = 9.0
# The lanes start this far behind the rear rail, and end this far short of the cabinet's back.
LACING_NEAR_MM = 16.0
LACING_FAR_MM = 20.0
# How far a cable leaving the rack rises above the roof before it ends in its marker. Every
# marker ends at the same height, in its own lane; the browser stacks the names of the ones on
# show, since a switch's seventeen uplinks at seventeen heights are a staircase over the rack.
EXIT_RISE_MM = 140.0

# The cable manager each kind of cable runs in. Power on one side and data on the other is how
# a cabinet is dressed, so a power lead never shares a lane with an uplink.
LEFT, RIGHT = 'left', 'right'
MANAGER_OF_KIND = {'power': LEFT}


@dataclass
class Box:
    """
    An axis-aligned box: its centre and its size, in millimetres.
    """

    x: float
    y: float
    z: float
    w: float
    h: float
    d: float

    @property
    def rear_z(self) -> float:
        """The face of the box that looks towards the back of the rack."""
        return self.z - self.d / 2

    def as_json(self) -> list[float]:
        return [_mm(v) for v in (self.x, self.y, self.z, self.w, self.h, self.d)]


@dataclass
class SceneDevice:
    """
    One device in the cabinet, once, whichever faces it shows on.
    """

    device: object
    box: Box
    # The side of the cabinet the device's own front looks out of. A device mounted on the rear
    # shows its front image at the back of the rack.
    facing: str
    front_image: str
    rear_image: str
    colour: str
    band: str
    label: str
    facts: list[str]
    # Finder group -> the space-separated ids the device carries for it, the same ids the
    # finders' rows are picked by.
    filters: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict:
        device = self.device
        return {
            'id': device.pk,
            'label': self.label,
            'url': device.get_absolute_url(),
            'assetTag': device.asset_tag or '',
            'box': self.box.as_json(),
            'facing': self.facing,
            'images': {'front': self.front_image, 'rear': self.rear_image},
            'colour': self.colour,
            'band': self.band,
            'facts': self.facts,
            'filters': self.filters,
        }


@dataclass
class SceneCable:
    """
    One cable, as the path it takes through the cabinet.
    """

    run: object
    manager: str
    points: list[tuple[float, float, float]]
    # Where a cable leaving the rack is named. None for a cable that stays in it.
    end_label: str | None = None

    def as_json(self) -> dict:
        run = self.run
        return {
            'id': run.cable.pk,
            'kind': run.kind,
            'colour': run.colour,
            'deviceId': run.local_device.pk,
            'peerDeviceId': run.peer_device.pk if run.internal and run.peer_device else None,
            'termination': f'{run.termination_type}/{run.termination_id}',
            'internal': self.end_label is None,
            'label': f'{run.local_name} → {run.peer_name}',
            'endLabel': self.end_label,
            'points': [[_mm(v) for v in point] for point in self.points],
        }


@dataclass
class SceneBand:
    """
    A run of units that holds no device: reserved or free.
    """

    box: Box
    label: str
    reservation: object = None

    def as_json(self) -> dict:
        return {
            'id': self.reservation.pk if self.reservation else None,
            'label': self.label,
            'box': self.box.as_json(),
        }


@dataclass
class RackScene:
    """
    Everything the 3D drawing of one rack needs.
    """

    rack: object
    frame: 'CabinetFrame'
    units: list[tuple[int, float]]
    devices: list[SceneDevice] = field(default_factory=list)
    cables: list[SceneCable] = field(default_factory=list)
    reservations: list[SceneBand] = field(default_factory=list)
    free: list[SceneBand] = field(default_factory=list)

    @property
    def depth(self) -> float:
        return self.frame.depth

    @property
    def height(self) -> float:
        return self.frame.height

    @property
    def front_rail_z(self) -> float:
        return self.frame.front_rail_z

    @property
    def rear_rail_z(self) -> float:
        return self.frame.rear_rail_z

    @property
    def managers(self) -> dict[str, tuple[float, float]]:
        return self.frame.managers

    def as_json(self) -> dict:
        return {
            'rack': {
                'name': self.rack.name,
                **self.frame.as_json(),
                'unitHeight': UNIT_MM,
                'managers': {side: [_mm(x), _mm(w)] for side, (x, w) in self.managers.items()},
                'units': [[unit, _mm(y)] for unit, y in self.units],
            },
            'devices': [d.as_json() for d in self.devices],
            'cables': [c.as_json() for c in self.cables],
            'reservations': [r.as_json() for r in self.reservations],
            'free': [f.as_json() for f in self.free],
        }


def cabinet_height(units: float) -> float:
    """
    How tall a cabinet of `units` rack units stands, plinth and roof included, in millimetres.

    Shared with the floor, so a rack is as tall in the room as it is when you look inside it.
    """
    return PLINTH_MM + units * UNIT_MM + ROOF_MM


def _mm(value: float) -> float:
    # A tenth of a millimetre is finer than anything drawn, and keeps the page's JSON short.
    return round(value, 1)


class CabinetFrame:
    """
    A cabinet's measurements, and the conversion from rack units into them.

    Public so every drawing of a rack builds the same cabinet: the rack's own view, and the
    floor when it shows the devices in each rack.
    """

    def __init__(self, rack) -> None:
        width_cm, depth_cm, _ = rack_footprint_cm(rack)
        # The rails decide the faceplate: a 19-inch rack takes 482.6 mm devices.
        self.faceplate = float(rack.width or 19) * MM_PER_INCH
        # A cabinet recorded narrower than its own faceplate plus two managers is a data error,
        # and drawing it as recorded would put the cables through the devices.
        self.width = max(width_cm * 10, self.faceplate + 2 * (MIN_MANAGER_MM + PANEL_MM))
        self.depth = max(depth_cm * 10, 2 * RAIL_SETBACK_MM + UNIT_MM)
        self.interior = rack.u_height * UNIT_MM
        self.height = cabinet_height(rack.u_height)

        self.front_rail_z = self.depth / 2 - RAIL_SETBACK_MM
        available = self.depth - 2 * RAIL_SETBACK_MM
        mounting = float(rack.mounting_depth) if rack.mounting_depth else available
        self.mounting_depth = min(mounting, available)
        self.rear_rail_z = self.front_rail_z - self.mounting_depth

        inner = self.faceplate / 2
        outer = self.width / 2 - PANEL_MM
        manager_width = outer - inner
        centre = inner + manager_width / 2
        self.managers = {LEFT: (-centre, manager_width), RIGHT: (centre, manager_width)}

    def y_bottom(self, offset: float) -> float:
        """
        The bottom of something the elevation placed, in millimetres above the floor.

        The elevation gives rack units above the bottom of the cabinet, with `desc_units` and
        `starting_unit` already applied, so this is a change of unit and nothing more.
        """
        return PLINTH_MM + offset * UNIT_MM

    def lane(self, manager: str, index: int) -> tuple[float, float]:
        """
        The x and z of one lane in a manager.

        Lanes fill the manager's cross-section column by column. A manager with more cables
        than lanes starts again from the first, which overlaps two tubes rather than routing a
        cable outside the cabinet.
        """
        centre, width = self.managers[manager]
        columns = max(1, int(width // LANE_PITCH_MM))
        rows = max(1, int((RAIL_SETBACK_MM - LACING_NEAR_MM - LACING_FAR_MM) // LANE_PITCH_MM))
        index %= columns * rows
        column, row = index % columns, index // columns
        # Inner columns first on both sides, so a short run hugs the devices.
        offset = (column + 0.5) * width / columns - width / 2
        x = centre - offset if manager == LEFT else centre + offset
        z = self.rear_rail_z - LACING_NEAR_MM - row * LANE_PITCH_MM
        return x, z

    def as_json(self) -> dict:
        """What a drawing needs to build the cabinet around the devices."""
        return {
            'width': _mm(self.width),
            'depth': _mm(self.depth),
            'height': _mm(self.height),
            'plinth': PLINTH_MM,
            'interior': _mm(self.interior),
            'faceplate': _mm(self.faceplate),
            'frontRailZ': _mm(self.front_rail_z),
            'rearRailZ': _mm(self.rear_rail_z),
        }


def device_box(frame: CabinetFrame, mounted) -> Box:
    """
    Where a mounted device sits in its cabinet, in the cabinet's own millimetres: centred on its
    footprint, with the front of the cabinet towards +z.
    """
    device = mounted.device
    depth = frame.mounting_depth if device.device_type.is_full_depth else frame.mounting_depth / 2
    if mounted.face == 'rear':
        z = frame.rear_rail_z + depth / 2
    else:
        z = frame.front_rail_z - depth / 2
    height = mounted.units * UNIT_MM
    return Box(
        x=0.0,
        y=frame.y_bottom(mounted.offset) + height / 2,
        z=z,
        w=frame.faceplate,
        h=height - DEVICE_GAP_MM,
        d=depth,
    )


def _image_url(image) -> str:
    return image.url if image else ''


def _facts(mounted, ports: bool) -> list[str]:
    """
    The lines of a device's hover card, below its name. The port count only where the ports
    were loaded, which the rack's own view does and a whole floor of devices does not.
    """
    device = mounted.device
    # A float, because NetBox stores the position as a Decimal and `:g` keeps its `.0`.
    facts = [str(device.device_type), f'U{float(device.position):g} · mounted {mounted.face}']
    if device.asset_tag:
        facts.insert(0, f'Asset tag {device.asset_tag}')
    # What the colouring says about the device, first: a band's colour alone cannot say "3 of 48
    # cabled" or the day its support ends, and the floor's hover card names its reading too.
    if mounted.value is not None and mounted.value.has_data:
        facts.insert(0, mounted.value.label)
    if ports:
        facts.append(f'{mounted.connected_count} of {mounted.port_count} ports connected')
    return facts


def scene_device(frame: CabinetFrame, mounted, ports: bool = True) -> SceneDevice:
    """
    One mounted device, ready to draw. `ports` says whether its ports were loaded, so its hover
    card can count them.
    """
    device = mounted.device
    filters = {'device-tags': ' '.join(tag.slug for tag in device.tags.all())}
    filters.update({cell.filter.group: cell.keys for cell in mounted.field_cells})
    return SceneDevice(
        device=device,
        box=device_box(frame, mounted),
        facing=mounted.face,
        front_image=_image_url(device.device_type.front_image),
        rear_image=_image_url(device.device_type.rear_image),
        colour=mounted.colour,
        band=mounted.band,
        label=mounted.label,
        facts=_facts(mounted, ports),
        filters=filters,
    )


def _exit_points(runs, boxes: dict[int, Box]) -> dict[tuple[int, int], tuple[float, float, float]]:
    """
    Where each cable leaves each device it is plugged into, keyed by (cable id, device id).

    NetBox does not record where a port sits on a faceplate, so the ends are spread evenly
    across the device, in port order. Power ports go to the left, where the power manager is,
    so the leads do not cross the data cables on their way out.
    """
    ends: dict[int, list[tuple[bool, list, int]]] = {}
    for run in runs:
        is_data = MANAGER_OF_KIND.get(run.kind, RIGHT) == RIGHT
        ends.setdefault(run.local_device.pk, []).append((is_data, natural_key(run.local_name), run.cable.pk))
        if _is_internal(run, boxes):
            ends.setdefault(run.peer_device.pk, []).append((is_data, natural_key(run.peer_port_name), run.cable.pk))

    points = {}
    for device_id, device_ends in ends.items():
        box = boxes[device_id]
        usable = box.w - 2 * EAR_MM
        device_ends.sort()
        for index, (_, _, cable_id) in enumerate(device_ends):
            x = box.x - usable / 2 + (index + 0.5) * usable / len(device_ends)
            points[(cable_id, device_id)] = (x, box.y, box.rear_z)
    return points


def _is_internal(run, boxes: dict[int, Box]) -> bool:
    return run.internal and run.peer_device is not None and run.peer_device.pk in boxes


def _end_label(run) -> str:
    """
    What a cable leaving the rack is named at its marker: where it goes, as briefly as that is
    true. The far rack when there is one, since that is where you would walk to.
    """
    if run.peer_rack:
        return f'{run.peer_rack} · {run.peer_name}'
    return run.peer_name


def _route(frame: CabinetFrame, runs, boxes: dict[int, Box]) -> list[SceneCable]:
    exits = _exit_points(runs, boxes)
    # Lanes are handed out in the order the cables leave the rack from the top down, so
    # neighbouring devices get neighbouring lanes and their vertical runs stay side by side.
    ordered = sorted(runs, key=lambda r: (-boxes[r.local_device.pk].y, natural_key(r.local_name)))
    next_lane = {LEFT: 0, RIGHT: 0}
    exit_y = frame.height + EXIT_RISE_MM

    cables = []
    for run in ordered:
        manager = MANAGER_OF_KIND.get(run.kind, RIGHT)
        lane_x, lane_z = frame.lane(manager, next_lane[manager])
        next_lane[manager] += 1

        start = exits[(run.cable.pk, run.local_device.pk)]
        points = [start, (start[0], start[1], lane_z), (lane_x, start[1], lane_z)]
        if _is_internal(run, boxes):
            end = exits[(run.cable.pk, run.peer_device.pk)]
            points += [(lane_x, end[1], lane_z), (end[0], end[1], lane_z), end]
            cables.append(SceneCable(run=run, manager=manager, points=points))
        else:
            points.append((lane_x, exit_y, lane_z))
            cables.append(SceneCable(run=run, manager=manager, points=points, end_label=_end_label(run)))
    return cables


def _band_box(frame: CabinetFrame, band) -> Box:
    height = band.units * UNIT_MM
    return Box(
        x=0.0,
        y=frame.y_bottom(band.offset) + height / 2,
        z=(frame.front_rail_z + frame.rear_rail_z) / 2,
        w=frame.faceplate,
        h=height - DEVICE_GAP_MM,
        d=frame.mounting_depth,
    )


def build_scene(elevation: RackElevation) -> RackScene:
    """
    Lay a rack out in 3D, from the elevation of it the reader is allowed to see.
    """
    rack = elevation.rack
    frame = CabinetFrame(rack)

    devices = [scene_device(frame, mounted) for mounted in elevation.devices]
    boxes = {d.device.pk: d.box for d in devices}
    # A run the elevation could not attach to a cable row has nothing to be picked by.
    runs = [run for run in elevation.runs if run.cable is not None and run.local_device.pk in boxes]

    return RackScene(
        rack=rack,
        frame=frame,
        units=[
            (unit, frame.y_bottom(unit_offset(rack, unit, 1)) + UNIT_MM / 2)
            for unit in range(rack.starting_unit, rack.starting_unit + rack.u_height)
        ],
        devices=devices,
        cables=_route(frame, runs, boxes),
        reservations=[
            SceneBand(box=_band_box(frame, band), label=band.label, reservation=band.reservation)
            for band in elevation.reservations
        ],
        free=[SceneBand(box=_band_box(frame, band), label=band.label) for band in elevation.free if band.label],
    )
