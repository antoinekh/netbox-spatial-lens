"""
The colourings of the racks on a floor, and that they agree with NetBox.
"""

from dcim.models import PowerOutlet, PowerPort
from django.db import connection
from django.test.utils import CaptureQueriesContext

from netbox_spatial_lens.colouring import Level, registry
from netbox_spatial_lens.rack_colourings import floor_power_utilisation, floor_space_utilisation
from netbox_spatial_lens.tests.base import (
    LensTestCase,
    cable,
    make_device,
    make_rack,
    power_feed,
    read,
    read_devices,
)


def reading(name: str, rack):
    """What the rack colouring `name` says of one rack."""
    return read(Level.RACKS, name, [rack])[rack.pk]


class CoolingColouringTest(LensTestCase):
    def test_a_rack_with_no_cooling_recorded_has_no_data(self):
        rack = make_rack(self.site)
        self.assertFalse(reading('cooling', rack).has_data)

    def test_capability_colours_and_capacity_labels(self):
        rack = make_rack(self.site, cooling_capability='liquid-only', cooling_capacity=30)
        value = reading('cooling', rack)
        self.assertIn('Liquid', value.label)
        self.assertIn('30', value.label)
        self.assertEqual(value.band, 'liquid-only')


class RoleColouringTest(LensTestCase):
    def test_a_rack_with_no_role_has_no_data(self):
        rack = make_rack(self.site)
        self.assertFalse(reading('role', rack).has_data)

    def test_the_role_colour_is_used(self):
        from dcim.models import RackRole

        role = RackRole.objects.create(name='Edge', slug='edge', color='ff0000')
        rack = make_rack(self.site, role=role)
        self.assertEqual(reading('role', rack).colour, '#ff0000')


class SpaceColouringTest(LensTestCase):
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
        # the whole claim of this colouring is that it agrees with the rack's own page.
        self.assertAlmostEqual(reading('space', rack).gauge * 100, rack.get_utilization())

    def test_an_empty_rack_reads_as_zero_not_as_no_data(self):
        rack = make_rack(self.site, u_height=10)
        value = reading('space', rack)
        self.assertTrue(value.has_data)
        self.assertEqual(value.gauge, 0)


class UtilisationReuseTest(LensTestCase):
    def test_the_second_ask_for_the_same_racks_costs_nothing(self):
        # The floor asks once for the colouring and once for the stat strip.
        racks = [make_rack(self.site, name='R1'), make_rack(self.site, name='R2')]
        first = floor_space_utilisation(racks)
        with CaptureQueriesContext(connection) as queries:
            second = floor_space_utilisation(racks)
        self.assertEqual(len(queries), 0)
        self.assertEqual(first, second)


class PowerColouringTest(LensTestCase):
    def test_a_rack_with_no_feeds_has_no_data(self):
        # Not zero per cent: a rack nobody has recorded a supply for is unknown, and the
        # colouring must not colour it as comfortably idle.
        rack = make_rack(self.site)
        self.assertFalse(reading('power', rack).has_data)

    def test_capacity_without_draw_is_zero_per_cent(self):
        rack = make_rack(self.site)
        power_feed(rack)
        value = reading('power', rack)
        self.assertTrue(value.has_data)
        self.assertEqual(value.gauge, 0)

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
        # The colouring restates NetBox's arithmetic to avoid 20 queries a rack, so it has to
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


class RedundancyColouringTest(LensTestCase):
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
        from netbox_spatial_lens.elevation import build_elevation

        mounted = build_elevation(self.rack).devices
        readings = read_devices('redundancy', mounted)
        return {m.device.name: readings[m.device.pk] for m in mounted}

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
        value = reading('redundancy', self.rack)
        self.assertEqual(value.label, '1 of 3 devices on one feed, 1 of 3 with no feed traced')
        self.assertEqual(value.band, 'single')

    def test_a_rack_is_not_gauged_by_its_count_of_devices(self):
        from netbox_spatial_lens.layout import build_layout
        from netbox_spatial_lens.tests.base import make_floor, place

        floor = make_floor(self.site, name='Powered')
        place(floor, self.rack)
        placed = build_layout(floor, registry.get(Level.RACKS, 'redundancy'))[0]
        self.assertIsNone(placed.fraction)

    def test_a_rack_of_redundant_devices_is_green(self):
        rack = make_rack(self.site, name='R-ok', u_height=10)
        server = make_device(self.site, rack, 'ok', self.role, self.manufacturer, position=1, power_ports=2)
        cable(server.powerports.get(name='psu0'), power_feed(rack, name='ok-a'))
        cable(server.powerports.get(name='psu1'), power_feed(rack, name='ok-b'))
        value = reading('redundancy', rack)
        self.assertEqual(value.label, '1 of 1 devices on two or more feeds')
        self.assertEqual(value.band, 'redundant')

    def test_a_rack_with_no_powered_device_is_no_data(self):
        empty = make_rack(self.site, name='R-empty')
        self.assertFalse(reading('redundancy', empty).has_data)

    def test_the_cost_does_not_grow_with_the_racks(self):
        colouring = registry.get(Level.RACKS, 'redundancy')
        with CaptureQueriesContext(connection) as one:
            colouring.evaluate([self.rack])
        other = make_rack(self.site, name='R-second', u_height=10)
        server = make_device(self.site, other, 'second', self.role, self.manufacturer, position=1, power_ports=1)
        cable(server.powerports.first(), power_feed(other, name='second-feed'))
        with CaptureQueriesContext(connection) as two:
            colouring.evaluate([self.rack, other])
        self.assertLessEqual(len(two), len(one) + 1)
