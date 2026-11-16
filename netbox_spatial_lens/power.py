"""
What a device draws, and where from.

NetBox answers this per object and per page: a device's draw is on the device, and the feed
behind it is several clicks away. The rack view asks both questions about twelve devices at
once, which is what makes the bulk resolution here worth having.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from netbox_spatial_lens.cabling import load_objects, peer_ends

__all__ = (
    'DevicePower',
    'load_device_power',
    'resolve_draws',
)


@dataclass
class DevicePower:
    """
    What a device draws, and where from.

    `allocated` is the figure NetBox computes for a power port, which is the maximum the
    device is declared to draw rather than anything measured. Saying "allocated" rather than
    "usage" matters: a rack that is full on paper may be idle in practice, and the two are
    different problems.
    """

    allocated_watts: float = 0
    maximum_watts: float = 0
    feeds: list = field(default_factory=list)
    unconnected: int = 0
    # True for a device with power outlets, such as a PDU: it supplies others.
    supplies: bool = False

    @property
    def sources(self) -> dict[int, str]:
        """The distinct power feeds this device reaches, by id, each named with its panel."""
        return {entry['feed_id']: f'{entry["feed"]} ({entry["panel"]})' for entry in self.feeds if entry['feed_id']}

    @property
    def redundancy(self) -> str | None:
        """
        How many feeds the device reaches, as a key of `palette.REDUNDANCY`.

        None where the question does not apply: a device with no power port, and a device that
        supplies others, whose single inlet is by design.
        """
        if self.supplies or not (self.feeds or self.unconnected):
            return None
        count = len(self.sources)
        if count >= 2:
            return 'redundant'
        return 'single' if count == 1 else 'untraced'

    @property
    def has_data(self) -> bool:
        return bool(self.maximum_watts or self.feeds or self.unconnected)


def load_device_power(devices: Sequence, totals: bool = True) -> dict[int, DevicePower]:
    """
    Draw and supply for each device, in a bounded number of queries.

    Four queries for the whole rack: the power ports, the outlets they are cabled to, the
    inlets those outlets draw from, and the feeds behind the inlets. It used to walk
    `link_peers` and `get_power_draw()` per port, which was 112 of a rack page's 182 queries.

    A device that feeds others needs its totals replaced by what draws through it, which costs
    a few more. That too is bounded, by the depth of the power tree rather than by the number
    of PDUs in the rack. A caller that only asks where the power comes from passes
    `totals=False` and is spared them.
    """
    from dcim.models import PowerOutlet, PowerPort

    device_ids = [d.pk for d in devices]
    if not device_ids:
        return {}

    ports = list(
        PowerPort.objects.filter(device_id__in=device_ids).values(
            'pk', 'device_id', 'name', 'cable_id', 'cable_end', 'allocated_draw', 'maximum_draw'
        )
    )
    if not ports:
        return {}

    near = {row['cable_id']: row['cable_end'] for row in ports if row['cable_id']}
    peers = peer_ends(near)
    load_objects(
        peers.values(),
        select_related={'poweroutlet': ('device', 'power_port'), 'powerfeed': ('power_panel',)},
    )

    # The feed behind each PDU inlet those outlets draw from, so the chain reaches past the
    # socket. Collected first, then resolved in one more pair of queries.
    inlets = {
        end.obj.power_port for end in peers.values() if isinstance(end.obj, PowerOutlet) and end.obj.power_port_id
    }
    inlet_peers = peer_ends({i.cable_id: i.cable_end for i in inlets if i.cable_id})
    load_objects(inlet_peers.values(), select_related={'powerfeed': ('power_panel',)})

    by_device = {}
    for row in ports:
        power = by_device.setdefault(row['device_id'], DevicePower())
        power.allocated_watts += row['allocated_draw'] or 0
        power.maximum_watts += row['maximum_draw'] or 0

        end = peers.get(row['cable_id']) if row['cable_id'] else None
        target = end.obj if end else None

        if isinstance(target, PowerOutlet):
            inlet = target.power_port
            feed = None
            if inlet is not None and inlet.cable_id:
                feed_end = inlet_peers.get(inlet.cable_id)
                feed = feed_end.obj if feed_end else None
            power.feeds.append(
                {
                    'port': row['name'],
                    'outlet': f'{target.device} \u00b7 {target}',
                    'feed': str(feed) if _is_feed(feed) else '',
                    'feed_id': feed.pk if _is_feed(feed) else None,
                    'panel': str(feed.power_panel) if _is_feed(feed) else '',
                }
            )
        elif _is_feed(target):
            # A PDU's own inlet cables straight to the feed rather than through an outlet.
            # Recorded here, otherwise the one device in the rack whose supply is certain
            # would be the one shown as having none.
            power.feeds.append(
                {
                    'port': row['name'],
                    'outlet': '',
                    'feed': str(target),
                    'feed_id': target.pk,
                    'panel': str(target.power_panel),
                }
            )
        else:
            power.unconnected += 1

    feeders = set(PowerOutlet.objects.filter(device_id__in=device_ids).values_list('device_id', flat=True))
    for device_id in feeders & by_device.keys():
        by_device[device_id].supplies = True
    if totals and feeders:
        _apply_aggregates(feeders, by_device)
    return by_device


def _apply_aggregates(feeders: set[int], by_device: dict[int, DevicePower]) -> None:
    """
    Replace the administrative totals for devices that feed others.

    A PDU's own `allocated_draw` says nothing useful; what matters is the sum of everything
    plugged into it. Summed over the device's power ports, so a dual-corded PDU reports both
    legs rather than whichever leg was read last.
    """
    from dcim.models import PowerPort

    # Every port of a feeding device, not only the ports that own outlets: a PDU may declare a
    # draw for its own electronics on a second inlet, and that is still load on the feed.
    ports = list(PowerPort.objects.filter(device_id__in=feeders).values_list('pk', 'device_id'))

    draws = resolve_draws({pk for pk, _ in ports})
    totals: dict[int, list[float]] = {}
    for pk, device_id in ports:
        allocated, maximum = draws.get(pk, (0.0, 0.0))
        running = totals.setdefault(device_id, [0.0, 0.0])
        running[0] += allocated
        running[1] += maximum

    for device_id, (allocated, maximum) in totals.items():
        power = by_device.get(device_id)
        if power is not None:
            power.allocated_watts = allocated
            power.maximum_watts = maximum


def resolve_draws(port_ids: set[int]) -> dict[int, tuple[float, float]]:
    """
    What each of `port_ids` draws, following everything plugged in below it.

    A power port that declares a draw is that draw. One that declares neither is the sum of
    the ports cabled to its outlets, resolved the same way, so the load of the servers at the
    bottom of a chain of PDUs carries up to the feed. This is what NetBox's
    `PowerPort.get_power_draw()` answers, and it agrees with it.

    It differs in how it gets there. NetBox walks the tree under one port at a time, which
    costs a handful of queries per PDU. This reads the tree a level at a time, so the cost is
    the depth of the power chain: two levels for a rack of PDUs and servers, whether the rack
    holds two PDUs or twenty.
    """
    from dcim.models import PowerOutlet, PowerPort
    from django.contrib.contenttypes.models import ContentType

    declared: dict[int, tuple[float | None, float | None]] = {}
    children: dict[int, list[int]] = {}
    frontier = set(port_ids)

    while frontier:
        auto = set()
        for pk, allocated, maximum in PowerPort.objects.filter(pk__in=frontier).values_list(
            'pk', 'allocated_draw', 'maximum_draw'
        ):
            declared[pk] = (allocated, maximum)
            # Both blank is NetBox's way of saying "work it out from what is plugged in".
            if allocated is None and maximum is None:
                auto.add(pk)
        if not auto:
            break

        outlets = PowerOutlet.objects.filter(power_port_id__in=auto, cable__isnull=False).values_list(
            'power_port_id', 'cable_id', 'cable_end'
        )
        near = {}
        owner = {}
        for port_id, cable_id, cable_end in outlets:
            near[cable_id] = cable_end
            owner[cable_id] = port_id

        port_type = ContentType.objects.get_for_model(PowerPort).pk
        frontier = set()
        for cable_id, end in peer_ends(near).items():
            # An outlet cabled to anything but a power port feeds nothing we can total.
            if end.type_id != port_type:
                continue
            children.setdefault(owner[cable_id], []).append(end.object_id)
            if end.object_id not in declared:
                frontier.add(end.object_id)

    def resolve(pk: int, seen: set[int]) -> tuple[float, float]:
        allocated, maximum = declared.get(pk, (None, None))
        if allocated is not None or maximum is not None:
            return float(allocated or 0), float(maximum or 0)
        total_allocated = total_maximum = 0.0
        for child in children.get(pk, ()):
            # A PDU wired back into itself would otherwise be followed forever.
            if child in seen:
                continue
            seen.add(child)
            child_allocated, child_maximum = resolve(child, seen)
            total_allocated += child_allocated
            total_maximum += child_maximum
        return total_allocated, total_maximum

    return {pk: resolve(pk, {pk}) for pk in port_ids}


def _is_feed(obj: Any) -> bool:
    return obj is not None and obj._meta.model_name == 'powerfeed'
