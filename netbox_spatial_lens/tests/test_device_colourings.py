"""
Colouring the devices in a rack, and the reserved space beneath them.
"""

from dcim.models import RackReservation
from tenancy.models import Tenant
from users.models import User

from netbox_spatial_lens.colouring import Level, registry
from netbox_spatial_lens.elevation import build_elevation
from netbox_spatial_lens.palette import categorical_colour, completion_colour
from netbox_spatial_lens.tests.base import (
    LensTestCase,
    cable,
    make_device,
    make_rack,
    read_devices,
)


class DeviceColouringTest(LensTestCase):
    def setUp(self):
        self.rack = make_rack(self.site, u_height=10)
        self.device = make_device(self.site, self.rack, 'srv', self.role, self.manufacturer, interfaces=2)
        self.mounted = build_elevation(self.rack).devices

    def test_role_colours_by_the_role_colour(self):
        self.assertEqual(read_devices('role', self.mounted)[self.device.pk].colour, '#2196f3')

    def test_status_reads_netboxs_own_colour(self):
        # Reading NetBox's colour rather than inventing a second scheme means a device looks
        # the same here as on the device list.
        value = read_devices('status', self.mounted)[self.device.pk]
        self.assertEqual(value.label, 'Active')

    def test_a_device_with_no_tenant_has_no_data(self):
        self.assertFalse(read_devices('tenant', self.mounted)[self.device.pk].has_data)

    def test_tenant_colours_are_stable(self):
        # hash() is randomised per process, so using it would give a tenant one colour today
        # and another after a restart, and two colours at once across workers.
        tenant = Tenant.objects.create(name='Acme Corp', slug='acme-corp')
        self.device.tenant = tenant
        self.device.save()
        mounted = build_elevation(self.rack).devices
        self.assertEqual(
            read_devices('tenant', mounted)[self.device.pk].colour,
            categorical_colour('Acme Corp'),
        )

    def test_cabling_reports_the_count_and_the_percentage(self):
        value = read_devices('cabling', self.mounted)[self.device.pk]
        self.assertIn('0 of', value.label)
        self.assertEqual(value.gauge, 0)

    def test_cabling_is_a_ramp_not_three_states(self):
        # 10% and 99% are both "partly cabled" and are not the same rack to walk into, so
        # they must not come out the same colour.
        self.assertNotEqual(completion_colour(10), completion_colour(99))

    def test_nothing_and_everything_are_their_own_colours(self):
        self.assertNotEqual(completion_colour(0), completion_colour(1))
        self.assertNotEqual(completion_colour(99), completion_colour(100))

    def test_the_ramp_runs_the_opposite_way_to_utilisation(self):
        # Full is the goal here and the problem there; reusing the utilisation ramp would make
        # a finished rack look like a failing one.
        from netbox_spatial_lens.palette import utilisation_colour

        self.assertEqual(completion_colour(100), utilisation_colour(10))
        self.assertEqual(completion_colour(0), utilisation_colour(95))

    def test_cabling_reports_partly_cabled(self):
        other = make_device(self.site, self.rack, 'peer', self.role, self.manufacturer, position=2, interfaces=1)
        cable(self.device.interfaces.first(), other.interfaces.first())
        mounted = build_elevation(self.rack).devices
        value = read_devices('cabling', mounted)[self.device.pk]
        self.assertIn('1 of 2', value.label)
        self.assertEqual(value.gauge, 0.5)

    def test_an_unknown_colouring_is_not_an_error(self):
        self.assertIsNone(registry.get(Level.DEVICES, 'no-such-colouring'))


class ReservationTest(LensTestCase):
    """
    Reserved units, which NetBox counts as used but which no drawing showed.
    """

    def setUp(self):
        self.rack = make_rack(self.site, u_height=20)
        self.user = User.objects.create_user('reserver', password='x')

    def reserve(self, units, description='Reserved'):
        return RackReservation.objects.create(rack=self.rack, units=units, user=self.user, description=description)

    def test_a_rack_with_no_reservations_has_no_bands(self):
        self.assertEqual(build_elevation(self.rack).reservations, [])

    def test_consecutive_units_merge_into_one_band(self):
        # NetBox stores a reservation as a list of units, which would draw as a stack of
        # separate stripes for what is really one claim.
        self.reserve([5, 6, 7])
        bands = build_elevation(self.rack).reservations
        self.assertEqual(len(bands), 1)
        self.assertEqual((bands[0].first_unit, bands[0].last_unit), (5, 7))

    def test_a_gap_starts_a_second_band(self):
        self.reserve([5, 6, 12])
        bands = build_elevation(self.rack).reservations
        self.assertEqual(len(bands), 2)

    def test_a_band_spans_the_height_of_its_units(self):
        self.reserve([5, 6, 7])
        band = build_elevation(self.rack).reservations[0]
        self.assertEqual((band.offset, band.units), (4, 3))

    def test_a_band_in_a_descending_rack_is_measured_from_its_lowest_unit(self):
        # U5 to U7 counted from the top of the cabinet: the band's bottom is U7, which has the
        # rack's other units below it.
        self.rack.desc_units = True
        self.rack.save()
        self.reserve([5, 6, 7])
        band = build_elevation(self.rack).reservations[0]
        self.assertEqual(band.offset, self.rack.u_height - 7)

    def test_a_single_unit_reads_as_one_unit(self):
        self.reserve([9])
        self.assertEqual(build_elevation(self.rack).reservations[0].label, 'U9 reserved')

    def test_the_description_travels_with_the_band(self):
        # "Damaged - DO NOT USE" is the whole reason to draw these.
        self.reserve([3], description='Damaged - DO NOT USE')
        band = build_elevation(self.rack).reservations[0]
        self.assertEqual(band.reservation.description, 'Damaged - DO NOT USE')
