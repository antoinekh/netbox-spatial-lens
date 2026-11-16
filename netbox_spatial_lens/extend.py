"""
What another plugin builds on. Import from here, and from nowhere else in the plugin: the names
in `__all__` are the ones a release keeps, and the changelog says when one changes.

An extension is a module named `spatial_lens` in your plugin or app. It is imported by itself
the first time a colouring is needed, whatever the order of `PLUGINS`:

    # yourplugin/spatial_lens.py
    from netbox_spatial_lens.extend import UTILISATION, Level, colouring

    @colouring(Level.RACKS, 'heat', label='Heat', bands=UTILISATION)
    def heat(racks, context):
        return {rack.pk: UTILISATION.reading(percent, f'{percent:.0f}% of capacity') for ...}

See docs/extending.md.
"""

from netbox_spatial_lens import palette
from netbox_spatial_lens.colouring import (
    COMPLETION,
    UTILISATION,
    Band,
    Context,
    Level,
    Reading,
    Scale,
    by_name,
    colouring,
)

__all__ = (
    'COMPLETION',
    'UTILISATION',
    'Band',
    'Context',
    'Level',
    'Reading',
    'Scale',
    'by_name',
    'colouring',
    'palette',
)
