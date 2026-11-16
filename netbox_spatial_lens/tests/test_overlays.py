"""
Overlays, their legends, and the rule that no data is never good news.
"""

import copy

from dcim.models import PowerOutlet, PowerPort
from django.conf import settings
from django.test import override_settings

from netbox_spatial_lens.overlays import (
    NO_DATA_COLOUR,
    NO_DATA_LABEL,
    BuiltinColouring,
    LegendEntry,
    Overlay,
    RackValue,
    Registry,
    cooling_overlay,
    floor_power_utilisation,
    get_overlay,
    power_overlay,
    register_overlay,
    resolve_colouring,
    role_overlay,
    space_overlay,
)
from netbox_spatial_lens.tests.base import (
    LensTestCase,
    cable,
    make_device,
    make_rack,
    power_feed,
)


class RackValueTest(LensTestCase):
    def test_the_default_is_no_data(self):
        value = RackValue()
        self.assertFalse(value.has_data)
        self.assertEqual(value.colour, NO_DATA_COLOUR)
        self.assertEqual(value.label, NO_DATA_LABEL)

    def test_zero_is_data(self):
        # Nought per cent and "nobody recorded it" must not collapse into the same answer.
        self.assertTrue(RackValue(value=0, label='0%').has_data)


class LegendTest(LensTestCase):
    def test_a_banded_overlay_keeps_its_declared_legend(self):
        overlay = Overlay('x', 'X', lambda racks: {}, legend=[LegendEntry('#fff', 'Low')])
        labels = [entry.label for entry in overlay.legend_for([])]
        self.assertEqual(labels, ['Low', NO_DATA_LABEL])

    def test_every_entry_carries_a_count(self):
        # The legend is usually read as a tally, so a colour without a number beside it is
        # only half the answer.
        overlay = Overlay('x', 'X', lambda racks: {}, legend=[LegendEntry('#111', 'Low')])
        entries = overlay.legend_for([RackValue('#111', 'Low', 1), RackValue('#111', 'Low', 2)])
        self.assertEqual(entries[0].count, 2)

    def test_a_band_nothing_falls_in_is_kept_with_a_zero(self):
        # The bands are the scale; a scale with gaps is harder to read than one with zeroes.
        overlay = Overlay('x', 'X', lambda racks: {}, legend=[LegendEntry('#111', 'Low')])
        self.assertEqual(overlay.legend_for([])[0].count, 0)

    def test_the_no_data_entry_is_counted_too(self):
        overlay = Overlay('x', 'X', lambda racks: {})
        entries = overlay.legend_for([RackValue(), RackValue(), RackValue('#111', 'Some', 1)])
        self.assertEqual(entries[-1].count, 2)

    def test_a_categorical_overlay_builds_its_legend_from_the_floor(self):
        # The bug this guards: role coloured four groups of racks and the legend read only
        # "No data", because the overlay declared none and none was derived.
        overlay = Overlay('x', 'X', lambda racks: {})
        values = [
            RackValue('#111', 'Compute', 'Compute'),
            RackValue('#222', 'Storage', 'Storage'),
            RackValue('#111', 'Compute', 'Compute'),
            RackValue(),
        ]
        labels = [entry.label for entry in overlay.legend_for(values)]
        self.assertEqual(labels, ['Compute', 'Storage', NO_DATA_LABEL])

    def test_the_no_data_entry_is_always_last(self):
        overlay = Overlay('x', 'X', lambda racks: {})
        self.assertEqual(overlay.legend_for([])[-1].label, NO_DATA_LABEL)


class BrokenOverlayTest(LensTestCase):
    def test_an_overlay_that_raises_does_not_take_the_floor_down(self):
        def explode(racks):
            raise RuntimeError('boom')

        overlay = Overlay('boom', 'Boom', explode)
        rack = make_rack(self.site)
        with self.assertLogs('netbox.plugins.netbox_spatial_lens.overlays', level='ERROR'):
            values = overlay.evaluate([rack])
        self.assertFalse(values[rack.pk].has_data)

    def test_registration_makes_an_overlay_findable(self):
        register_overlay('probe', 'Probe', lambda racks: {})
        self.assertIsNotNone(get_overlay('probe'))

    def test_an_unknown_name_is_not_an_error(self):
        self.assertIsNone(get_overlay('no-such-overlay'))


class ResolveColouringTest(LensTestCase):
    """
    Which colouring a drawing opens with. One rule for the floor, the rack and the map.
    """

    def setUp(self):
        super().setUp()
        self.first = Overlay('first', 'First', lambda items: {})
        self.default = Overlay('default', 'Default', lambda items: {})
        self.named = Overlay('named', 'Named', lambda items: {})
        self.colourings = [self.first, self.default, self.named]

    def test_the_named_colouring_wins(self):
        self.assertIs(resolve_colouring(self.colourings, 'named', 'default'), self.named)

    def test_an_unknown_name_falls_back_to_the_default(self):
        self.assertIs(resolve_colouring(self.colourings, 'no-such-thing', 'default'), self.default)

    def test_no_name_falls_back_to_the_default(self):
        self.assertIs(resolve_colouring(self.colourings, None, 'default'), self.default)

    def test_a_default_nothing_answers_to_falls_back_to_the_first_registered(self):
        # The case the map once missed: the default colouring switched off, or misspelt, while
        # others are still on offer.
        self.assertIs(resolve_colouring(self.colourings, None, 'no-such-default'), self.first)

    def test_nothing_registered_is_none(self):
        self.assertIsNone(resolve_colouring([], 'named', 'default'))


class RegistryTest(LensTestCase):
    """
    One registry per level. Built fresh here, because the real ones are process-wide.
    """

    def setUp(self):
        super().setUp()
        self.registry = Registry(
            kind=Overlay,
            noun='Overlay',
            default_setting='default_overlay',
            builtins_setting='enable_builtin_overlays',
            builtins={
                'one': BuiltinColouring('One', lambda items: {}, 'The first.'),
                'two': BuiltinColouring('Two', lambda items: {}, 'The second.', [LegendEntry('#000000', 'Black')]),
            },
        )

    def _setting(self, value):
        config = copy.deepcopy(settings.PLUGINS_CONFIG)
        config['netbox_spatial_lens']['enable_builtin_overlays'] = value
        return override_settings(PLUGINS_CONFIG=config)

    def test_true_registers_every_builtin_in_order(self):
        with self._setting(True):
            self.registry.register_configured_builtins()
        self.assertEqual([c.name for c in self.registry.all()], ['one', 'two'])
        self.assertEqual(self.registry.get('two').legend[0].label, 'Black')

    def test_false_registers_none(self):
        with self._setting(False):
            self.registry.register_configured_builtins()
        self.assertEqual(self.registry.all(), [])

    def test_a_list_registers_the_named_ones_and_skips_an_unknown_name(self):
        with self._setting(['two', 'typo']), self.assertLogs('netbox.plugins.netbox_spatial_lens.overlays', 'WARNING'):
            self.registry.register_configured_builtins()
        self.assertEqual([c.name for c in self.registry.all()], ['two'])

    def test_a_later_registration_replaces_an_earlier_one(self):
        self.registry.register('one', 'First', lambda items: {})
        with self.assertLogs('netbox.plugins.netbox_spatial_lens.overlays', 'WARNING'):
            replaced = self.registry.register('one', 'Replaced', lambda items: {})
        self.assertIs(self.registry.get('one'), replaced)
        self.assertEqual(len(self.registry.all()), 1)

    def test_a_registration_is_of_the_registry_kind(self):
        self.assertIsInstance(self.registry.register('three', 'Three', lambda items: {}), Overlay)

    def test_no_name_is_nothing(self):
        self.registry.register('one', 'One', lambda items: {})
        self.assertIsNone(self.registry.get(None))


class CoolingOverlayTest(LensTestCase):
    def test_a_rack_with_no_cooling_recorded_has_no_data(self):
        rack = make_rack(self.site)
        self.assertNotIn(rack.pk, cooling_overlay([rack]))

    def test_capability_colours_and_capacity_labels(self):
        rack = make_rack(self.site, cooling_capability='liquid-only', cooling_capacity=30)
        value = cooling_overlay([rack])[rack.pk]
        self.assertIn('Liquid', value.label)
        self.assertIn('30', value.label)


class RoleOverlayTest(LensTestCase):
    def test_a_rack_with_no_role_has_no_data(self):
        rack = make_rack(self.site)
        self.assertNotIn(rack.pk, role_overlay([rack]))

    def test_the_role_colour_is_used(self):
        from dcim.models import RackRole

        role = RackRole.objects.create(name='Edge', slug='edge', color='ff0000')
        rack = make_rack(self.site, role=role)
        self.assertEqual(role_overlay([rack])[rack.pk].colour, '#ff0000')


class SpaceOverlayTest(LensTestCase):
    def test_a_device_excluded_from_utilisation_is_not_counted(self):
        # NetBox's own figure passes ignore_excluded_devices=True, so a shelf or a blanking
        # panel whose type is marked "exclude from utilization" is not space consumed. Counting
        # it here made the plan, the legend band and the Space stat disagree with the rack's
        # own page, and with this plugin's rack view, which asks NetBox directly.
        rack = make_rack(self.site, name='RX', u_height=10)
        device = make_device(self.site, rack, 'shelf', self.role, self.manufacturer, position=1, u_height=2)
        device.device_type.exclude_from_utilization = True
        device.device_type.save()

        # Asserted against NetBox's own number rather than against a figure of my choosing:
        # the whole claim of this overlay is that it agrees with the rack's own page.
        self.assertEqual(space_overlay([rack])[rack.pk].value, rack.get_utilization())

    def test_an_empty_rack_reads_as_zero_not_as_no_data(self):
        rack = make_rack(self.site, u_height=10)
        value = space_overlay([rack])[rack.pk]
        self.assertTrue(value.has_data)
        self.assertEqual(value.value, 0)


class PowerOverlayTest(LensTestCase):
    def test_a_rack_with_no_feeds_has_no_data(self):
        # Not zero per cent: a rack nobody has recorded a supply for is unknown, and the
        # overlay must not colour it as comfortably idle.
        rack = make_rack(self.site)
        self.assertNotIn(rack.pk, power_overlay([rack]))

    def test_capacity_without_draw_is_zero_per_cent(self):
        rack = make_rack(self.site)
        power_feed(rack)
        value = power_overlay([rack])[rack.pk]
        self.assertTrue(value.has_data)
        self.assertEqual(value.value, 0)

    def test_allocated_draw_is_summed_through_the_pdu(self):
        rack = make_rack(self.site, u_height=10)
        feed = power_feed(rack, amperage=16, voltage=230, max_utilization=100)
        pdu = make_device(
            self.site,
            rack,
            'pdu',
            self.switch_role,
            self.manufacturer,
            position=1,
            power_ports=1,
            outlets=2,
        )
        server = make_device(self.site, rack, 'srv', self.role, self.manufacturer, position=2, power_ports=1)
        pdu.powerports.update(allocated_draw=None, maximum_draw=None)
        cable(pdu.powerports.first(), feed)
        cable(server.powerports.first(), pdu.poweroutlets.first())

        allocated, capacity = floor_power_utilisation([rack])[rack.pk]
        self.assertEqual(capacity, 16 * 230)
        # The one server's allocated_draw, reached through the PDU's outlet.
        self.assertEqual(allocated, 100)

    def test_it_agrees_with_netbox(self):
        # The overlay restates NetBox's arithmetic to avoid 20 queries a rack, so it has to
        # keep giving NetBox's answer.
        rack = make_rack(self.site, u_height=10)
        feed = power_feed(rack)
        pdu = make_device(
            self.site,
            rack,
            'pdu2',
            self.switch_role,
            self.manufacturer,
            position=1,
            power_ports=1,
            outlets=2,
        )
        server = make_device(self.site, rack, 'srv2', self.role, self.manufacturer, position=2, power_ports=1)
        pdu.powerports.update(allocated_draw=None, maximum_draw=None)
        cable(pdu.powerports.first(), feed)
        cable(server.powerports.first(), pdu.poweroutlets.first())

        allocated, capacity = floor_power_utilisation([rack])[rack.pk]
        self.assertAlmostEqual(allocated / capacity * 100, rack.get_power_utilization(), places=1)

    def _fed_pdu(self, rack, name='pdu3', outlets=1):
        pdu = make_device(
            self.site, rack, name, self.switch_role, self.manufacturer, position=1, power_ports=1, outlets=outlets
        )
        cable(pdu.powerports.first(), power_feed(rack, name=f'{name}-feed'))
        return pdu

    def test_a_draw_declared_on_the_pdu_inlet_is_kept_rather_than_summed(self):
        rack = make_rack(self.site, u_height=10)
        pdu = self._fed_pdu(rack)
        pdu.powerports.update(allocated_draw=500)
        server = make_device(self.site, rack, 'srv3', self.role, self.manufacturer, position=2, power_ports=1)
        cable(server.powerports.first(), pdu.poweroutlets.first())

        allocated, capacity = floor_power_utilisation([rack])[rack.pk]
        self.assertEqual(allocated, 500)
        self.assertAlmostEqual(allocated / capacity * 100, rack.get_power_utilization(), places=1)

    def test_draw_carries_up_a_chain_of_pdus(self):
        rack = make_rack(self.site, u_height=10)
        upstream = self._fed_pdu(rack)
        upstream.powerports.update(allocated_draw=None, maximum_draw=None)
        downstream = make_device(
            self.site, rack, 'pdu4', self.switch_role, self.manufacturer, position=2, power_ports=1, outlets=1
        )
        downstream.powerports.update(allocated_draw=None, maximum_draw=None)
        server = make_device(self.site, rack, 'srv4', self.role, self.manufacturer, position=3, power_ports=1)
        cable(downstream.powerports.first(), upstream.poweroutlets.first())
        cable(server.powerports.first(), downstream.poweroutlets.first())

        allocated, capacity = floor_power_utilisation([rack])[rack.pk]
        self.assertEqual(allocated, 100)
        self.assertAlmostEqual(allocated / capacity * 100, rack.get_power_utilization(), places=1)

    def test_an_outlet_of_an_inlet_no_feed_supplies_is_not_this_racks_load(self):
        rack = make_rack(self.site, u_height=10)
        pdu = self._fed_pdu(rack, outlets=2)
        pdu.powerports.update(allocated_draw=None, maximum_draw=None)
        unfed = PowerPort.objects.create(device=pdu, name='inlet-b')
        on_unfed = pdu.poweroutlets.last()
        on_unfed.power_port = unfed
        on_unfed.save()
        server = make_device(self.site, rack, 'srv5', self.role, self.manufacturer, position=2, power_ports=1)
        cable(server.powerports.first(), on_unfed)

        allocated, capacity = floor_power_utilisation([rack])[rack.pk]
        self.assertEqual(allocated, 0)
        self.assertAlmostEqual(allocated / capacity * 100, rack.get_power_utilization(), places=1)


class RedundancyOverlayTest(LensTestCase):
    """
    Which devices depend on a single power feed, on the floor and in the rack.

    One rack with two feeds, a PDU on each, and three servers: one cabled to both PDUs, one to
    a single PDU, and one with a supply left uncabled.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rack = make_rack(cls.site, name='R-power', u_height=20)
        cls.pdus = []
        for index, side in enumerate(('a', 'b')):
            pdu = make_device(
                cls.site,
                cls.rack,
                f'pdu-{side}',
                cls.switch_role,
                cls.manufacturer,
                position=1 + index,
                power_ports=1,
                outlets=1,
            )
            cable(pdu.powerports.first(), power_feed(cls.rack, name=f'feed-{side}'))
            for number in (1, 2):
                PowerOutlet.objects.create(device=pdu, name=f'extra{number}', power_port=pdu.powerports.first())
            cls.pdus.append(pdu)

        cls.dual = cls.server('dual', 5)
        cls.plug(cls.dual, 0, cls.pdus[0], 'outlet0')
        cls.plug(cls.dual, 1, cls.pdus[1], 'outlet0')
        cls.single = cls.server('single', 6)
        cls.plug(cls.single, 0, cls.pdus[0], 'extra1')
        cls.plug(cls.single, 1, cls.pdus[0], 'extra2')
        cls.unplugged = cls.server('unplugged', 7)

    @classmethod
    def server(cls, name, position):
        return make_device(cls.site, cls.rack, name, cls.role, cls.manufacturer, position=position, power_ports=2)

    @staticmethod
    def plug(server, port, pdu, outlet):
        cable(server.powerports.get(name=f'psu{port}'), pdu.poweroutlets.get(name=outlet))

    def device_values(self):
        from netbox_spatial_lens.device_overlays import get_device_overlay
        from netbox_spatial_lens.elevation import build_elevation

        mounted = build_elevation(self.rack).devices
        values = get_device_overlay('redundancy').evaluate(mounted)
        return {m.device.name: values[m.device.pk] for m in mounted}

    def test_a_device_on_two_feeds_is_redundant_and_names_them(self):
        value = self.device_values()['dual']
        self.assertEqual(value.label, '2 feeds: feed-a (feed-a-panel), feed-b (feed-b-panel)')
        self.assertEqual(value.colour, '#4c9f70')

    def test_two_supplies_on_one_feed_are_one_feed(self):
        value = self.device_values()['single']
        self.assertEqual(value.label, '1 feed: feed-a (feed-a-panel)')
        self.assertEqual(value.colour, '#c9483f')

    def test_a_device_with_nothing_cabled_is_not_traced(self):
        self.assertEqual(self.device_values()['unplugged'].label, 'No feed traced')

    def test_a_pdu_is_not_judged_for_its_single_inlet(self):
        self.assertFalse(self.device_values()['pdu-a'].has_data)

    def test_the_worst_device_decides_the_rack_and_the_label_counts_them(self):
        overlay = get_overlay('redundancy')
        value = overlay.evaluate([self.rack])[self.rack.pk]
        self.assertEqual(value.label, '1 of 3 devices on one feed, 1 of 3 with no feed traced')
        self.assertEqual(overlay.band_of(value), 'single')

    def test_a_rack_is_not_gauged_by_its_count_of_devices(self):
        from netbox_spatial_lens.layout import build_layout
        from netbox_spatial_lens.tests.base import make_floor, place

        floor = make_floor(self.site, name='Powered')
        place(floor, self.rack)
        placed = build_layout(floor, get_overlay('redundancy'))[0]
        self.assertIsNone(placed.fraction)

    def test_a_rack_of_redundant_devices_is_green(self):
        rack = make_rack(self.site, name='R-ok', u_height=10)
        server = make_device(self.site, rack, 'ok', self.role, self.manufacturer, position=1, power_ports=2)
        cable(server.powerports.get(name='psu0'), power_feed(rack, name='ok-a'))
        cable(server.powerports.get(name='psu1'), power_feed(rack, name='ok-b'))
        overlay = get_overlay('redundancy')
        value = overlay.evaluate([rack])[rack.pk]
        self.assertEqual(value.label, '1 of 1 devices on two or more feeds')
        self.assertEqual(overlay.band_of(value), 'redundant')

    def test_a_rack_with_no_powered_device_is_no_data(self):
        empty = make_rack(self.site, name='R-empty')
        self.assertFalse(get_overlay('redundancy').evaluate([empty])[empty.pk].has_data)

    def test_the_cost_does_not_grow_with_the_racks(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        overlay = get_overlay('redundancy')
        with CaptureQueriesContext(connection) as one:
            overlay.evaluate([self.rack])
        other = make_rack(self.site, name='R-second', u_height=10)
        server = make_device(self.site, other, 'second', self.role, self.manufacturer, position=1, power_ports=1)
        cable(server.powerports.first(), power_feed(other, name='second-feed'))
        with CaptureQueriesContext(connection) as two:
            overlay.evaluate([self.rack, other])
        self.assertLessEqual(len(two), len(one) + 1)
