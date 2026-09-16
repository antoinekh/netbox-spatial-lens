"""
The world view: sites, and what runs between them.

This builds the data; the page draws it on a MapLibre globe, which does its own projection
from each point's latitude and longitude. There is one renderer. A browser without WebGL, or
one that cannot load MapLibre, is told so, and still gets the figures, the legends and the
lists this builds.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from circuits.models import Circuit, CircuitTermination
from dcim.models import Site
from django.db.models import Count, Prefetch, Q
from django.urls import reverse

from netbox_spatial_lens.overlays import NO_DATA_COLOUR as NO_DATA
from netbox_spatial_lens.overlays import NO_DATA_LABEL, LegendEntry, Stat
from netbox_spatial_lens.palette import NODE, distinct_colours
from netbox_spatial_lens.site_overlays import resolve_site_overlay

__all__ = (
    'WorldLink',
    'WorldMap',
    'WorldNode',
    'build_world',
)

# A site's marker, scaled between these by rack count.
MIN_RADIUS = 7
MAX_RADIUS = 22

SITE_COLOUR = NODE['site']
PROVIDER_COLOUR = NODE['provider']
# The legend band of a provider network. Not a colour and not a label, so no site band can take it.
PROVIDER_KEY = 'lens:provider'


@dataclass
class WorldNode:
    """
    A site, or a provider network, as a point on the map.
    """

    key: str
    label: str
    kind: str  # 'site' or 'provider'
    radius: float
    colour: str
    url: str = ''
    detail: str = ''
    object_id: int | None = None
    # Where the point is. The map projects it itself.
    lat: float | None = None
    lon: float | None = None
    # What the hover card shows, as ordered label/value pairs. A list rather than fields so a
    # site and a provider network can describe themselves differently without the template
    # branching on which kind it is.
    facts: list = field(default_factory=list)
    status: str = ''
    link_count: int = 0
    # The legend band this node falls in, as the key the legend picks it by: the group, status,
    # tenant or region name for a site, and `PROVIDER_KEY` for a provider network.
    band: str = ''
    # What clicking the node does, in words, for the hover card and the finder. A site opens
    # its Spatial Lens tab, or its one room where it has one; a provider network has no page.
    action: str = 'Trace'


@dataclass
class WorldLink:
    """
    A circuit drawn between two nodes.
    """

    circuit: object
    a: WorldNode
    z: WorldNode
    width: float
    label: str
    # The provider's colour. A circuit is the one thing on this map that belongs to somebody
    # outside the estate, and which of them a line belongs to is the question the drawing held
    # the answer to and could not be asked.
    colour: str = NO_DATA


@dataclass
class WorldMap:
    nodes: list = field(default_factory=list)
    links: list = field(default_factory=list)
    ungeocoded: list = field(default_factory=list)
    # What the colours mean, and how many points are in each. Built here rather than in the
    # template because a colour is derived from a name, and the two must not be derived twice.
    legend: list = field(default_factory=list)
    # The headline figures above the map.
    stats: list = field(default_factory=list)
    # What the circuit colours mean. Its own legend rather than more bands in the site one:
    # a provider is not a kind of site, and the two narrow independently.
    providers: list = field(default_factory=list)

    @property
    def site_nodes(self) -> list[WorldNode]:
        return [n for n in self.nodes if n.kind == 'site']


def build_world(sites_queryset=None, overlay=None, circuits=None) -> WorldMap:
    """
    Every geocoded site, and the circuits joining them.

    A site with no coordinates cannot be drawn. It is listed rather than dropped, because a
    map missing half an estate that says nothing about it is worse than no map.

    `sites_queryset` is the set of sites the caller may see. The view passes its own restricted
    queryset, so a user with object permissions over part of the estate gets a map of that part
    rather than of everything. Defaulting to every site keeps the function usable from a shell
    or a command, where there is no user to restrict against.

    `overlay` is what the points are coloured by, and the site group when nothing is named. It
    is asked for the whole set at once, because a categorical colouring has to settle clashes
    between two names that hash to one colour, and that cannot be decided one site at a time.

    `circuits` is restricted the same way, and for the same reason: a user allowed to see the
    sites but not the circuits between them should not be handed every CID, provider and commit
    rate in the estate because the lines happen to be drawn on a map they may open.
    """
    base = Site.objects.all() if sites_queryset is None else sites_queryset
    # The hover card names the region, the group and the tenant, so they are fetched with the
    # site. Left to attribute access they were three queries per site, which is most of what
    # this view used to spend.
    base = base.select_related('region', 'group', 'tenant')
    sites = list(base.exclude(latitude=None).exclude(longitude=None))
    ungeocoded = list(base.filter(Q(latitude=None) | Q(longitude=None)))

    if not sites:
        return WorldMap(nodes=[], links=[], ungeocoded=ungeocoded)

    # One query for the counts the hover card needs, rather than one per site.
    counted = {
        row['pk']: row
        for row in Site.objects.filter(pk__in=[s.pk for s in sites])
        # Prefixed, because `racks` and `devices` are reverse accessors on Site and Django
        # refuses an annotation that shadows a field.
        .annotate(n_racks=Count('racks', distinct=True), n_devices=Count('devices', distinct=True))
        .values('pk', 'n_racks', 'n_devices')
    }
    rack_counts = {pk: row['n_racks'] for pk, row in counted.items()}
    busiest = max(rack_counts.values() or [1]) or 1

    # With none given, the same colouring the page would pick: the configured default, which is
    # the site group, else the first registered. A deployment that switches every colouring off
    # still gets a map: the points keep the plain site blue and the legend explains only the
    # provider networks.
    overlay = overlay or resolve_site_overlay(None)
    values = overlay.evaluate(sites) if overlay else {}

    nodes = {}
    for site in sites:
        racks = rack_counts.get(site.pk, 0)
        nodes[f'site:{site.pk}'] = WorldNode(
            key=f'site:{site.pk}',
            label=site.name,
            kind='site',
            # Area, not radius, tracks the rack count, so a site with four times the racks
            # looks four times the size rather than sixteen.
            radius=MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * math.sqrt(racks / busiest),
            # A map of two dozen identical blue dots throws away everything the estate is
            # organised by: which of these is a branch and which is a data centre is exactly
            # the question at this zoom. The colouring answers it, and a site it cannot answer
            # for is grey and counted rather than quietly passed off as ordinary.
            colour=values[site.pk].colour if site.pk in values else SITE_COLOUR,
            band=overlay.band_of(values[site.pk]) if site.pk in values else '',
            # The site's Spatial Lens tab, which lists its racks and offers to add a floor. The view
            # replaces it with the room itself where the site has exactly one.
            url=reverse('dcim:site_lens', args=[site.pk]),
            action='Open the site',
            detail=f'{racks} rack{"s" if racks != 1 else ""}',
            object_id=site.pk,
            lat=float(site.latitude),
            lon=float(site.longitude),
            status=site.get_status_display(),
            facts=_site_facts(site, counted.get(site.pk, {}), overlay, values.get(site.pk)),
        )

    links = _build_links(nodes, circuits)
    for link in links:
        link.a.link_count += 1
        link.z.link_count += 1

    providers = sum(1 for n in nodes.values() if n.kind == 'provider')

    return WorldMap(
        nodes=list(nodes.values()),
        links=links,
        ungeocoded=ungeocoded,
        legend=_world_legend(overlay, values, providers),
        stats=_world_stats(sites, counted, links, ungeocoded, providers),
        providers=_provider_legend(links),
    )


def _world_legend(overlay, values: Mapping, providers: int) -> list[LegendEntry]:
    """
    What the colours on the map mean, and how many points are in each.

    The colouring's own bands first, then the provider networks. A provider network is not a
    site and is listed here anyway, because this is the key to the colours on one drawing and a
    reader matching purple against it does not care which model it came from. It also makes
    "show me only the clouds" the same gesture as "show me only the branch offices".

    Every point on the map is accounted for. A map whose legend explains twenty of twenty-eight
    sites is a map you cannot trust the other eight of, so the band for sites the colouring
    could not answer for is counted and kept even when it is empty.
    """
    entries = overlay.legend_for(values.values()) if overlay else []
    if providers:
        entries.append(LegendEntry(PROVIDER_COLOUR, 'Provider network', providers, key=PROVIDER_KEY))
    return entries


def _provider_legend(links: Sequence) -> list[LegendEntry]:
    """
    What the circuit colours mean, and how many circuits each provider carries.

    Counted over the circuits actually drawn rather than over every provider in the database:
    a legend on this map explains this map, and a provider whose circuits both end somewhere
    unplaced has no line here to explain.

    A circuit with no provider recorded keeps the grey, is named and is counted, which is the
    rule every other legend in the plugin follows.

    The swatches are read off the lines rather than derived a second time. Deriving them again
    means choosing colours over a different set of providers, and the clash-resolution in
    `distinct_colours` gives a different answer for a different set: one undrawn circuit could
    shift the colour of every provider after it, and the legend would name a colour nothing on
    the map wore. Reading the drawn lines cannot drift from them.
    """
    if not links:
        return []

    counts: dict[str, int] = {}
    colours: dict[str, str] = {}
    for link in links:
        provider = getattr(link.circuit, 'provider', None)
        name = provider.name if provider else ''
        counts[name] = counts.get(name, 0) + 1
        if name:
            colours[name] = link.colour

    entries = [LegendEntry(colours[name], name, counts[name]) for name in sorted(colours)]
    entries.append(LegendEntry(NO_DATA, NO_DATA_LABEL, counts.get('', 0)))
    return entries


def _commit_rate(links: Sequence) -> str:
    """
    The committed bandwidth of the circuits on the map, as a reader would say it.

    NetBox records a commit rate in kbps. Summed across an estate that is a number nobody reads
    in kbps, so it is given in the largest unit that leaves a figure under four digits.
    """
    total = sum(getattr(link.circuit, 'commit_rate', None) or 0 for link in links)
    if not total:
        return ''
    for unit, size in (('Tbps', 1_000_000_000), ('Gbps', 1_000_000), ('Mbps', 1_000)):
        if total >= size:
            return f'{total / size:g} {unit} committed'
    return f'{total:g} kbps committed'


def _world_stats(
    sites: Sequence,
    counted: Mapping,
    links: Sequence,
    ungeocoded: Sequence,
    providers: int,
) -> list[Stat]:
    """
    The headline figures above the map.

    A map answers "where". These answer "how much", which is the question somebody usually
    arrives with, and at this zoom it is the size and reach of the estate: how many sites, how
    much is in them, and how much circuit runs between them.

    The sites figure carries what could not be drawn. An estate half of which has no
    coordinates must not read as an estate half its size, which is the same honesty rule the
    floor keeps about a rack nobody has measured.
    """
    if not sites:
        return []

    racks = sum(row['n_racks'] for row in counted.values())
    devices = sum(row['n_devices'] for row in counted.values())
    missing = len(ungeocoded)

    stats = [
        Stat(
            label='Sites',
            # The whole estate, not the drawn part of it. "Sites 10, 10 without coordinates"
            # is a figure arguing with its own caption; the count has to be the number the
            # caption is subtracting from.
            value=str(len(sites) + missing),
            detail=f'{missing} without coordinates' if missing else 'all placed',
        ),
        # These two are summed over the sites on the map, because they come from the same
        # query that placed them, so they say so rather than claiming the whole estate.
        Stat(label='Racks', value=str(racks), detail='in the sites on the map'),
        Stat(label='Devices', value=str(devices), detail='in the sites on the map'),
        Stat(
            label='Circuits',
            value=str(len(links)),
            detail=_commit_rate(links) or 'no commit rate recorded',
        ),
    ]
    if providers:
        stats.append(
            Stat(label='Provider networks', value=str(providers), detail='reached by circuit'),
        )
    return stats


def _site_facts(site, counts: Mapping, overlay=None, value=None) -> list[tuple[str, str]]:
    """
    The lines under a site's name on hover.

    Only what is actually recorded: an empty field is left out rather than shown as a dash,
    because a hover card padded with blanks reads as an inventory in worse shape than it is.

    The colouring's reading comes first, as the floor's hover card names it too, unless the card
    already says it: coloured by group, the group is on its own line, and the status is the badge.
    """
    facts = []
    if overlay is not None and value is not None and value.has_data:
        facts.append((overlay.label, value.label))
    if site.region:
        facts.append(('Region', str(site.region)))
    if site.group:
        facts.append(('Group', str(site.group)))
    if site.tenant:
        facts.append(('Tenant', str(site.tenant)))
    facts.append(('Racks', str(counts.get('n_racks', 0))))
    facts.append(('Devices', str(counts.get('n_devices', 0))))
    if site.physical_address:
        # First line only: a hover card is not the place for a postal address.
        facts.append(('Address', site.physical_address.splitlines()[0]))
    if facts and value is not None and value.has_data:
        said = {text for _, text in facts[1:]} | {site.get_status_display()}
        if value.label in said:
            facts.pop(0)
    return facts


def _endpoint_key(termination) -> tuple[str | None, str | None, str | None]:
    """
    Which node a circuit termination belongs to.

    A termination lands either on something inside a site or on a provider network. The
    provider network is a real endpoint, not an absence: a branch office reaching an MPLS
    cloud is the WAN, and drawing only site-to-site links would show an estate with no
    connectivity at all.
    """
    site = getattr(termination, '_site', None) or getattr(termination, 'site', None)
    if site:
        return f'site:{site.pk}', site.name, 'site'
    network = getattr(termination, '_provider_network', None) or getattr(termination, 'provider_network', None)
    if network:
        return f'provider:{network.pk}', str(network), 'provider'
    return None, None, None


def _build_links(nodes: dict, circuits=None) -> list[WorldLink]:
    """
    Circuits with both ends resolvable, drawn between their endpoints.

    A provider network is given a position of its own: the centre of the sites reaching it.
    That places an MPLS cloud in the middle of the estate that uses it, which is where a
    reader looks for it.
    """
    # The terminations are read with the denormalised endpoint columns `_endpoint_key` needs.
    # Left to attribute access, `termination._site` was a query per termination, which on an
    # estate of any size is the whole cost of this view.
    base = Circuit.objects.all() if circuits is None else circuits
    circuits = base.select_related('provider', 'type').prefetch_related(
        Prefetch(
            'terminations',
            queryset=CircuitTermination.objects.select_related('_site', '_provider_network'),
        )
    )

    pending, provider_members, provider_labels = [], {}, {}
    for circuit in circuits:
        terminations = list(circuit.terminations.all())
        if len(terminations) != 2:
            # One-ended circuits are common and are not links: there is no second point.
            continue
        a_key, a_label, a_kind = _endpoint_key(terminations[0])
        z_key, z_label, z_kind = _endpoint_key(terminations[1])
        if not a_key or not z_key or a_key == z_key:
            continue
        pending.append((circuit, a_key, z_key))

        for key, label, kind, other in (
            (a_key, a_label, a_kind, z_key),
            (z_key, z_label, z_kind, a_key),
        ):
            if kind != 'provider':
                continue
            provider_labels[key] = label
            if other.startswith('site:'):
                provider_members.setdefault(key, set()).add(other)

    for key, members in provider_members.items():
        sited = [nodes[m] for m in members if m in nodes]
        if not sited:
            continue
        label = provider_labels.get(key, key)
        nodes[key] = WorldNode(
            key=key,
            label=label,
            kind='provider',
            radius=MAX_RADIUS,
            colour=PROVIDER_COLOUR,
            band=PROVIDER_KEY,
            detail=f'{len(sited)} site{"s" if len(sited) != 1 else ""}',
            facts=[('Sites reached', str(len(sited)))],
            # A provider network has no address of its own, so it is placed at the mean of
            # the sites reaching it. Averaging the latitudes directly is close enough at the
            # scale of one estate, and a great-circle centroid would not move the pin far
            # enough to be worth the arithmetic.
            lat=sum(n.lat for n in sited) / len(sited),
            lon=sum(n.lon for n in sited) / len(sited),
        )

    # Chosen across the whole set, which is the only place two provider names hashing onto one
    # colour can be seen and settled.
    colours = distinct_colours(circuit.provider.name for circuit, _, _ in pending if getattr(circuit, 'provider', None))

    links = []
    for circuit, a_key, z_key in pending:
        if a_key not in nodes or z_key not in nodes:
            continue
        provider = getattr(circuit, 'provider', None)
        links.append(
            WorldLink(
                circuit=circuit,
                a=nodes[a_key],
                z=nodes[z_key],
                width=_link_width(circuit),
                label=f'{circuit.cid} · {circuit.provider}',
                colour=colours[provider.name] if provider else NO_DATA,
            )
        )
    return links


def _link_width(circuit) -> float:
    """
    Thicker for a faster circuit, as net3d weights its arcs by capacity.

    Commit rate is in kbps and spans several orders of magnitude, so the width follows its
    logarithm: a 10 Gb link should read as fatter than a 10 Mb one, not five hundred times
    fatter. A circuit with no rate recorded gets the base width rather than none at all.

    The ceiling is set against the markers, not chosen for its own sake. The smallest site
    draws at about eight pixels across, so a link any fatter than this stops being a line
    between two places and starts hiding the places it joins.
    """
    rate = getattr(circuit, 'commit_rate', None)
    if not rate:
        return 1.0
    return min(1.0 + math.log10(rate / 1000 + 1) * 0.7, 3.5)
