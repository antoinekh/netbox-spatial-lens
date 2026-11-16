"""
The floor's rack table and zoom, the list filters, and the pages carrying less text.
"""

import re

from dcim.models import Location
from django.urls import reverse

from netbox_spatial_lens.colouring import Level, registry
from netbox_spatial_lens.filtersets import FloorFilterSet, RackPlacementFilterSet
from netbox_spatial_lens.layout import build_layout, rack_rows
from netbox_spatial_lens.models import Floor, RackPlacement
from netbox_spatial_lens.tables import FloorTable
from netbox_spatial_lens.tests.base import make_device, make_floor, make_rack, place
from netbox_spatial_lens.tests.test_views import ViewTestCase


class FloorPageTest(ViewTestCase):
    def setUp(self):
        super().setUp()
        self.floor = make_floor(self.site)
        self.r2 = make_rack(self.site, name='R2', u_height=10)
        self.r10 = make_rack(self.site, name='R10', u_height=10)
        place(self.floor, self.r2, x=100, y=100)
        place(self.floor, self.r10, x=300, y=100)
        make_device(self.site, self.r2, 'srv', self.role, self.manufacturer, u_height=2)

    def _get(self, query=''):
        return self.client.get(f'{self.floor.get_absolute_url()}{query}')

    def test_the_plan_can_zoom(self):
        response = self._get()
        self.assertContains(response, 'data-lens-zoomable')
        self.assertContains(response, 'data-lens-zoom="in"')

    def test_the_racks_are_a_table_that_sorts(self):
        response = self._get('?colour=space')
        self.assertContains(response, 'data-lens-rack-table')
        self.assertContains(response, 'data-sort="number"')
        # The same band and name the plan carries, so the legend and the find box reach the rows.
        for row in response.context['rack_rows']:
            self.assertContains(response, f'<tr data-lens-filterable="racks rack-tags" data-band="{row.placed.band}"')

    def test_a_rack_is_one_tab_stop(self):
        # The link around a rack takes focus; the rack inside it used to take a second one.
        response = self._get()
        self.assertIsNone(re.search(r'<g class="lens-rack[^>]*tabindex', response.content.decode()))

    def test_the_gestures_are_behind_a_help_icon(self):
        response = self._get()
        self.assertContains(response, 'lens-help')
        self.assertNotContains(response, 'lens-hint')
        self.assertNotContains(response, 'colouring the racks')

    def test_the_site_thumbnails_do_not_zoom(self):
        response = self.client.get(reverse('dcim:site_lens', args=[self.site.pk]))
        self.assertNotContains(response, 'data-lens-zoomable')


class RackRowTest(ViewTestCase):
    def test_rows_are_in_natural_order_with_their_figures(self):
        floor = make_floor(self.site)
        r10 = make_rack(self.site, name='R10', u_height=10)
        r2 = make_rack(self.site, name='R2', u_height=10)
        place(floor, r10, x=100, y=100)
        place(floor, r2, x=300, y=100)
        make_device(self.site, r2, 'srv', self.role, self.manufacturer, u_height=5)

        rows = rack_rows(build_layout(floor, registry.get(Level.RACKS, 'space')))
        self.assertEqual([row.rack.name for row in rows], ['R2', 'R10'])
        self.assertEqual(rows[0].space_percent, 50)
        self.assertEqual(rows[0].free_units, 5)
        # No feed recorded is no answer, not zero.
        self.assertIsNone(rows[0].power_percent)


class ListFilterTest(ViewTestCase):
    def setUp(self):
        super().setUp()
        self.hall = Location.objects.create(site=self.site, name='Hall', slug='hall')
        self.site_floor = make_floor(self.site, name='Site floor')
        self.hall_floor = Floor.objects.create(name='Hall floor', location=self.hall, width=10, depth=8)

    def test_a_site_filter_finds_the_floors_bound_to_its_locations(self):
        floors = FloorFilterSet({'site_id': [self.site.pk]}, Floor.objects.all()).qs
        self.assertEqual(set(floors), {self.site_floor, self.hall_floor})

    def test_the_site_column_names_the_site_of_a_location_floor(self):
        table = FloorTable(Floor.objects.filter(pk=self.hall_floor.pk))
        self.assertIn(self.site.name, str(table.rows[0].get_cell('site')))

    def test_placements_filter_by_the_rack_site_and_location(self):
        rack = make_rack(self.site, name='Hall rack', location=self.hall)
        placement = RackPlacement.objects.create(floor=self.hall_floor, rack=rack, x=100, y=100)
        by_site = RackPlacementFilterSet({'site_id': [self.site.pk]}, RackPlacement.objects.all()).qs
        by_location = RackPlacementFilterSet({'location_id': [self.hall.pk]}, RackPlacement.objects.all()).qs
        self.assertEqual(list(by_site), [placement])
        self.assertEqual(list(by_location), [placement])

    def test_the_placement_list_shows_site_and_location(self):
        rack = make_rack(self.site, name='Hall rack', location=self.hall)
        RackPlacement.objects.create(floor=self.hall_floor, rack=rack, x=100, y=100)
        response = self.client.get(reverse('plugins:netbox_spatial_lens:rackplacement_list'))
        self.assertContains(response, self.hall.get_absolute_url())

    def test_the_layer_list_has_a_filter_form(self):
        response = self.client.get(reverse('plugins:netbox_spatial_lens:floorlayer_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context.get('filter_form'))


class EditorFootprintTest(ViewTestCase):
    def test_an_unplaced_rack_carries_its_footprint(self):
        floor = make_floor(self.site)
        make_rack(self.site, name='Wide', outer_width=800, outer_depth=1200, outer_unit='mm')
        response = self.client.get(reverse('plugins:netbox_spatial_lens:floor_layout', args=[floor.pk]))
        self.assertContains(response, 'data-width="80.0" data-depth="120.0"')


class WorldRendererTest(ViewTestCase):
    """
    The map is the MapLibre globe alone, with a message in its place until it is drawn.
    """

    def setUp(self):
        super().setUp()
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.save()

    def test_there_is_no_fallback_projection(self):
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertNotContains(response, 'lens-world-node')
        self.assertNotContains(response, 'data-lens-fallback')

    def test_the_map_has_a_message_until_it_is_drawn(self):
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertContains(response, 'data-lens-map-message')

    def test_the_finders_and_legends_do_not_need_the_map(self):
        # They are the page's use when the map cannot be drawn, so they are rendered server-side.
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertContains(response, 'data-lens-finder="sites"')
        self.assertContains(response, 'data-lens-filter="sites"')


class WorldTextTest(ViewTestCase):
    def test_the_status_line_does_not_repeat_the_totals(self):
        self.site.latitude, self.site.longitude = 51.5, -0.12
        self.site.save()
        response = self.client.get(reverse('plugins:netbox_spatial_lens:world'))
        self.assertContains(response, '<span class="text-muted lens-scale" data-lens-world-status></span>')
        self.assertContains(response, 'lens-help')


class TagFilterTest(ViewTestCase):
    """
    Racks on a floor and devices in a rack can be found by asset tag and narrowed by tag.
    """

    def setUp(self):
        super().setUp()
        from extras.models import Tag

        self.core = Tag.objects.create(name='Core', slug='core', color='f44336')
        self.edge = Tag.objects.create(name='Edge', slug='edge', color='2196f3')
        self.floor = make_floor(self.site)
        self.tagged = make_rack(self.site, name='R1', asset_tag='AT-0001')
        self.plain = make_rack(self.site, name='R2')
        self.tagged.tags.add(self.core, self.edge)
        self.plain.tags.add(self.core)
        place(self.floor, self.tagged, x=100, y=100)
        place(self.floor, self.plain, x=300, y=100)

    def test_tags_in_use_are_counted_in_name_order(self):
        from netbox_spatial_lens.tags import tags_in_use

        counts = [(item.tag.name, item.count) for item in tags_in_use([self.tagged, self.plain])]
        self.assertEqual(counts, [('Core', 2), ('Edge', 1)])

    def test_the_floor_offers_the_tags_of_its_racks(self):
        response = self.client.get(self.floor.get_absolute_url())
        self.assertContains(response, 'data-lens-finder="rack-tags"')
        self.assertContains(response, 'data-lens-pick="edge"')
        # The control is inert without its script, which the floor page did not load before it
        # had a finder of its own.
        self.assertContains(response, 'netbox_spatial_lens/finder.js')
        self.assertContains(response, 'data-tags="core edge "')
        self.assertContains(response, 'data-asset-tag="AT-0001"')

    def test_the_rack_table_shows_the_asset_tag_and_tags(self):
        response = self.client.get(self.floor.get_absolute_url())
        self.assertContains(response, '<td data-sort-value="AT-0001">AT-0001</td>')
        self.assertContains(response, 'background-color: #2196f3')

    def test_a_floor_with_no_tags_offers_no_tag_finder(self):
        self.tagged.tags.clear()
        self.plain.tags.clear()
        response = self.client.get(self.floor.get_absolute_url())
        self.assertNotContains(response, 'data-lens-finder="rack-tags"')

    def test_the_rack_offers_the_tags_of_its_devices(self):
        device = make_device(self.site, self.tagged, 'srv', self.role, self.manufacturer)
        device.asset_tag = 'AT-D-01'
        device.save()
        device.tags.add(self.edge)
        response = self.client.get(reverse('dcim:rack_lens', args=[self.tagged.pk]))
        self.assertContains(response, 'data-lens-finder="device-tags"')
        scene_device = response.context['rack3d_config']['scene']['devices'][0]
        self.assertEqual(scene_device['filters']['device-tags'], 'edge')
        self.assertEqual(scene_device['assetTag'], 'AT-D-01')
