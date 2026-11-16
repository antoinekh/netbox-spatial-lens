"""
The colourings of the devices in a rack.

The elevation used to answer one question, "what role is each of these", by hard-coding the
role colour. The questions people bring to a rack are wider: what is still planned, who owns
which units, which devices nobody has cabled, which are near their power limit and which depend
on one feed. Each is a different colouring of the same drawing.

What the rack view already knows of a device, its ports and its power, is in `context.mounted`,
so no colouring here reads the database.
"""

from collections.abc import Sequence

from netbox_spatial_lens.colouring import (
    COMPLETION,
    NO_DATA_COLOUR,
    REDUNDANCY,
    UTILISATION,
    Context,
    Level,
    Reading,
    builtin,
    by_name,
)
from netbox_spatial_lens.palette import NO_ROLE, STATUS_COLOURS

__all__ = ()


@builtin(Level.DEVICES, 'role', label='Role', description='The device role, in its own colour.')
def role(devices: Sequence, context: Context) -> dict[int, Reading]:
    """
    The device role, in its own colour. The default.
    """
    return {
        device.pk: Reading(device.role.name, colour=f'#{device.role.color}' if device.role.color else NO_ROLE)
        for device in devices
        if device.role is not None
    }


@builtin(Level.DEVICES, 'status', label='Status', description='What is live, staged, failed or planned.')
def status(devices: Sequence, context: Context) -> dict[int, Reading]:
    """
    Lifecycle status: what is live, what is staged, what has failed.

    NetBox already assigns each status a colour, so this reads the same as the device list
    rather than inventing a second scheme for the same fact.
    """
    return {
        device.pk: Reading(
            device.get_status_display(),
            colour=STATUS_COLOURS.get(device.get_status_color(), NO_DATA_COLOUR),
        )
        for device in devices
        if device.status
    }


@builtin(Level.DEVICES, 'tenant', label='Tenant', description='Who owns each device.')
def tenant(devices: Sequence, context: Context) -> dict[int, Reading]:
    """
    Who owns each device, which is the question in any shared or colocated rack.
    """
    return by_name(devices, 'tenant')


@builtin(
    Level.DEVICES,
    'cabling',
    label='Cabling',
    description='How much of each device is plugged in.',
    bands=COMPLETION,
)
def cabling(devices: Sequence, context: Context) -> dict[int, Reading]:
    """
    How much of each device is actually plugged in.

    The question before a hand-over: a rack can be full of devices and empty of links, and
    that is invisible in every other colouring.
    """
    readings = {}
    for device in devices:
        mounted = context.mounted[device.pk]
        if not mounted.port_count:
            continue
        connected = mounted.connected_count
        percent = connected / mounted.port_count * 100
        # The count first, because "3 of 48" is what somebody acts on; the percentage is what
        # makes two devices comparable at a glance.
        label = f'{connected} of {mounted.port_count} cabled ({percent:.0f}%)'
        readings[device.pk] = COMPLETION.reading(percent, label)
    return readings


@builtin(
    Level.DEVICES,
    'power',
    label='Power',
    description='Allocated draw against the device maximum.',
    bands=UTILISATION,
)
def power(devices: Sequence, context: Context) -> dict[int, Reading]:
    """
    Allocated draw against what the device declares it can take.

    Both figures are administrative rather than measured, so the label says "allocated": a
    rack full on paper may be idle in practice, and the two are different problems.
    """
    readings = {}
    for device in devices:
        drawn = context.mounted[device.pk].power
        if drawn is None or not drawn.maximum_watts:
            continue
        percent = drawn.allocated_watts / drawn.maximum_watts * 100
        readings[device.pk] = UTILISATION.reading(
            percent, f'{drawn.allocated_watts:.0f} W of {drawn.maximum_watts:.0f} W'
        )
    return readings


@builtin(
    Level.DEVICES,
    'redundancy',
    label='Redundancy',
    description='How many power feeds each device reaches.',
    bands=REDUNDANCY,
)
def redundancy(devices: Sequence, context: Context) -> dict[int, Reading]:
    """
    How many power feeds each device reaches.

    A device with two supplies cabled to one feed, or with one of them not cabled, goes dark
    with that feed. The power colouring cannot show it: both devices draw the same.
    """
    readings = {}
    for device in devices:
        drawn = context.mounted[device.pk].power
        state = drawn.redundancy if drawn is not None else None
        if state is None:
            continue
        sources = sorted(drawn.sources.values())
        if sources:
            label = f'{len(sources)} feed{"s" if len(sources) != 1 else ""}: {", ".join(sources)}'
        else:
            label = 'No feed traced'
        readings[device.pk] = Reading(label, band=state)
    return readings
