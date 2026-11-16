"""
The colourings of the sites on the world map.

Group is a good default and a poor only option: at this zoom the question is as often "what is
still planned", "who owns this" or "which region is this in", and each is a different colouring
of the same set of points. It matters more here than on the floor, because the legend on the
map is also its filter, so what it can colour by is what a reader can narrow to.
"""

from collections.abc import Sequence

from netbox_spatial_lens.colouring import NO_DATA_COLOUR, Context, Level, Reading, builtin, by_name
from netbox_spatial_lens.palette import STATUS_COLOURS

__all__ = ()


@builtin(Level.SITES, 'group', label='Group', description='How the estate is organised.')
def group(sites: Sequence, context: Context) -> dict[int, Reading]:
    """
    The site group: how an estate is usually organised, and the map's default.

    A map of two dozen identical dots throws that organisation away, and which of these is a
    branch and which is a data centre is exactly the question at this zoom.
    """
    return by_name(sites, 'group')


@builtin(Level.SITES, 'status', label='Status', description='What is live, planned or being retired.')
def status(sites: Sequence, context: Context) -> dict[int, Reading]:
    """
    Lifecycle status: what is live, what is planned, what is being decommissioned.

    NetBox already assigns each status a colour, so this reads the same as the site list
    rather than inventing a second scheme for the same fact.
    """
    return {
        site.pk: Reading(site.get_status_display(), colour=STATUS_COLOURS.get(site.get_status_color(), NO_DATA_COLOUR))
        for site in sites
        if site.status
    }


@builtin(Level.SITES, 'tenant', label='Tenant', description='Who owns each site.')
def tenant(sites: Sequence, context: Context) -> dict[int, Reading]:
    """
    Who owns each site.
    """
    return by_name(sites, 'tenant')


@builtin(Level.SITES, 'region', label='Region', description='The region each site is filed under.')
def region(sites: Sequence, context: Context) -> dict[int, Reading]:
    """
    Where each site is, by NetBox's own geography rather than by its coordinates.

    The map already places a site by latitude and longitude. This says which region somebody
    filed it under, which is what an estate is actually run by and is not always what the
    coordinates suggest.
    """
    return by_name(sites, 'region')
