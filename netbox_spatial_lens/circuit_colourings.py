"""
The colourings of the circuits on the world map.

The provider is the default: a circuit is the one thing on the map that belongs to somebody
outside the estate. It is not the only question a line answers. Which circuits are still
planned, which are the internet transits and whose they are are each a different colouring of
the same lines, and the legend of the map is also its filter.
"""

from collections.abc import Sequence
from dataclasses import replace

from netbox_spatial_lens.colouring import NO_DATA_COLOUR, Context, Level, Reading, builtin, by_name
from netbox_spatial_lens.palette import STATUS_COLOURS

__all__ = ()


@builtin(Level.CIRCUITS, 'provider', label='Provider', description='Who carries each circuit.')
def provider(circuits: Sequence, context: Context) -> dict[int, Reading]:
    """
    Who carries each circuit, and the map's default.
    """
    return by_name(circuits, 'provider')


@builtin(Level.CIRCUITS, 'type', label='Type', description='What each circuit is for.')
def kind(circuits: Sequence, context: Context) -> dict[int, Reading]:
    """
    What each circuit is for, in the colour NetBox gives its type where it has one.
    """
    readings = by_name(circuits, 'type')
    for circuit in circuits:
        if circuit.pk in readings and circuit.type.color:
            readings[circuit.pk] = replace(readings[circuit.pk], colour=f'#{circuit.type.color}')
    return readings


@builtin(Level.CIRCUITS, 'status', label='Status', description='What is live, planned or being retired.')
def status(circuits: Sequence, context: Context) -> dict[int, Reading]:
    """
    Lifecycle status, in the colours NetBox gives each status in the circuit list.
    """
    return {
        circuit.pk: Reading(
            circuit.get_status_display(),
            colour=STATUS_COLOURS.get(circuit.get_status_color(), NO_DATA_COLOUR),
        )
        for circuit in circuits
        if circuit.status
    }


@builtin(Level.CIRCUITS, 'tenant', label='Tenant', description='Who each circuit is for.')
def tenant(circuits: Sequence, context: Context) -> dict[int, Reading]:
    """
    Who each circuit is for.
    """
    return by_name(circuits, 'tenant')
