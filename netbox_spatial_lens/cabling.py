"""
Resolving what is on the other end of a cable, in bulk.

NetBox exposes this per object, as `termination.link_peers`, which walks the cable and its
terminations one at a time. That is the right shape for a page about one interface and the
wrong one for a page about a rack: a rack of twelve devices cost 177 queries, almost all of
them the same two walks repeated.

Everything here works on sets. A cable termination is a generic foreign key, so it cannot be
prefetched in one query, but it can be grouped by content type and fetched one query per model
instead of one per row. `CableTermination` also denormalises `_device` and `_rack`, so the
common questions ("which device is that end on", "is it in this rack") are answered without
touching the device table at all.

The rack view's cable runs are built here too, for the same reason: a run is a cable seen
from one rack, and everything it needs is already resolved above.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dcim.models import Cable, CableTermination, Rack
from django.contrib.contenttypes.models import ContentType

from netbox_spatial_lens.overlays import LegendEntry
from netbox_spatial_lens.palette import KIND

__all__ = (
    'CABLE_KIND_COLOURS',
    'KIND_LABELS',
    'RESTRICTED_LABEL',
    'CableRun',
    'PeerEnd',
    'build_runs',
    'kind_legend',
    'kind_of',
    'load_objects',
    'peer_ends',
)


# A stable order for termination rows, so "the first end of a cable" is the same on every read.
# By the cable's id column: the model's own ordering sorts by the cable, which joins its table.
TERMINATION_ORDER = ('cable_id', 'cable_end', 'pk')


class PeerEnd:
    """
    The far end of one cable, as far as the database rows describe it.

    `obj` is filled in only when the caller asked for the objects themselves; the identity and
    the denormalised device and rack are always present, and are enough for most questions.
    """

    __slots__ = ('cable_id', 'device_id', 'obj', 'object_id', 'rack_id', 'type_id')

    def __init__(
        self,
        cable_id: int,
        type_id: int,
        object_id: int,
        device_id: int | None,
        rack_id: int | None,
        obj: Any = None,
    ) -> None:
        self.cable_id = cable_id
        self.type_id = type_id
        self.object_id = object_id
        self.device_id = device_id
        self.rack_id = rack_id
        self.obj = obj

    def __repr__(self) -> str:
        return f'<PeerEnd cable={self.cable_id} object={self.type_id}:{self.object_id}>'


def peer_ends(near_ends: Mapping[int, str]) -> dict[int, PeerEnd]:
    """
    The opposite end of each cable, in one query.

    `near_ends` maps a cable id to the `cable_end` the caller is standing on, 'A' or 'B'. A
    cable with several terminations on the far end yields the first; this plugin draws one
    line per cable, so the rest would have nowhere to go.

    Returns cable id to PeerEnd, with `obj` unset. Call `load_objects` when the objects
    themselves are needed.
    """
    if not near_ends:
        return {}

    rows = (
        CableTermination.objects.filter(cable_id__in=near_ends)
        .order_by(*TERMINATION_ORDER)
        .values_list('cable_id', 'cable_end', 'termination_type_id', 'termination_id', '_device_id', '_rack_id')
    )

    peers = {}
    for cable_id, end, type_id, object_id, device_id, rack_id in rows:
        if end == near_ends.get(cable_id) or cable_id in peers:
            continue
        peers[cable_id] = PeerEnd(cable_id, type_id, object_id, device_id, rack_id)
    return peers


def load_objects(
    ends: Iterable[PeerEnd], select_related: Mapping[str, Sequence[str]] | None = None
) -> Iterable[PeerEnd]:
    """
    Fetch the objects behind a collection of PeerEnds, one query per content type.

    A generic foreign key cannot be prefetched, so the alternative is a query per row. Grouping
    by content type first turns a rack's worth of terminations into a handful of queries: one
    for the interfaces, one for the power outlets, one for the circuit terminations.

    `select_related` maps a model name to the related fields to pull in with it, so a caller
    that needs `outlet.power_port` does not pay for it a second time.
    """
    by_type = defaultdict(list)
    for end in ends:
        if end is not None and end.obj is None:
            by_type[end.type_id].append(end)

    for type_id, group in by_type.items():
        content_type = ContentType.objects.get_for_id(type_id)
        model = content_type.model_class()
        if model is None:
            # A termination type this NetBox no longer installs. Left unresolved rather than
            # raising: a stale row should not take a page down.
            continue

        queryset = model.objects.filter(pk__in={e.object_id for e in group})

        # Every termination that lives on a device is named as "device · port" somewhere, and
        # a device fetched per row is the N+1 this module exists to remove. Pulled in by
        # default rather than left to each caller to remember.
        related = set((select_related or {}).get(content_type.model, ()))
        if any(f.name == 'device' for f in model._meta.fields):
            related.add('device')
        if related:
            queryset = queryset.select_related(*related)

        objects = queryset.in_bulk()
        for end in group:
            end.obj = objects.get(end.object_id)

    return ends


@dataclass
class CableRun:
    """
    One cable leaving a device in this rack.

    `peer_device` is None when the far end is not a device at all, which a circuit termination
    or a power feed is. Those still matter: a rack whose uplink goes to a circuit should say
    so rather than showing a cable that appears to stop in mid-air.
    """

    cable: object
    local_device: object
    local_name: str
    peer_name: str
    peer_device: object | None
    peer_rack: object | None
    colour: str
    kind: str  # 'interface', 'power', 'console', 'passthrough' or 'other'
    # Whether the far end is a device mounted in this rack, so the cable is drawn end to end
    # rather than leaving through the roof.
    internal: bool = False
    # The local end, so the run can be traced end to end from here.
    termination_type: str = ''
    termination_id: int | None = None
    # The far end's port on its own, without its device. The per-device cabling list reads
    # outward from whichever device you selected, so when that device is the far end its own
    # name would otherwise be repeated on every row.
    peer_port_name: str = ''


# Kept as a name for what the drawing needs; the values live in the palette.
CABLE_KIND_COLOURS = KIND

# What each cable colour means, in the order a network engineer reads them: data first,
# then the ports a path passes through, then the out-of-band and power that support it.
KIND_LABELS = {
    'interface': 'Interface',
    'passthrough': 'Patch panel',
    'circuit': 'Circuit',
    'console': 'Console',
    'power': 'Power',
    'other': 'Other',
}


# What the far end of a cable or a hop is called when the reader may not see it. The link is
# drawn, because the reader may see this end of it; what it reaches is not named.
RESTRICTED_LABEL = 'Restricted'


def kind_of(termination: Any) -> str:
    """
    What kind of link a termination is, as a key of `KIND_LABELS`.

    Shared by the rack drawing and the trace panel, so a hop and the cable it follows are
    always the same colour.
    """
    if termination is None:
        return 'other'
    name = termination._meta.model_name
    if 'interface' in name:
        return 'interface'
    if 'power' in name:
        return 'power'
    if 'console' in name:
        return 'console'
    if 'frontport' in name or 'rearport' in name:
        return 'passthrough'
    if 'circuit' in name or 'provider' in name:
        return 'circuit'
    return 'other'


def build_runs(
    rack: Rack, devices: Sequence, order_by_device: Mapping[int, float], devices_queryset=None
) -> list[CableRun]:
    """
    Every cable with at least one end on a device in this rack.

    `order_by_device` holds the devices mounted at a U, each with the key its cables are listed
    by, so the list reads down the cabinet. A device missing from it has no position to draw a
    cable from.

    Built from the termination rows rather than from the cables, so the whole rack costs a
    handful of queries instead of one per cable end. Walking `cable.terminations` and touching
    each generic `termination` was 65 of a rack page's 182 queries.

    A cable with both ends in the rack yields one run, not two: drawing it twice would show a
    single patch lead as two, and double every count on the page.

    `devices_queryset` is what the reader may see. A far end on a device outside it is drawn as
    a cable leaving the rack and named `RESTRICTED_LABEL`, so the drawing does not name a device
    the rest of NetBox would refuse to show.
    """
    devices_by_id = {d.pk: d for d in devices}
    device_ids = set(devices_by_id)
    if not device_ids:
        return []

    # Our own ends first: every termination in this rack that carries a cable.
    near_rows = (
        CableTermination.objects.filter(_device_id__in=device_ids)
        .order_by(*TERMINATION_ORDER)
        .values_list('cable_id', 'cable_end', 'termination_type_id', 'termination_id', '_device_id')
    )
    near = {}
    near_ends = {}
    for cable_id, end, type_id, object_id, device_id in near_rows:
        # A cable with both ends in the rack appears twice, and is drawn once, from an end that
        # has a U position.
        held = near.get(cable_id)
        if held is not None and (held.device_id in order_by_device or device_id not in order_by_device):
            continue
        near[cable_id] = PeerEnd(cable_id, type_id, object_id, device_id, rack.pk)
        near_ends[cable_id] = end

    if not near:
        return []

    peers = peer_ends(near_ends)
    load_objects(list(near.values()) + list(peers.values()))

    # One query for the cables themselves, for their labels.
    cables = Cable.objects.in_bulk(near)
    # And one for the racks the far ends sit in, which the termination rows already name.
    rack_ids = {p.rack_id for p in peers.values() if p.rack_id and p.rack_id != rack.pk}
    racks = Rack.objects.in_bulk(rack_ids) if rack_ids else {}

    peer_device_ids = {p.device_id for p in peers.values() if p.device_id}
    if devices_queryset is None:
        visible = peer_device_ids
    else:
        visible = set(devices_queryset.filter(pk__in=peer_device_ids).values_list('pk', flat=True))

    runs = []
    for cable_id, local in near.items():
        if local.device_id not in order_by_device or local.obj is None:
            # The local end is on a device with no U position, so there is no row to draw
            # from. It still appears in the unplaced list.
            continue
        peer = peers.get(cable_id)
        if peer is None or peer.obj is None:
            # A cable with one end recorded is a half-documented link, with no second point
            # to draw it to.
            continue

        kind = kind_of(local.obj)
        peer_device = getattr(peer.obj, 'device', None)
        if peer.device_id and peer.device_id not in visible:
            peer_device, peer_name, peer_port_name, peer_rack = None, RESTRICTED_LABEL, RESTRICTED_LABEL, None
        else:
            peer_name = f'{peer_device} \u00b7 {peer.obj}' if peer_device else str(peer.obj)
            peer_port_name = str(peer.obj)
            peer_rack = racks.get(peer.rack_id)
        runs.append(
            CableRun(
                cable=cables.get(cable_id),
                local_device=devices_by_id[local.device_id],
                local_name=str(local.obj),
                peer_name=peer_name,
                peer_port_name=peer_port_name,
                peer_device=peer_device,
                peer_rack=peer_rack,
                colour=CABLE_KIND_COLOURS[kind],
                internal=bool(peer_device) and peer.device_id in order_by_device,
                kind=kind,
                termination_type=f'{local.obj._meta.app_label}.{local.obj._meta.model_name}',
                termination_id=local.object_id,
            )
        )

    runs.sort(key=lambda r: (order_by_device[r.local_device.pk], r.local_name))
    return runs


def kind_legend(runs: Iterable) -> list[LegendEntry]:
    """
    What the cable colours in one rack mean, and how many of each there are.

    Only the kinds actually present: a rack with no console cable has nothing to say about
    purple, and a legend of six entries where two apply is harder to read than one of two.
    """
    counts: dict[str, int] = {}
    for run in runs:
        counts[run.kind] = counts.get(run.kind, 0) + 1
    return [
        LegendEntry(CABLE_KIND_COLOURS[kind], label, counts[kind], key=kind)
        for kind, label in KIND_LABELS.items()
        if kind in counts
    ]
