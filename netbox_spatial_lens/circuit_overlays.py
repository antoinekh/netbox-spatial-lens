"""
What colours a circuit on the world map.

The provider is the default: a circuit is the one thing on the map that belongs to somebody
outside the estate. It is not the only question a line answers. Which circuits are still
planned, which are the internet transits and whose they are are each a different colouring of
the same lines, and the legend of the map is also its filter.

Registered the same way the other three levels are, so another plugin can add one.
"""

from collections.abc import Sequence

from netbox_spatial_lens.overlays import (
    NO_DATA_COLOUR,
    BuiltinColouring,
    Colouring,
    RackValue,
    Registry,
    colour_by_related,
)
from netbox_spatial_lens.palette import STATUS_COLOURS

__all__ = (
    'BUILTIN_CIRCUIT_OVERLAYS',
    'CircuitOverlay',
    'get_circuit_overlay',
    'get_circuit_overlays',
    'register_builtin_circuit_overlays',
    'register_circuit_overlay',
    'registry',
    'resolve_circuit_overlay',
)


class CircuitOverlay(Colouring):
    """
    A named way of colouring the circuits on the world map.

    `fn` takes the circuits and returns a dict of circuit id to RackValue.
    """


def provider_overlay(circuits: Sequence) -> dict[int, RackValue]:
    """
    Who carries each circuit, and the map's default.
    """
    return colour_by_related(circuits, 'provider')


def type_overlay(circuits: Sequence) -> dict[int, RackValue]:
    """
    What each circuit is for, in the colour NetBox gives its type where it has one.
    """
    values = colour_by_related(circuits, 'type')
    for circuit in circuits:
        if circuit.pk in values and circuit.type.color:
            values[circuit.pk].colour = f'#{circuit.type.color}'
    return values


def tenant_overlay(circuits: Sequence) -> dict[int, RackValue]:
    """
    Who each circuit is for.
    """
    return colour_by_related(circuits, 'tenant')


def status_overlay(circuits: Sequence) -> dict[int, RackValue]:
    """
    Lifecycle status, in the colours NetBox gives each status in the circuit list.
    """
    values = {}
    for circuit in circuits:
        if not circuit.status:
            continue
        values[circuit.pk] = RackValue(
            colour=STATUS_COLOURS.get(circuit.get_status_color(), NO_DATA_COLOUR),
            label=circuit.get_status_display(),
            value=circuit.status,
        )
    return values


BUILTIN_CIRCUIT_OVERLAYS = {
    'provider': BuiltinColouring('Provider', provider_overlay, 'Who carries each circuit.'),
    'type': BuiltinColouring('Type', type_overlay, 'What each circuit is for.'),
    'status': BuiltinColouring('Status', status_overlay, 'What is live, planned or being retired.'),
    'tenant': BuiltinColouring('Tenant', tenant_overlay, 'Who each circuit is for.'),
}

# The colourings of the circuits. The functions below are the names other plugins register with.
registry = Registry(
    kind=CircuitOverlay,
    noun='Circuit overlay',
    default_setting='default_circuit_overlay',
    builtins_setting='enable_builtin_circuit_overlays',
    builtins=BUILTIN_CIRCUIT_OVERLAYS,
)
register_circuit_overlay = registry.register
get_circuit_overlays = registry.all
get_circuit_overlay = registry.get
resolve_circuit_overlay = registry.resolve
register_builtin_circuit_overlays = registry.register_builtins
