"""
The rack in 3D: where each device box sits, which images it wears, and where its cables run.
"""

from dcim.models import Device, PowerPort
from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from netbox_spatial_lens.cabling import RESTRICTED_LABEL
from netbox_spatial_lens.elevation import build_elevation
from netbox_spatial_lens.scene import (
    EXIT_RISE_MM,
    LEFT,
    PLINTH_MM,
    RIGHT,
    UNIT_MM,
    build_scene,
)
from netbox_spatial_lens.tests.base import LensTestCase, cable, make_device, make_rack
from netbox_spatial_lens.tests.test_views import ViewTestCase, grant


def _scene(rack, devices_queryset=None):
    return build_scene(build_elevation(rack, devices_queryset=devices_queryset))


def _device(scene, device):
    return next(d for d in scene.devices if d.device.pk == device.pk)


class DeviceBoxTest(LensTestCase):
    def setUp(self):
        self.rack = make_rack(self.site, u_height=10, outer_width=600, outer_depth=1000, outer_unit='mm')

    def test_u1_sits_on_the_plinth(self):
        device = make_device(self.site, self.rack, 'low', self.role, self.manufacturer, position=1)
        box = _device(_scene(self.rack), device).box
        self.assertAlmostEqual(box.y, PLINTH_MM + UNIT_MM / 2)

    def test_a_tall_device_is_as_tall_as_its_units(self):
        device = make_device(self.site, self.rack, 'tall', self.role, self.manufacturer, position=3, u_height=2)
        box = _device(_scene(self.rack), device).box
        self.assertAlmostEqual(box.y, PLINTH_MM + 3 * UNIT_MM)
        self.assertAlmostEqual(box.h, 2 * UNIT_MM, delta=1.5)

    def test_desc_units_puts_u1_at_the_top(self):
        # The elevation already inverts a rack numbered from the top; the scene converts its
        # answer rather than placing the unit again, so the two cannot disagree.
        rack = make_rack(self.site, name='Desc', u_height=10, desc_units=True)
        device = make_device(self.site, rack, 'top', self.role, self.manufacturer, position=1)
        box = _device(_scene(rack), device).box
        self.assertAlmostEqual(box.y, PLINTH_MM + 9.5 * UNIT_MM)

    def test_a_19_inch_rack_takes_a_19_inch_faceplate(self):
        device = make_device(self.site, self.rack, 'wide', self.role, self.manufacturer)
        self.assertAlmostEqual(_device(_scene(self.rack), device).box.w, 482.6)

    def test_a_full_depth_device_spans_the_rails(self):
        device = make_device(self.site, self.rack, 'deep', self.role, self.manufacturer, full_depth=True)
        scene = _scene(self.rack)
        box = _device(scene, device).box
        self.assertAlmostEqual(box.z + box.d / 2, scene.front_rail_z)
        self.assertAlmostEqual(box.rear_z, scene.rear_rail_z)

    def test_a_half_depth_device_on_the_rear_hangs_off_the_rear_rail(self):
        device = make_device(self.site, self.rack, 'back', self.role, self.manufacturer, full_depth=False, face='rear')
        scene = _scene(self.rack)
        placed = _device(scene, device)
        self.assertEqual(placed.facing, 'rear')
        self.assertAlmostEqual(placed.box.rear_z, scene.rear_rail_z)
        self.assertAlmostEqual(placed.box.d, (scene.front_rail_z - scene.rear_rail_z) / 2)

    def test_a_full_depth_device_is_in_the_scene_once(self):
        make_device(self.site, self.rack, 'once', self.role, self.manufacturer, full_depth=True)
        self.assertEqual(len(_scene(self.rack).devices), 1)

    def test_the_images_are_the_device_types(self):
        device = make_device(self.site, self.rack, 'pictured', self.role, self.manufacturer)
        device_type = device.device_type
        device_type.front_image.name = 'devicetype-images/pictured.front.png'
        device_type.save()
        placed = _device(_scene(self.rack), device)
        self.assertTrue(placed.front_image.endswith('devicetype-images/pictured.front.png'))
        self.assertEqual(placed.rear_image, '')

    def test_it_carries_the_ids_the_finders_narrow_by(self):
        device = make_device(self.site, self.rack, 'tagged', self.role, self.manufacturer)
        device.tags.add('blue', 'core')
        filters = _device(_scene(self.rack), device).filters
        self.assertEqual(sorted(filters['device-tags'].split()), ['blue', 'core'])

    def test_the_hover_card_names_what_the_colouring_says_first(self):
        from netbox_spatial_lens.device_overlays import get_device_overlay

        device = make_device(self.site, self.rack, 'coloured', self.role, self.manufacturer)
        elevation = build_elevation(self.rack)
        mounted = elevation.devices[0]
        mounted.value = get_device_overlay('role').evaluate(elevation.devices)[device.pk]
        facts = _device(build_scene(elevation), device).facts
        self.assertEqual(facts[0], self.role.name)

    def test_a_device_the_colouring_has_no_answer_for_adds_no_line(self):
        device = make_device(self.site, self.rack, 'plain', self.role, self.manufacturer)
        self.assertEqual(_device(_scene(self.rack), device).facts[0], str(device.device_type))

    def test_the_json_names_the_device(self):
        device = make_device(self.site, self.rack, 'named', self.role, self.manufacturer)
        entry = _scene(self.rack).as_json()['devices'][0]
        self.assertEqual(entry['id'], device.pk)
        self.assertEqual(entry['label'], 'named')
        self.assertEqual(entry['url'], device.get_absolute_url())
        self.assertEqual(len(entry['box']), 6)


class CableRouteTest(LensTestCase):
    def setUp(self):
        self.rack = make_rack(self.site, u_height=12)
        self.switch = make_device(
            self.site, self.rack, 'tor', self.switch_role, self.manufacturer, position=12, interfaces=4
        )
        self.server = make_device(
            self.site, self.rack, 'srv', self.role, self.manufacturer, position=2, interfaces=2, power_ports=1
        )
        self.pdu = make_device(self.site, self.rack, 'pdu', self.role, self.manufacturer, position=1, outlets=1)
        cable(self.server.interfaces.get(name='eth0'), self.switch.interfaces.get(name='eth0'))
        cable(self.server.interfaces.get(name='eth1'), self.switch.interfaces.get(name='eth1'))
        cable(PowerPort.objects.get(device=self.server), self.pdu.poweroutlets.first())

    def _cables(self, scene=None):
        return (scene or _scene(self.rack)).cables

    def test_every_cable_is_routed(self):
        self.assertEqual(len(self._cables()), 3)

    def test_an_internal_route_starts_and_ends_on_its_two_devices(self):
        scene = _scene(self.rack)
        boxes = {d.device.pk: d.box for d in scene.devices}
        for routed in (c for c in scene.cables if c.run.kind == 'interface'):
            start, end = routed.points[0], routed.points[-1]
            self.assertAlmostEqual(start[1], boxes[routed.run.local_device.pk].y)
            self.assertAlmostEqual(start[2], boxes[routed.run.local_device.pk].rear_z)
            self.assertAlmostEqual(end[1], boxes[routed.run.peer_device.pk].y)
            self.assertAlmostEqual(end[2], boxes[routed.run.peer_device.pk].rear_z)
            self.assertIsNone(routed.end_label)

    def test_power_runs_on_the_left_and_data_on_the_right(self):
        for routed in self._cables():
            expected = LEFT if routed.run.kind == 'power' else RIGHT
            self.assertEqual(routed.manager, expected)

    def test_the_vertical_run_stays_inside_its_manager(self):
        scene = _scene(self.rack)
        for routed in scene.cables:
            centre, width = scene.managers[routed.manager]
            vertical_x = routed.points[2][0]
            self.assertLessEqual(abs(vertical_x - centre), width / 2)

    def test_the_lacing_is_behind_the_rear_rail(self):
        scene = _scene(self.rack)
        for routed in scene.cables:
            self.assertLess(routed.points[2][2], scene.rear_rail_z)
            self.assertGreater(routed.points[2][2], -scene.depth / 2)

    def test_two_cables_in_one_manager_get_their_own_lanes(self):
        data = [c for c in self._cables() if c.manager == RIGHT]
        lanes = {(c.points[2][0], c.points[2][2]) for c in data}
        self.assertEqual(len(lanes), 2)

    def test_two_cables_leaving_one_device_leave_from_different_places(self):
        data = [c for c in self._cables() if c.run.kind == 'interface']
        self.assertNotEqual(data[0].points[0][0], data[1].points[0][0])

    def test_the_route_turns_only_at_right_angles(self):
        # The corners are rounded by the browser; the route itself runs along the axes, the way
        # a cable is dressed, so every segment changes exactly one coordinate.
        for routed in self._cables():
            for a, b in zip(routed.points, routed.points[1:], strict=False):
                changed = sum(1 for i in range(3) if abs(a[i] - b[i]) > 1e-6)
                self.assertLessEqual(changed, 1, routed.points)


class LeavingTheRackTest(LensTestCase):
    def setUp(self):
        self.rack = make_rack(self.site, u_height=10)
        self.other = make_rack(self.site, name='R2', u_height=10)
        self.local = make_device(self.site, self.rack, 'here', self.role, self.manufacturer, interfaces=2)
        self.far = make_device(self.site, self.other, 'there', self.role, self.manufacturer, interfaces=2)
        cable(self.local.interfaces.get(name='eth0'), self.far.interfaces.get(name='eth0'))
        cable(self.local.interfaces.get(name='eth1'), self.far.interfaces.get(name='eth1'))

    def test_it_rises_out_through_the_roof(self):
        scene = _scene(self.rack)
        for routed in scene.cables:
            self.assertGreaterEqual(routed.points[-1][1], scene.height + EXIT_RISE_MM)

    def test_it_is_named_after_the_far_rack(self):
        routed = _scene(self.rack).cables[0]
        self.assertTrue(routed.end_label.startswith('R2'))
        self.assertFalse(routed.as_json()['internal'])

    def test_two_markers_end_in_different_lanes(self):
        ends = {(routed.points[-1][0], routed.points[-1][2]) for routed in _scene(self.rack).cables}
        self.assertEqual(len(ends), 2)

    def test_a_far_end_the_reader_may_not_see_is_not_named(self):
        scene = _scene(self.rack, devices_queryset=Device.objects.filter(pk=self.local.pk))
        self.assertEqual({routed.end_label for routed in scene.cables}, {RESTRICTED_LABEL})


class RackViewTest(ViewTestCase):
    def setUp(self):
        super().setUp()
        self.rack = make_rack(self.site, u_height=10)
        self.device = make_device(self.site, self.rack, 'srv', self.role, self.manufacturer, interfaces=1)

    def _get(self):
        return self.client.get(reverse('dcim:rack_lens', args=[self.rack.pk]))

    def test_the_tab_renders_with_its_scene(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="lens-rack3d-config"')
        self.assertEqual(response.context['rack3d_config']['scene']['devices'][0]['id'], self.device.pk)
        self.assertTrue(response.context['rack3d_config']['enabled'])

    def test_three_is_loaded_through_an_import_map(self):
        response = self._get()
        self.assertContains(response, '<script type="importmap">')
        self.assertContains(response, 'build/three.module.js')
        self.assertContains(response, '"three/addons/"')
        self.assertContains(response, '"lens/stage3d": "/static/netbox_spatial_lens/stage3d.js?v=')

    def test_an_empty_setting_turns_the_drawing_off(self):
        plugins_config = {
            **settings.PLUGINS_CONFIG,
            'netbox_spatial_lens': {**settings.PLUGINS_CONFIG['netbox_spatial_lens'], 'three_base': ''},
        }
        with override_settings(PLUGINS_CONFIG=plugins_config):
            response = self._get()
        self.assertEqual(response.status_code, 200)
        # The stage is still mapped, so it can say on the page why nothing is drawn.
        self.assertContains(response, '"lens/stage3d"')
        self.assertNotContains(response, 'three.module.js')
        self.assertFalse(response.context['rack3d_config']['enabled'])

    def test_the_column_beside_it_is_rendered_up_front(self):
        response = self._get()
        self.assertContains(response, f'data-lens-alloc="{self.device.pk}"')
        self.assertContains(response, 'data-lens-trace-card')
        self.assertContains(response, 'rack_panel.js')


class RackVisibilityTest(ViewTestCase):
    def test_a_device_the_reader_may_not_see_is_not_in_the_scene(self):
        rack = make_rack(self.site, u_height=10)
        mine = make_device(self.site, rack, 'mine', self.role, self.manufacturer, position=1)
        make_device(self.site, rack, 'secretbox', self.role, self.manufacturer, position=5)

        self.user.is_superuser = False
        self.user.save()
        grant(self.user, 'dcim.rack')
        grant(self.user, 'dcim.device', constraints={'name': 'mine'})

        response = self.client.get(reverse('dcim:rack_lens', args=[rack.pk]))
        self.assertEqual(response.status_code, 200)
        ids = [d['id'] for d in response.context['rack3d_config']['scene']['devices']]
        self.assertEqual(ids, [mine.pk])
        self.assertNotContains(response, 'secretbox')
