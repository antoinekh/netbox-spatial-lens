"""
What colours a site on the world map.

The map coloured by site group and by nothing else, which made the group the only thing the
legend could filter by. A network engineer arrives at this zoom asking a different question
about as often: what is still planned, who owns it, which region is it in. Each of those is a
different colouring of the same set of points.

The rules under test are the ones the floor and the rack already keep. A site the colouring
has no answer for is grey, labelled and counted, never dropped. No two bands share a colour,
because a legend that says two things with one swatch has stopped explaining anything.
"""

from dcim.models import Region, Site, SiteGroup
from django.test import TestCase
from tenancy.models import Tenant

from netbox_spatial_lens.palette import NO_DATA, NODE, categorical_colour, distinct_colours
from netbox_spatial_lens.site_overlays import (
    SiteOverlay,
    get_site_overlay,
    get_site_overlays,
)


def make_site(name, **kwargs):
    return Site.objects.create(name=name, slug=name.lower().replace(' ', '-'), **kwargs)


class RegistryTest(TestCase):
    def test_the_four_builtins_are_selectable(self):
        # First, and in this order. Another installed plugin may register more after them.
        self.assertEqual(
            [o.name for o in get_site_overlays()][:4],
            ['group', 'status', 'tenant', 'region'],
        )

    def test_an_unknown_name_resolves_to_nothing(self):
        # A link carrying a colouring a later release removed must not 500 the map.
        self.assertIsNone(get_site_overlay('no-such-thing'))

    def test_a_colouring_that_raises_leaves_the_map_grey(self):
        # A broken colouring must not take the world map down. The points are still worth
        # looking at with one reading missing.
        def broken(sites):
            raise RuntimeError('boom')

        # Built rather than registered: the registry is process-wide, and a test that leaves
        # a fifth colouring in it changes what every later test sees on the toolbar.
        overlay = SiteOverlay(name='broken', label='Broken', fn=broken)
        site = make_site('Alpha')
        values = overlay.evaluate([site])
        self.assertFalse(values[site.pk].has_data)


class GroupTest(TestCase):
    def test_a_site_takes_its_group_colour(self):
        group = SiteGroup.objects.create(name='Branch Offices', slug='branch')
        site = make_site('Branch 1', group=group)
        value = get_site_overlay('group').evaluate([site])[site.pk]
        self.assertEqual(value.label, 'Branch Offices')
        self.assertEqual(value.colour, categorical_colour('Branch Offices'))

    def test_a_site_in_no_group_is_grey_and_counted(self):
        site = make_site('Loose')
        overlay = get_site_overlay('group')
        values = overlay.evaluate([site])
        self.assertFalse(values[site.pk].has_data)
        entry = next(e for e in overlay.legend_for(values.values()) if e.label == 'No data')
        self.assertEqual(entry.count, 1)
        self.assertEqual(entry.colour, NO_DATA)


class StatusTest(TestCase):
    def test_a_site_reads_the_colour_netbox_gives_its_status(self):
        site = make_site('Planned DC', status='planned')
        value = get_site_overlay('status').evaluate([site])[site.pk]
        self.assertEqual(value.label, site.get_status_display())

    def test_every_site_has_a_status_so_none_is_grey(self):
        # NetBox requires a status, so this colouring is the one that always accounts for
        # every point. If that ever changes, the grey band catches it rather than the map
        # quietly under-reporting.
        make_site('A', status='active')
        make_site('B', status='retired')
        overlay = get_site_overlay('status')
        values = overlay.evaluate(Site.objects.all())
        grey = next(e for e in overlay.legend_for(values.values()) if e.label == 'No data')
        self.assertEqual(grey.count, 0)

    def test_two_statuses_are_two_bands(self):
        make_site('A', status='active')
        make_site('B', status='planned')
        overlay = get_site_overlay('status')
        values = overlay.evaluate(Site.objects.all())
        named = [e for e in overlay.legend_for(values.values()) if e.count]
        self.assertEqual(len(named), 2)


class TenantTest(TestCase):
    def test_a_site_takes_its_tenant_colour(self):
        tenant = Tenant.objects.create(name='Dunder Mifflin', slug='dunder')
        site = make_site('Scranton', tenant=tenant)
        value = get_site_overlay('tenant').evaluate([site])[site.pk]
        self.assertEqual(value.label, 'Dunder Mifflin')
        self.assertEqual(value.colour, distinct_colours(['Dunder Mifflin'])['Dunder Mifflin'])

    def test_a_tenant_whose_name_hashes_onto_a_reserved_colour_is_moved_off_it(self):
        # The hash knows nothing about the map's permanent bands, so sooner or later a real
        # tenant lands on the provider purple. It has to be moved, or clicking the provider
        # networks picks that tenant's sites out with them.
        colliding = next(
            name for name in (f'Tenant {index}' for index in range(500)) if categorical_colour(name) == NODE['provider']
        )
        tenant = Tenant.objects.create(name=colliding, slug='colliding')
        site = make_site('Collides', tenant=tenant)
        value = get_site_overlay('tenant').evaluate([site])[site.pk]
        self.assertEqual(value.label, colliding)
        self.assertNotEqual(value.colour, NODE['provider'])

    def test_an_untenanted_site_is_grey_and_counted(self):
        site = make_site('Nobody')
        overlay = get_site_overlay('tenant')
        values = overlay.evaluate([site])
        entry = next(e for e in overlay.legend_for(values.values()) if e.label == 'No data')
        self.assertEqual(entry.count, 1)
        self.assertFalse(values[site.pk].has_data)


class RegionTest(TestCase):
    def test_a_site_takes_its_region_colour(self):
        region = Region.objects.create(name='Nord', slug='nord')
        site = make_site('Lille', region=region)
        value = get_site_overlay('region').evaluate([site])[site.pk]
        self.assertEqual(value.label, 'Nord')

    def test_a_site_in_no_region_is_grey_and_counted(self):
        site = make_site('Nowhere')
        overlay = get_site_overlay('region')
        values = overlay.evaluate([site])
        entry = next(e for e in overlay.legend_for(values.values()) if e.label == 'No data')
        self.assertEqual(entry.count, 1)
        self.assertFalse(values[site.pk].has_data)


class DistinctColoursTest(TestCase):
    """
    `categorical_colour` hashes a name onto one of eight colours, which keeps a name the same
    colour across restarts and workers but cannot promise distinctness. On a legend, two names
    sharing a swatch is the one failure that matters.
    """

    def test_a_name_keeps_its_hashed_colour_when_nothing_has_taken_it(self):
        self.assertEqual(distinct_colours(['Europe'])['Europe'], categorical_colour('Europe'))

    def test_no_two_names_share_a_colour(self):
        names = ['Europe', 'Branch Offices', 'Headquarters', 'Colo', 'Nord', 'Sud']
        colours = distinct_colours(names)
        self.assertEqual(len(set(colours.values())), len(names))

    def test_more_names_than_the_palette_holds_still_get_distinct_colours(self):
        # An estate filed under thirteen regions is ordinary, and the base ring holds eight.
        # Running out used to hand the ninth name a colour already spoken for, which put two
        # regions behind one swatch on a legend whose whole job is to tell them apart.
        names = [f'Region {index}' for index in range(24)]
        colours = distinct_colours(names)
        self.assertEqual(len(set(colours.values())), len(names))

    def test_no_band_is_given_the_colour_that_means_no_data(self):
        # Grey is reserved. A named band wearing it makes the one colour that has to keep
        # meaning "nobody recorded this" mean something else as well.
        names = [f'Region {index}' for index in range(24)]
        self.assertNotIn(NO_DATA, distinct_colours(names).values())

    def test_no_band_is_given_the_colour_that_means_provider_network(self):
        # The provider networks are a permanent band on this legend, in the plugin's own
        # purple. A region handed that purple shares a swatch with them, and because a band is
        # picked by its colour, clicking either one selects both.
        names = [f'Region {index}' for index in range(24)]
        self.assertNotIn(NODE['provider'], distinct_colours(names).values())

    def test_the_answer_does_not_depend_on_the_order_asked(self):
        # Two renders of one map must agree, and the second may walk the names in a different
        # order because they came out of a set.
        names = ['Europe', 'Branch Offices', 'Headquarters', 'Colo']
        self.assertEqual(distinct_colours(names), distinct_colours(list(reversed(names))))
