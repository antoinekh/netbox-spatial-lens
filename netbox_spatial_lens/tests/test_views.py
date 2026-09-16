"""
The pages render, and they tell the truth about what they could not answer.
"""

import copy
from unittest import mock

from core.models import ObjectType
from dcim.models import Site
from django.conf import settings
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from users.models import User
from utilities.testing import create_test_user

from netbox_spatial_lens.models import Floor
from netbox_spatial_lens.overlays import RackValue
from netbox_spatial_lens.palette import NO_DATA, categorical_colour, distinct_colours
from netbox_spatial_lens.site_overlays import SiteOverlay, get_site_overlay, get_site_overlays
from netbox_spatial_lens.tests.base import (
    LensTestCase,
    make_device,
    make_floor,
    make_rack,
    place,
    power_feed,
)
from netbox_spatial_lens.world import build_world


def grant(user, model: str, actions=('view',), constraints=None) -> None:
    """
    One NetBox object permission, for a test that reads as a permission question.

    `model` is 'app_label.model'. `constraints` are NetBox's own object-level constraints, so
    a test can grant a user one rack of two and assert the other is nowhere on the page.
    """
    from users.models import ObjectPermission

    app, name = model.split('.')
    permission = ObjectPermission.objects.create(
        name=f'{model} {"-".join(actions)}', actions=list(actions), constraints=constraints or None
    )
    permission.users.add(user)
    permission.object_types.add(ObjectType.objects.get(app_label=app, model=name))


class ViewTestCase(LensTestCase):
    def setUp(self):
        self.user = create_test_user()
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)


class FloorViewTest(ViewTestCase):
    def setUp(self):
        super().setUp()
        self.floor = make_floor(self.site)
        self.rack = make_rack(self.site)
        place(self.floor, self.rack)

    def test_the_floor_renders(self):
        response = self.client.get(self.floor.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lens-floor')

    def test_a_floor_in_a_location_still_names_its_site(self):
        # A floor binds to a site or to a location, never both, so a room in a location had a
        # dash where its site should be. The site is not in doubt; only how the floor reached
        # it is.
        from dcim.models import Location

        location = Location.objects.create(site=self.site, name='Row 1', slug='row-1')
        floor = make_floor(self.site, name='Row 1 floor')
        floor.site, floor.location = None, location
        floor.save()

        response = self.client.get(floor.get_absolute_url())
        self.assertContains(response, self.site.name)

    def test_an_unknown_overlay_falls_back_rather_than_failing(self):
        # A link carrying an overlay a later release removed should still open the floor.
        response = self.client.get(f'{self.floor.get_absolute_url()}?overlay=no-such-thing')
        self.assertEqual(response.status_code, 200)

    def test_a_floor_with_no_data_says_so(self):
        # The honesty rule: a room of grey must read as "nobody recorded this", never as a
        # clean bill of health. The count sits in the legend beside the grey swatch.
        response = self.client.get(f'{self.floor.get_absolute_url()}?overlay=cooling')
        self.assertContains(response, 'No data')
        self.assertContains(response, 'lens-legend__count')

    def test_a_rack_links_inward_to_its_lens_tab(self):
        response = self.client.get(self.floor.get_absolute_url())
        self.assertContains(response, f'/dcim/racks/{self.rack.pk}/spatial-lens/')

    def test_the_editor_renders(self):
        response = self.client.get(reverse('plugins:netbox_spatial_lens:floor_layout', args=[self.floor.pk]))
        self.assertEqual(response.status_code, 200)
        # Without a readable CSRF token every save comes back 403, because NetBox sets
        # CSRF_COOKIE_HTTPONLY and the script cannot read the cookie.
        self.assertContains(response, 'csrfmiddlewaretoken')


class RackViewTest(ViewTestCase):
    def test_the_rack_can_be_looked_at_from_the_front_and_the_rear(self):
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer, interfaces=2)
        response = self.client.get(reverse('dcim:rack_lens', args=[rack.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-lens-view="front"')
        self.assertContains(response, 'data-lens-view="rear"')

    def test_an_empty_rack_does_not_break(self):
        rack = make_rack(self.site, u_height=10)
        response = self.client.get(reverse('dcim:rack_lens', args=[rack.pk]))
        self.assertEqual(response.status_code, 200)

    def test_a_rack_with_devices_offers_a_way_to_find_one(self):
        # The same box the floor has. Reading a name off a 48U cabinet by eye is the same
        # problem as reading one off a room of fifty cabinets.
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer)
        response = self.client.get(reverse('dcim:rack_lens', args=[rack.pk]))
        self.assertContains(response, 'data-lens-find')
        self.assertContains(response, 'Find a device')

    def test_an_empty_rack_offers_no_search(self):
        # Nothing to search, so the box would be a control that cannot do anything.
        rack = make_rack(self.site, u_height=10)
        response = self.client.get(reverse('dcim:rack_lens', args=[rack.pk]))
        self.assertNotContains(response, 'data-lens-find')

    def test_a_device_carries_its_name_for_the_search(self):
        # The search reads the name from the scene, as the floor's reads it off the drawing,
        # rather than the server filtering and re-rendering: the page holds every device it can
        # show.
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer)
        response = self.client.get(reverse('dcim:rack_lens', args=[rack.pk]))
        self.assertEqual([d['label'] for d in response.context['rack3d_config']['scene']['devices']], ['srv'])


class RackCablingFinderTest(ViewTestCase):
    """
    The cabling list behind a filter, the way the map's site and circuit lists are.

    A top-of-rack switch puts thirty-odd rows in the cabling card, which is a list you scroll
    rather than one you read. The same control the map uses answers it: type to reach one, tick
    to narrow the drawing to a handful.
    """

    def setUp(self):
        super().setUp()
        self.rack = make_rack(self.site, name='R1', u_height=10)
        self.switch = make_device(
            self.site, self.rack, 'tor', self.switch_role, self.manufacturer, position=10, interfaces=2
        )
        self.server = make_device(self.site, self.rack, 'srv', self.role, self.manufacturer, position=1, interfaces=2)
        from netbox_spatial_lens.tests.base import cable

        cable(self.server.interfaces.first(), self.switch.interfaces.first())

    def _get(self):
        return self.client.get(reverse('dcim:rack_lens', args=[self.rack.pk]))

    def test_the_cabling_list_is_a_finder(self):
        response = self._get()
        self.assertContains(response, 'data-lens-finder="cables"')
        self.assertContains(response, 'data-lens-finder-search')

    def test_every_cable_is_a_row_that_can_be_ticked(self):
        response = self._get()
        cable_id = self.rack.devices.first().interfaces.first().cable_id
        self.assertContains(response, f'data-lens-pick="{cable_id}"')

    def test_a_row_names_both_ends_so_it_can_be_searched_for(self):
        response = self._get()
        self.assertContains(response, 'data-lens-name')
        self.assertContains(response, 'srv')
        self.assertContains(response, 'tor')

    def test_the_whole_list_is_not_rendered_under_the_card(self):
        # The point of the finder. A production rack has hundreds of cables, and printing them
        # all under the card is the long list it was meant to replace.
        response = self._get()
        self.assertNotContains(response, 'Leaving the rack')
        self.assertNotContains(response, 'Within the rack')

    def test_the_card_says_where_the_cables_are(self):
        # An empty card reads as "no cabling", which is the one thing it must not say when
        # there are thirty-six of them behind a button.
        response = self._get()
        self.assertContains(response, 'data-lens-cabling="rack"')
        self.assertContains(response, 'Find a cable')

    def test_a_device_still_carries_its_own_cabling(self):
        # Selecting a device narrows the card to that device, which is a short list and stays.
        response = self._get()
        self.assertContains(response, f'data-lens-cabling="{self.switch.pk}"')

    def test_a_rack_with_no_cabling_offers_no_finder(self):
        bare = make_rack(self.site, name='R2', u_height=10)
        response = self.client.get(reverse('dcim:rack_lens', args=[bare.pk]))
        self.assertNotContains(response, 'data-lens-finder="cables"')


class SiteLensViewTest(ViewTestCase):
    """
    The level between the world and a floor.

    A site is one room often enough that the map used to go straight to a floor, which quietly
    told anyone with several rooms that they had one. The site names all of them.
    """

    def setUp(self):
        super().setUp()
        from dcim.models import Location

        self.row = Location.objects.create(site=self.site, name='Row 1', slug='row-1')
        self.hall = make_floor(self.site, name='Hall')
        self.row_floor = make_floor(self.site, name='Row 1 floor')
        self.row_floor.site, self.row_floor.location = None, self.row
        self.row_floor.save()

    def _url(self):
        return reverse('dcim:site_lens', args=[self.site.pk])

    def test_it_names_every_room_in_the_site(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hall')
        self.assertContains(response, 'Row 1 floor')

    def test_a_room_in_another_site_is_not_listed(self):
        other = Site.objects.create(name='Elsewhere', slug='elsewhere')
        make_floor(other, name='Not mine')
        self.assertNotContains(self.client.get(self._url()), 'Not mine')

    def test_a_rack_on_no_floor_is_reported_rather_than_dropped(self):
        make_rack(self.site, name='Homeless')
        response = self.client.get(self._url())
        self.assertContains(response, 'Homeless')

    def test_a_room_the_reader_may_not_see_is_not_listed(self):
        self.user.is_superuser = False
        self.user.save()
        grant(self.user, 'netbox_spatial_lens.floor', constraints={'name': 'Hall'})
        grant(self.user, 'dcim.site')
        response = self.client.get(self._url())
        self.assertContains(response, 'Hall')
        self.assertNotContains(response, 'Row 1 floor')

    def test_the_cost_does_not_grow_with_the_rooms(self):
        # Each room drawn on its own repeated the placement, device count, space and power
        # queries, so a site of twenty rooms cost twenty times one. Every room here has a rack
        # with a feed, so the power walk has something to read in each of them.
        def cost(rooms):
            site = Site.objects.create(name=f'{rooms} rooms', slug=f'rooms-{rooms}')
            for n in range(rooms):
                rack = make_rack(site, name=f'R{rooms}-{n}')
                power_feed(rack, name=f'feed-{rooms}-{n}')
                place(make_floor(site, name=f'Room {n}'), rack)
            url = reverse('dcim:site_lens', args=[site.pk])
            self.client.get(url)
            with CaptureQueriesContext(connection) as captured:
                self.client.get(url)
            return len(captured.captured_queries)

        self.assertEqual(cost(4), cost(1))


class SiteLinkTest(ViewTestCase):
    """
    Where a marker on the world map takes you.

    It used to be `dict(site_id, floor_pk)`, so a site with two rooms lost one of them to the
    dictionary, and a room bound to a location was not in the mapping at all.
    """

    def setUp(self):
        super().setUp()
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.save()

    def _url_for_site(self):
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        node = next(n for n in response.context['world'].nodes if n.object_id == self.site.pk)
        return node.url

    def test_one_room_goes_straight_to_it(self):
        floor = make_floor(self.site, name='Hall')
        self.assertEqual(self._url_for_site(), floor.get_absolute_url())

    def test_a_room_bound_to_a_location_is_still_reached(self):
        from dcim.models import Location

        row = Location.objects.create(site=self.site, name='Row 1', slug='row-1')
        floor = make_floor(self.site, name='Row 1 floor')
        floor.site, floor.location = None, row
        floor.save()
        self.assertEqual(self._url_for_site(), floor.get_absolute_url())

    def test_several_rooms_go_to_the_site_rather_than_to_one_of_them(self):
        make_floor(self.site, name='Hall')
        make_floor(self.site, name='Annexe')
        self.assertEqual(self._url_for_site(), reverse('dcim:site_lens', args=[self.site.pk]))

    def test_no_room_at_all_goes_to_the_site_lens_tab(self):
        # The Spatial Lens tab lists the site's racks and offers to add a floor; NetBox's own site page
        # is one tab away from it.
        self.assertEqual(self._url_for_site(), reverse('dcim:site_lens', args=[self.site.pk]))


class WorldViewTest(ViewTestCase):
    def test_it_renders_with_no_geocoded_sites(self):
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No site has coordinates recorded')

    def test_a_geocoded_site_appears(self):
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.save()
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertContains(response, self.site.name)

    def test_the_map_offers_every_colouring(self):
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.save()
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        for overlay in get_site_overlays():
            self.assertContains(response, f'?overlay={overlay.name}')

    def test_the_finders_carry_every_site_and_a_way_to_filter_them(self):
        # The lists are behind a button now, so the page must still hold every row: the filter
        # and the ticks work on what is already there rather than asking the server again.
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.save()
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertContains(response, 'data-lens-finder="sites"')
        self.assertContains(response, 'data-lens-finder="circuits"')
        self.assertContains(response, 'data-lens-finder-search')
        self.assertContains(response, f'data-lens-name="{self.site.name}"')

    def test_a_colouring_named_in_the_url_is_the_one_drawn(self):
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.status = 'planned'
        self.site.save()
        response = self.client.get(f'{reverse("plugins:netbox_spatial_lens:world")}?overlay=status')
        self.assertEqual(response.context['overlay'].name, 'status')
        self.assertContains(response, self.site.get_status_display())

    def test_an_unknown_colouring_falls_back_rather_than_failing(self):
        # A link carrying a colouring a later release removed should still open the map.
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.save()
        response = self.client.get(f'{reverse("plugins:netbox_spatial_lens:world")}?overlay=no-such-thing')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['overlay'].name, 'group')

    def test_a_default_no_colouring_answers_to_falls_back_to_the_first_registered(self):
        # The map used to fall back to the group inside the builder only, so it was drawn by
        # group while the page named no colouring and no button was active.
        config = copy.deepcopy(settings.PLUGINS_CONFIG)
        config['netbox_spatial_lens']['default_site_overlay'] = 'no-such-default'
        with override_settings(PLUGINS_CONFIG=config):
            response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertEqual(response.context['overlay'].name, get_site_overlays()[0].name)

    def test_with_the_default_colouring_switched_off_the_map_uses_the_first_left(self):
        # `enable_builtin_site_overlays: ['status']` with the default left at 'group': the map
        # used to be drawn by nothing while Status sat on the toolbar.
        from netbox_spatial_lens import site_overlays

        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.status = 'planned'
        self.site.save()
        with mock.patch.dict(site_overlays.registry._items, clear=True):
            site_overlays.register_builtin_site_overlays(['status'])
            response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
            node = next(n for n in build_world().nodes if n.object_id == self.site.pk)
        self.assertEqual(response.context['overlay'].name, 'status')
        self.assertEqual(node.band, self.site.get_status_display())


class TraceViewTest(ViewTestCase):
    def test_an_unknown_termination_is_a_404_not_a_500(self):
        response = self.client.get(reverse('plugins:netbox_spatial_lens:trace', args=['dcim.interface', 10_000_000]))
        self.assertEqual(response.status_code, 404)

    def test_a_real_termination_returns_hops(self):
        rack = make_rack(self.site, u_height=10)
        device = make_device(self.site, rack, 'srv', self.role, self.manufacturer, interfaces=1)
        response = self.client.get(
            reverse(
                'plugins:netbox_spatial_lens:trace',
                args=['dcim.interface', device.interfaces.first().pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('hops', response.json())

    def test_it_refuses_a_user_who_cannot_read_cables(self):
        plain = User.objects.create_user('plain', password='x')
        self.client.force_login(plain)
        response = self.client.get(reverse('plugins:netbox_spatial_lens:trace', args=['dcim.interface', 1]))
        self.assertEqual(response.status_code, 403)


class BulkActionTest(ViewTestCase):
    """
    Every bulk action the list offers must actually be routed.

    NetBox's list template renders the bulk edit and delete buttons whether or not the plugin
    routes them, and an unrouted one comes out as formaction="None". Clicking it posts to
    /floors/None and answers "the requested page does not exist", which looks like a broken
    delete rather than a missing view.
    """

    def setUp(self):
        super().setUp()
        self.floor = make_floor(self.site)
        self.rack = make_rack(self.site)
        self.placement = place(self.floor, self.rack)

    def test_no_list_offers_an_unrouted_action(self):
        for url in (
            reverse('plugins:netbox_spatial_lens:floor_list'),
            reverse('plugins:netbox_spatial_lens:rackplacement_list'),
        ):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), 'formaction="None"')

    def test_the_bulk_routes_resolve(self):
        for name in (
            'floor_bulk_edit',
            'floor_bulk_delete',
            'rackplacement_bulk_edit',
            'rackplacement_bulk_delete',
        ):
            with self.subTest(name=name):
                self.assertTrue(reverse(f'plugins:netbox_spatial_lens:{name}'))

    def test_bulk_delete_removes_the_floors(self):
        response = self.client.post(
            reverse('plugins:netbox_spatial_lens:floor_bulk_delete'),
            {'pk': [self.floor.pk], 'confirm': True, '_confirm': True},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Floor.objects.filter(pk=self.floor.pk).exists())

    def test_deleting_a_floor_lands_somewhere_that_exists(self):
        # The symptom that started this: the redirect after a delete must not be a 404.
        response = self.client.post(
            reverse('plugins:netbox_spatial_lens:floor_delete', args=[self.floor.pk]),
            {'confirm': True},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'does not exist')


class WorldColouringTest(LensTestCase):
    """
    Sites coloured by group, status, tenant or region.

    The legend on this map is also its filter, so whatever the map cannot colour by is a
    question nobody can ask of it. The rules the tests guard: every point on the map is
    accounted for by the legend, and no colour is explained twice.
    """

    def test_the_map_colours_by_group_when_no_colouring_is_named(self):
        from dcim.models import SiteGroup

        group = SiteGroup.objects.create(name='Branch Offices', slug='branch')
        site = Site.objects.create(name='Branch 1', slug='branch-1', group=group, latitude=51.5, longitude=-0.1)
        node = next(n for n in build_world().nodes if n.object_id == site.pk)
        self.assertEqual(node.band, 'Branch Offices')
        self.assertEqual(node.colour, categorical_colour('Branch Offices'))

    def test_the_hover_card_names_what_the_colouring_says(self):
        site = Site.objects.create(name='Owned', slug='owned', latitude=51.5, longitude=-0.1)

        def owner(sites):
            return {s.pk: RackValue('#3f7fbf', 'Paid by Acme', 'acme') for s in sites}

        world = build_world(overlay=SiteOverlay('owner', 'Owner', owner))
        node = next(n for n in world.nodes if n.object_id == site.pk)
        self.assertEqual(node.facts[0], ('Owner', 'Paid by Acme'))

    def test_coloured_by_status_the_status_is_not_named_twice(self):
        # The status is the card's badge already.
        site = Site.objects.create(name='Live', slug='live', latitude=51.5, longitude=-0.1)
        node = next(n for n in build_world(overlay=get_site_overlay('status')).nodes if n.object_id == site.pk)
        self.assertNotIn(('Status', site.get_status_display()), node.facts)

    def test_coloured_by_group_the_group_is_not_named_twice(self):
        from dcim.models import SiteGroup

        group = SiteGroup.objects.create(name='Europe', slug='europe')
        site = Site.objects.create(name='Grouped', slug='grouped', group=group, latitude=51.5, longitude=-0.1)
        node = next(n for n in build_world(overlay=get_site_overlay('group')).nodes if n.object_id == site.pk)
        self.assertEqual([fact for fact in node.facts if fact[1] == 'Europe'], [('Group', 'Europe')])

    def test_the_map_colours_by_the_colouring_it_is_given(self):
        site = Site.objects.create(name='Planned', slug='planned', status='planned', latitude=51.5, longitude=-0.1)
        world = build_world(overlay=get_site_overlay('status'))
        node = next(n for n in world.nodes if n.object_id == site.pk)
        self.assertEqual(node.band, site.get_status_display())

    def test_a_site_the_colouring_cannot_answer_for_is_grey_and_counted(self):
        Site.objects.create(name='Loose', slug='loose', latitude=51.5, longitude=-0.1)
        world = build_world(overlay=get_site_overlay('tenant'))
        entry = next(e for e in world.legend if e.label == 'No data')
        self.assertEqual(entry.count, 1)
        self.assertEqual(entry.colour, NO_DATA)

    def test_no_two_bands_share_a_colour(self):
        from dcim.models import SiteGroup

        for index, name in enumerate(('Europe', 'Branch Offices', 'Headquarters', 'Colo')):
            group = SiteGroup.objects.create(name=name, slug=f'g{index}')
            Site.objects.create(
                name=f'S{index}',
                slug=f's{index}',
                group=group,
                latitude=50 + index,
                longitude=index,
            )
        legend = [e for e in build_world().legend if e.count]
        self.assertEqual(len({e.colour for e in legend}), len(legend))

    def test_the_whole_legend_is_free_of_repeated_colours(self):
        # A band is picked by its colour, so two bands sharing one are selected together: the
        # reader clicks New York and gets the provider networks as well. The permanent bands,
        # the no-data grey and the provider purple, are as much a part of that as the named
        # ones, which is why this is asserted over the finished legend rather than the
        # colouring's own output.
        from dcim.models import Region

        for index in range(12):
            region = Region.objects.create(name=f'R{index}', slug=f'r{index}')
            Site.objects.create(
                name=f'S{index}',
                slug=f's{index}',
                region=region,
                latitude=40 + index,
                longitude=index,
            )
        legend = build_world(overlay=get_site_overlay('region')).legend
        colours = [e.colour for e in legend]
        self.assertEqual(len(set(colours)), len(colours))

    def test_the_legend_accounts_for_every_site_under_every_colouring(self):
        from dcim.models import SiteGroup

        group = SiteGroup.objects.create(name='Europe', slug='europe')
        Site.objects.create(name='A', slug='a', group=group, latitude=51.5, longitude=-0.1)
        Site.objects.create(name='B', slug='b', latitude=48.9, longitude=2.3)
        for overlay in get_site_overlays():
            world = build_world(overlay=overlay)
            self.assertEqual(
                sum(e.count for e in world.legend),
                len(world.site_nodes),
                f'the {overlay.name} legend loses a site',
            )


class WorldCircuitTest(LensTestCase):
    """
    Circuits coloured by their provider, and the legend that narrows to one.

    The map could colour its sites four ways and its circuits not at all, so "which of these
    is Level 3" was a question the drawing held the answer to and could not be asked.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other = Site.objects.create(name='Far', slug='far', latitude=48.9, longitude=2.3)
        cls.site.latitude, cls.site.longitude = 51.5, -0.1
        cls.site.save()

    def circuit(self, cid, provider_name):
        from circuits.models import Circuit, CircuitTermination, CircuitType, Provider

        kind, _ = CircuitType.objects.get_or_create(name='Transit', slug='transit')
        provider = None
        if provider_name:
            provider, _ = Provider.objects.get_or_create(
                name=provider_name, slug=provider_name.lower().replace(' ', '-')
            )
        circuit = Circuit.objects.create(cid=cid, provider=provider, type=kind, status='active')
        CircuitTermination.objects.create(circuit=circuit, term_side='A', termination=self.site)
        CircuitTermination.objects.create(circuit=circuit, term_side='Z', termination=self.other)
        return circuit

    def test_a_circuit_takes_its_provider_colour(self):
        self.circuit('CID-1', 'Level 3')
        link = build_world().links[0]
        self.assertEqual(link.colour, distinct_colours(['Level 3'])['Level 3'])

    def test_two_providers_are_two_bands(self):
        self.circuit('CID-1', 'Level 3')
        self.circuit('CID-2', 'CenturyLink')
        world = build_world()
        named = [e for e in world.providers if e.count]
        self.assertEqual(len(named), 2)
        self.assertEqual(len({e.colour for e in named}), 2)

    def test_every_circuit_has_a_provider_so_none_is_grey(self):
        # NetBox makes the provider mandatory, so this legend is the one that always accounts
        # for every line. The grey band is kept at zero rather than dropped: if that ever
        # changes, an unattributed circuit shows up here instead of quietly wearing a colour
        # that means somebody else's network.
        from django.db.utils import IntegrityError

        self.circuit('CID-1', 'Level 3')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.circuit('CID-2', None)

        world = build_world()
        grey = next(e for e in world.providers if e.label == 'No data')
        self.assertEqual(grey.count, 0)
        self.assertEqual(grey.colour, NO_DATA)

    def test_the_legend_accounts_for_every_circuit_drawn(self):
        self.circuit('CID-1', 'Level 3')
        self.circuit('CID-2', 'Level 3')
        self.circuit('CID-3', 'CenturyLink')
        world = build_world()
        self.assertEqual(sum(e.count for e in world.providers), len(world.links))

    def test_the_legend_swatch_matches_the_line_it_explains(self):
        # The colours were chosen twice, once over every circuit and once over the drawn ones,
        # and the two sets need not agree: a provider whose only circuit is dropped changes the
        # answer for everybody after it. The legend then names a colour nothing on the map
        # wears, and picking that band hides every line and shows none.
        drawn = self.circuit('CID-1', 'Level 3')
        self.circuit('CID-2', 'CenturyLink')
        # A third circuit that cannot be drawn: one end is a site with no coordinates.
        from circuits.models import Circuit, CircuitTermination, CircuitType, Provider

        nowhere = Site.objects.create(name='Nowhere', slug='nowhere')
        kind = CircuitType.objects.get(slug='transit')
        provider, _ = Provider.objects.get_or_create(name='Undrawn', slug='undrawn')
        undrawn = Circuit.objects.create(cid='CID-3', provider=provider, type=kind, status='active')
        CircuitTermination.objects.create(circuit=undrawn, term_side='A', termination=self.site)
        CircuitTermination.objects.create(circuit=undrawn, term_side='Z', termination=nowhere)

        world = build_world()
        drawn_colours = {link.circuit.provider.name: link.colour for link in world.links}
        for entry in world.providers:
            if entry.label in drawn_colours:
                self.assertEqual(entry.colour, drawn_colours[entry.label], f'{entry.label} swatch')
        self.assertIn(drawn.provider.name, drawn_colours)

    def test_a_user_who_may_not_see_circuits_gets_none_of_them(self):
        # The map already restricts its sites. It read every circuit in the database, so a
        # user with no circuit permission still saw the CIDs, the providers and the commit
        # rates between the sites they were allowed to see.
        from circuits.models import Circuit

        self.circuit('CID-1', 'Level 3')
        self.assertEqual(len(build_world().links), 1)

        none = Circuit.objects.none()
        self.assertEqual(build_world(circuits=none).links, [])
        self.assertEqual(build_world(circuits=none).providers, [])

    def test_an_estate_with_no_circuits_has_no_provider_legend(self):
        self.assertEqual(build_world().providers, [])

    def test_the_two_legends_are_separate_groups(self):
        # Picking a provider must not disturb the site colouring, and the other way round. They
        # answer different questions and the page holds both at once.
        self.circuit('CID-1', 'Level 3')
        world = build_world()
        self.assertNotEqual(world.legend, world.providers)


class WorldStatsTest(TestCase):
    """
    The strip above the map: what the estate is, before you read where it is.

    Built on a bare TestCase rather than the shared fixture, because these figures count every
    site the caller can see and a fixture site would sit in the totals unmentioned.
    """

    def test_an_empty_map_has_no_strip(self):
        self.assertEqual(build_world().stats, [])

    def test_the_strip_counts_the_whole_estate(self):
        Site.objects.create(name='A', slug='a', latitude=51.5, longitude=-0.1)
        Site.objects.create(name='B', slug='b', latitude=48.9, longitude=2.3)
        sites = next(s for s in build_world().stats if s.label == 'Sites')
        self.assertEqual(sites.value, '2')

    def test_the_sites_figure_does_not_argue_with_its_own_caption(self):
        # "Sites 1, 1 without coordinates" reads as an estate of one. The count has to be the
        # number the caption is subtracting from.
        Site.objects.create(name='A', slug='a', latitude=51.5, longitude=-0.1)
        Site.objects.create(name='Nowhere', slug='nowhere')
        sites = next(s for s in build_world().stats if s.label == 'Sites')
        self.assertEqual(sites.value, '2')
        self.assertIn('1 without coordinates', sites.detail)

    def test_the_strip_says_how_many_sites_it_could_not_place(self):
        # The honesty rule at this zoom: an estate half of which has no coordinates must not
        # read as an estate half its size.
        Site.objects.create(name='A', slug='a', latitude=51.5, longitude=-0.1)
        Site.objects.create(name='Nowhere', slug='nowhere')
        sites = next(s for s in build_world().stats if s.label == 'Sites')
        self.assertIn('1 without coordinates', sites.detail)

    def test_the_strip_totals_the_racks_and_devices(self):
        site = Site.objects.create(name='A', slug='a', latitude=51.5, longitude=-0.1)
        make_rack(site, name='R1')
        make_rack(site, name='R2')
        stats = {s.label: s.value for s in build_world().stats}
        self.assertEqual(stats['Racks'], '2')


class PermissionTest(TestCase):
    """
    The plugin draws what the reader may see, and nothing else.

    A drawing is a query result with a picture around it. NetBox restricts the querysets its
    own views are built on, but a floor plan reads racks, a rack reads devices, and a map reads
    circuits, none of which is the view's own queryset. Left alone they are read with the
    plugin's permissions rather than the reader's, and the picture becomes a way to see objects
    the rest of NetBox refuses to show.
    """

    def setUp(self):
        self.site = Site.objects.create(name='Site', slug='site')
        self.other = Site.objects.create(name='Other', slug='other')
        self.floor = make_floor(self.site, width=20, depth=20)
        self.mine = make_rack(self.site, name='MINE')
        self.hidden = make_rack(self.site, name='HIDDEN')
        place(self.floor, self.mine, x=100, y=100)
        place(self.floor, self.hidden, x=400, y=100)

        self.user = create_test_user()
        self.client.force_login(self.user)

        # Everything the plugin's own pages need, and racks limited to one of the two.
        grant(self.user, 'netbox_spatial_lens.floor')
        grant(self.user, 'netbox_spatial_lens.rackplacement')
        grant(self.user, 'dcim.rack', constraints={'name': 'MINE'})
        grant(self.user, 'dcim.site')

    def test_a_floor_draws_only_the_racks_the_reader_may_see(self):
        response = self.client.get(self.floor.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'MINE')
        self.assertNotContains(response, 'HIDDEN')

    def test_the_floor_counts_only_the_racks_the_reader_may_see(self):
        # The stat strip and the legend are read as a tally of the room. Counting a cabinet the
        # reader cannot see makes the tally disagree with the plan beside it.
        response = self.client.get(self.floor.get_absolute_url())
        racks = next(s for s in response.context['stats'] if s.label == 'Racks')
        self.assertEqual(racks.value, '1')
