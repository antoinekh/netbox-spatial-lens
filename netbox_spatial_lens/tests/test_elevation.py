"""
The inside of a rack: where devices sit, which face they are drawn on, and their cabling.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext

from netbox_spatial_lens.elevation import build_elevation, unit_offset
from netbox_spatial_lens.ports import rack_allocation
from netbox_spatial_lens.tests.base import (
    LensTestCase,
    cable,
    make_device,
    make_rack,
    power_feed,
)


class UnitPositionTest(LensTestCase):
    def test_u1_sits_at_the_bottom(self):
        rack = make_rack(self.site, u_height=10)
        self.assertEqual(unit_offset(rack, 1, 1), 0)
        self.assertEqual(unit_offset(rack, 10, 1), 9)

    def test_desc_units_inverts_the_rack(self):
        # Getting this wrong draws every device upside down, and looks plausible.
        rack = make_rack(self.site, u_height=10, desc_units=True)
        self.assertEqual(unit_offset(rack, 1, 1), 9)
        self.assertEqual(unit_offset(rack, 10, 1), 0)

    def test_a_tall_device_in_a_descending_rack_is_measured_from_its_lowest_unit(self):
        rack = make_rack(self.site, u_height=10, desc_units=True)
        self.assertEqual(unit_offset(rack, 1, 2), 8)

    def test_the_starting_unit_is_the_bottom(self):
        rack = make_rack(self.site, u_height=10, starting_unit=5)
        self.assertEqual(unit_offset(rack, 5, 1), 0)


class MountingTest(LensTestCase):
    def setUp(self):
        self.rack = make_rack(self.site, u_height=10)

    def test_a_full_depth_device_is_listed_once(self):
        make_device(self.site, self.rack, 'both', self.role, self.manufacturer, full_depth=True)
        self.assertEqual(len(build_elevation(self.rack).devices), 1)

    def test_it_knows_its_face_and_height(self):
        make_device(
            self.site, self.rack, 'back', self.role, self.manufacturer, u_height=2, face='rear', full_depth=False
        )
        mounted = build_elevation(self.rack).devices[0]
        self.assertEqual(mounted.face, 'rear')
        self.assertEqual(mounted.units, 2)

    def test_a_device_with_no_position_is_listed_rather_than_dropped(self):
        device = make_device(self.site, self.rack, 'floating', self.role, self.manufacturer)
        device.position = None
        device.save()
        elevation = build_elevation(self.rack)
        self.assertEqual([d.name for d in elevation.unplaced], ['floating'])
        self.assertEqual(elevation.devices, [])


class CablingTest(LensTestCase):
    def setUp(self):
        self.rack = make_rack(self.site, u_height=10)
        self.switch = make_device(
            self.site,
            self.rack,
            'tor',
            self.switch_role,
            self.manufacturer,
            position=10,
            interfaces=4,
        )
        self.server = make_device(
            self.site,
            self.rack,
            'srv',
            self.role,
            self.manufacturer,
            position=1,
            interfaces=2,
            power_ports=1,
        )

    def test_a_cable_inside_the_rack_yields_one_run_not_two(self):
        cable(self.server.interfaces.first(), self.switch.interfaces.first())
        runs = build_elevation(self.rack).runs
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].internal)

    def test_a_cable_from_a_device_with_no_position_is_drawn_from_its_mounted_end(self):
        shelf = make_device(self.site, self.rack, 'shelf', self.role, self.manufacturer, position=None, interfaces=1)
        cable(shelf.interfaces.first(), self.switch.interfaces.first())
        runs = build_elevation(self.rack).runs
        self.assertEqual([run.local_device for run in runs], [self.switch])
        self.assertEqual(runs[0].peer_device, shelf)

    def test_a_cable_leaving_the_rack_is_not_internal(self):
        other = make_rack(self.site, name='R2', u_height=10)
        far = make_device(self.site, other, 'far', self.role, self.manufacturer, interfaces=1)
        cable(self.server.interfaces.first(), far.interfaces.first())
        run = build_elevation(self.rack).runs[0]
        self.assertFalse(run.internal)
        self.assertEqual(run.peer_rack, other)

    def test_the_run_names_the_termination_it_can_be_traced_from(self):
        cable(self.server.interfaces.first(), self.switch.interfaces.first())
        run = build_elevation(self.rack).runs[0]
        self.assertEqual(run.termination_type, 'dcim.interface')
        self.assertIsNotNone(run.termination_id)

    def test_cabling_costs_a_bounded_number_of_queries(self):
        # The regression this guards: link_peers and get_power_draw per object made a rack of
        # twelve devices cost 182 queries. `PduAggregateTest` guards the other half of it,
        # that the cost stops growing once the devices feed each other.
        for i in range(4):
            make_device(
                self.site,
                self.rack,
                f'extra{i}',
                self.role,
                self.manufacturer,
                position=i + 2,
                interfaces=2,
                power_ports=1,
            )
        with CaptureQueriesContext(connection) as captured:
            build_elevation(self.rack)
        self.assertLess(len(captured.captured_queries), 30)


class AllocationTest(LensTestCase):
    def test_the_rack_total_is_the_sum_of_its_devices(self):
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'a', self.role, self.manufacturer, position=1, interfaces=3)
        make_device(self.site, rack, 'b', self.role, self.manufacturer, position=2, interfaces=5)
        groups = {g.label: g for g in rack_allocation(build_elevation(rack))}
        self.assertEqual(groups['Interfaces'].total, 8)
        self.assertEqual(groups['Interfaces'].free, 8)

    def test_a_connected_port_is_not_free(self):
        rack = make_rack(self.site, u_height=10)
        a = make_device(self.site, rack, 'a', self.role, self.manufacturer, position=1, interfaces=1)
        b = make_device(self.site, rack, 'b', self.role, self.manufacturer, position=2, interfaces=1)
        cable(a.interfaces.first(), b.interfaces.first())
        groups = {g.label: g for g in rack_allocation(build_elevation(rack))}
        self.assertEqual(groups['Interfaces'].free, 0)


class DevicePowerTest(LensTestCase):
    def test_a_device_reports_the_feed_behind_its_socket(self):
        rack = make_rack(self.site, u_height=10)
        feed = power_feed(rack)
        pdu = make_device(
            self.site,
            rack,
            'pdu',
            self.switch_role,
            self.manufacturer,
            position=1,
            power_ports=1,
            outlets=1,
        )
        server = make_device(self.site, rack, 'srv', self.role, self.manufacturer, position=2, power_ports=1)
        cable(pdu.powerports.first(), feed)
        cable(server.powerports.first(), pdu.poweroutlets.first())

        mounted = {m.device.name: m for m in build_elevation(rack).devices}
        supplies = mounted['srv'].power.feeds
        self.assertEqual(len(supplies), 1)
        self.assertEqual(supplies[0]['feed'], feed.name)

    def test_an_uncabled_power_port_is_counted_not_hidden(self):
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer, power_ports=2)
        mounted = build_elevation(rack).devices[0]
        self.assertEqual(mounted.power.unconnected, 2)


class PduAggregateTest(LensTestCase):
    """
    What a PDU draws is the sum of what is plugged into it.

    NetBox answers that per power port, and each answer walks the tree below it. A rack of
    PDUs therefore cost a handful of queries per PDU, which is the one thing this module
    exists to avoid. The whole rack is resolved together instead, and these say the answer
    did not change.
    """

    def _pdu(self, rack, name, position, outlets=1, declared=False):
        pdu = make_device(
            self.site,
            rack,
            name,
            self.switch_role,
            self.manufacturer,
            position=position,
            power_ports=1,
            outlets=outlets,
        )
        if not declared:
            # The helper declares 100/200 on every port. A PDU in the field usually declares
            # nothing, which is what puts NetBox into aggregating mode.
            pdu.powerports.update(allocated_draw=None, maximum_draw=None)
        return pdu

    def _server(self, rack, name, position):
        return make_device(
            self.site,
            rack,
            name,
            self.role,
            self.manufacturer,
            position=position,
            power_ports=1,
        )

    def _power(self, rack):
        return {m.device.name: m.power for m in build_elevation(rack).devices}

    def test_a_pdu_draws_the_sum_of_what_is_plugged_into_it(self):
        rack = make_rack(self.site, u_height=10)
        pdu = self._pdu(rack, 'pdu', 1, outlets=2)
        for i, outlet in enumerate(pdu.poweroutlets.all()):
            cable(self._server(rack, f'srv{i}', i + 2).powerports.first(), outlet)

        power = self._power(rack)
        self.assertEqual(power['pdu'].allocated_watts, 200)
        self.assertEqual(power['pdu'].maximum_watts, 400)

    def test_an_empty_pdu_draws_nothing(self):
        rack = make_rack(self.site, u_height=10)
        self._pdu(rack, 'pdu', 1, outlets=2)
        power = self._power(rack)
        self.assertEqual(power['pdu'].allocated_watts, 0)
        self.assertEqual(power['pdu'].maximum_watts, 0)

    def test_a_declared_draw_is_kept_rather_than_summed(self):
        rack = make_rack(self.site, u_height=10)
        pdu = self._pdu(rack, 'pdu', 1, declared=True)
        cable(self._server(rack, 'srv', 2).powerports.first(), pdu.poweroutlets.first())

        power = self._power(rack)
        self.assertEqual(power['pdu'].allocated_watts, 100)
        self.assertEqual(power['pdu'].maximum_watts, 200)

    def test_draw_carries_up_a_chain_of_pdus(self):
        rack = make_rack(self.site, u_height=10)
        upper = self._pdu(rack, 'pdu-a', 1)
        lower = self._pdu(rack, 'pdu-b', 2)
        cable(lower.powerports.first(), upper.poweroutlets.first())
        cable(self._server(rack, 'srv', 3).powerports.first(), lower.poweroutlets.first())

        power = self._power(rack)
        self.assertEqual(power['pdu-b'].allocated_watts, 100)
        self.assertEqual(power['pdu-a'].allocated_watts, 100)

    def test_a_pdu_feeding_itself_is_not_followed_forever(self):
        rack = make_rack(self.site, u_height=10)
        pdu = self._pdu(rack, 'pdu', 1)
        cable(pdu.powerports.first(), pdu.poweroutlets.first())
        self.assertEqual(self._power(rack)['pdu'].allocated_watts, 0)

    def test_a_second_declared_inlet_is_added_to_the_load(self):
        # A PDU can declare a draw for its own electronics on a port that feeds nothing. That
        # is load on the feed, and summing over the device's ports is what counts it.
        from dcim.models import PowerPort

        rack = make_rack(self.site, u_height=10)
        pdu = self._pdu(rack, 'pdu', 1)
        PowerPort.objects.create(device=pdu, name='psu1', allocated_draw=40, maximum_draw=60)
        cable(self._server(rack, 'srv', 2).powerports.first(), pdu.poweroutlets.first())

        power = self._power(rack)
        self.assertEqual(power['pdu'].allocated_watts, 140)
        self.assertEqual(power['pdu'].maximum_watts, 260)

    def test_the_cost_does_not_grow_with_the_pdus(self):
        def cost(pdus):
            rack = make_rack(self.site, name=f'R{pdus}', u_height=40)
            for n in range(pdus):
                pdu = self._pdu(rack, f'p{pdus}-{n}', n * 2 + 1)
                server = self._server(rack, f's{pdus}-{n}', n * 2 + 2)
                cable(server.powerports.first(), pdu.poweroutlets.first())
            with CaptureQueriesContext(connection) as captured:
                build_elevation(rack)
            return len(captured.captured_queries)

        self.assertEqual(cost(6), cost(2))


class RackSpaceTest(LensTestCase):
    """
    How many units are used, reserved and free.
    """

    def test_an_empty_rack_is_all_free(self):
        rack = make_rack(self.site, u_height=10)
        space = build_elevation(rack).space
        self.assertEqual((space['free'], space['used'], space['reserved']), (10, 0, 0))

    def test_a_mounted_device_takes_its_units(self):
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer, position=1, u_height=2)
        space = build_elevation(rack).space
        self.assertEqual(space['used'], 2)
        self.assertEqual(space['free'], 8)

    def test_reserved_units_are_neither_used_nor_free(self):
        from dcim.models import RackReservation
        from users.models import User

        rack = make_rack(self.site, u_height=10)
        RackReservation.objects.create(
            rack=rack,
            units=[5, 6],
            user=User.objects.create_user('res', password='x'),
            description='Held',
        )
        space = build_elevation(rack).space
        self.assertEqual(space['reserved'], 2)
        self.assertEqual(space['free'], 8)

    def test_it_agrees_with_netboxs_utilisation(self):
        # The header sits beside NetBox's own percentage, so the two must not disagree. Rack
        # units are counted in halves upstream, which is what made a first attempt report 51
        # free of 48.
        from dcim.models import RackReservation
        from users.models import User

        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer, position=1, u_height=2)
        RackReservation.objects.create(
            rack=rack,
            units=[8],
            user=User.objects.create_user('res2', password='x'),
            description='Held',
        )
        space = build_elevation(rack).space
        ours = (space['used'] + space['reserved']) / space['total'] * 100
        self.assertAlmostEqual(ours, rack.get_utilization(), places=1)
