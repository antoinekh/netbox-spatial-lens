"""
What the plan draws beyond the racks themselves: the scale, the labels, the gauge and the
headline figures.

All pure functions over the ORM, so none of it needs a browser. The rules being guarded here
are the ones a screenshot would catch and a unit test usually would not: that one drawing has
one type size, that a band alone never has to carry a magnitude, and that the figures above the
plan agree with the colours on it.
"""

from netbox_spatial_lens.colouring import Colouring, Level, registry
from netbox_spatial_lens.elevation import build_elevation, rack_summary
from netbox_spatial_lens.geometry import metre_step, metre_ticks, size_labels
from netbox_spatial_lens.layout import build_layout, build_layouts, floor_summary
from netbox_spatial_lens.rack_colourings import floor_space_utilisation
from netbox_spatial_lens.tests.base import (
    LensTestCase,
    make_device,
    make_floor,
    make_rack,
    place,
)


class MetreScaleTest(LensTestCase):
    def test_a_small_room_is_ruled_every_metre(self):
        self.assertEqual(metre_step(800), 1)

    def test_a_large_room_opens_the_step_up(self):
        # A thirty-metre hall ruled every metre is a mesh, not a scale.
        self.assertEqual(metre_step(3000), 5)
        self.assertEqual(metre_step(20000), 20)

    def test_the_step_never_gives_more_than_twelve_rules(self):
        for extent in (500, 1247, 4000, 9000, 30000):
            self.assertLessEqual(len(metre_ticks(extent, metre_step(extent))), 13)

    def test_ticks_are_whole_metres_in_centimetres(self):
        self.assertEqual(metre_ticks(350, 1), [(0.0, '0'), (100.0, '1'), (200.0, '2'), (300.0, '3')])

    def test_both_edges_can_share_one_step(self):
        # The reason the step is a separate function: derived per axis it gave a room ruled
        # every metre across and every two metres down, which is a drawing at two scales.
        step = metre_step(1247)
        across = metre_ticks(850, step)
        down = metre_ticks(1247, step)
        self.assertEqual(across[1][0] - across[0][0], down[1][0] - down[0][0])


class LabelSizingTest(LensTestCase):
    _floors = 0

    def _placed(self, *specs):
        # A name per call: a floor is unique per site and name, and two calls in one test
        # would otherwise collide rather than build a second floor.
        LabelSizingTest._floors += 1
        floor = make_floor(self.site, name=f'Floor {LabelSizingTest._floors}', width=30, depth=30)
        for index, (name, width, depth) in enumerate(specs):
            rack = make_rack(
                self.site,
                name=f'{name}-{LabelSizingTest._floors}',
                outer_width=width,
                outer_depth=depth,
                outer_unit='mm',
            )
            place(floor, rack, x=100 + index * 200, y=100)
        return build_layout(floor, None)

    def test_every_rack_on_a_floor_gets_the_same_size(self):
        # One drawing, one type size. Sized per rack it put a long name at four pixels beside
        # a short one at nineteen, which reads as a broken plan rather than as a long name.
        placed = self._placed(('R1', 600, 1070), ('R2-a-very-long-name', 600, 1070))
        self.assertEqual(len({p.label_size for p in placed}), 1)

    def test_the_smallest_cabinet_sets_the_size(self):
        wide = self._placed(('R1', 900, 1200), ('R2', 900, 1200))
        mixed = self._placed(('R1', 900, 1200), ('R2', 400, 600))
        self.assertLess(mixed[0].label_size, wide[0].label_size)

    def test_a_name_too_long_for_its_cabinet_is_trimmed(self):
        placed = self._placed(('R1', 600, 1070), ('EU-London-Hall-2-R01', 600, 1070))
        long_one = next(p for p in placed if p.rack.name.startswith('EU-London'))
        self.assertNotEqual(long_one.display_name, long_one.rack.name)
        self.assertTrue(long_one.display_name.endswith('…'))

    def test_a_name_that_fits_is_left_alone(self):
        placed = self._placed(('R1', 600, 1070))
        self.assertEqual(placed[0].display_name, placed[0].rack.name)

    def test_an_empty_floor_does_not_raise(self):
        size_labels([])


class GaugeTest(LensTestCase):
    """
    A band alone cannot tell 12% from 48%. The gauge carries what the band rounds away, and
    only for a colouring that measures a quantity.
    """

    def setUp(self):
        self.floor = make_floor(self.site, width=10, depth=10)
        self.rack = make_rack(self.site, u_height=10)
        make_device(self.site, self.rack, 'srv', self.role, self.manufacturer, position=1, u_height=4)
        place(self.floor, self.rack)

    def test_a_quantitative_colouring_yields_a_fraction(self):
        placed = build_layout(self.floor, registry.get(Level.RACKS, 'space'))
        self.assertAlmostEqual(placed[0].fraction, 0.4, places=2)
        self.assertEqual(placed[0].gauge_label, '40%')

    def test_a_categorical_colouring_yields_none(self):
        # A role is a name, not a magnitude, so there is nothing to draw a gauge of.
        self.rack.role = None
        placed = build_layout(self.floor, registry.get(Level.RACKS, 'role'))
        self.assertIsNone(placed[0].fraction)
        self.assertEqual(placed[0].gauge_label, '')

    def test_a_rack_the_colouring_cannot_measure_yields_none(self):
        rack = make_rack(self.site, name='R2')
        place(self.floor, rack, x=500, y=500)
        placed = {p.rack.name: p for p in build_layout(self.floor, registry.get(Level.RACKS, 'power'))}
        self.assertIsNone(placed['R2'].fraction)

    def test_the_fill_never_runs_past_its_track(self):
        placed = build_layout(self.floor, registry.get(Level.RACKS, 'space'))[0]
        self.assertLessEqual(placed.gauge_width, placed.gauge_track_width)
        self.assertGreaterEqual(placed.gauge_width, 0)


class SeveralFloorsTest(LensTestCase):
    """
    Several rooms read together, as the site page draws them.
    """

    def setUp(self):
        self.hall = make_floor(self.site, name='Hall')
        self.cage = make_floor(self.site, name='Cage')
        self.empty = make_floor(self.site, name='Empty')
        place(self.hall, make_rack(self.site, name='H1'))
        place(self.cage, make_rack(self.site, name='C1'))

    def test_each_floor_gets_its_own_racks(self):
        layouts = build_layouts([self.hall, self.cage, self.empty], None)
        self.assertEqual([p.rack.name for p in layouts[self.hall.pk]], ['H1'])
        self.assertEqual([p.rack.name for p in layouts[self.cage.pk]], ['C1'])
        self.assertEqual(layouts[self.empty.pk], [])

    def test_a_colouring_is_handed_one_room_at_a_time(self):
        # Extending promises a colouring the racks on the floor. Handed every room at once, one
        # that compares the racks in a room would silently compare across the site.
        seen = []

        def probe(racks, context):
            seen.append({rack.name for rack in racks})

        colouring = Colouring(Level.RACKS, 'probe', 'Probe', probe)
        build_layouts([self.hall, self.cage], colouring)
        self.assertCountEqual(seen, [{'H1'}, {'C1'}])


class SpaceUtilisationTest(LensTestCase):
    """
    The bulk walk must give the same answer as NetBox's own per-rack one. It exists only to be
    cheaper, and a cheaper figure that disagrees is worse than an expensive one.
    """

    def test_it_agrees_with_netbox(self):
        rack = make_rack(self.site, u_height=20)
        make_device(self.site, rack, 'a', self.role, self.manufacturer, position=1, u_height=2)
        make_device(self.site, rack, 'b', self.role, self.manufacturer, position=10, u_height=4)
        used, total = floor_space_utilisation([rack])[rack.pk]
        self.assertEqual(total, 20)
        self.assertAlmostEqual(used / total * 100, float(rack.get_utilization()), places=1)

    def test_a_reserved_unit_counts_as_used(self):
        from dcim.models import RackReservation
        from django.contrib.auth import get_user_model

        rack = make_rack(self.site, u_height=10)
        user = get_user_model().objects.create(username='reserver')
        RackReservation.objects.create(rack=rack, units=[3, 4], user=user, description='held')
        used, total = floor_space_utilisation([rack])[rack.pk]
        self.assertEqual((used, total), (2, 10))

    def test_a_unit_both_reserved_and_filled_is_counted_once(self):
        # The bug this guards: summing the two lists put R101 a unit ahead of NetBox's own
        # figure, which is exactly the sort of drift that makes a plan untrusted.
        from dcim.models import RackReservation
        from django.contrib.auth import get_user_model

        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'a', self.role, self.manufacturer, position=3, u_height=1)
        user = get_user_model().objects.create(username='reserver')
        RackReservation.objects.create(rack=rack, units=[3], user=user, description='held')
        used, _ = floor_space_utilisation([rack])[rack.pk]
        self.assertEqual(used, 1)
        self.assertAlmostEqual(used / 10 * 100, float(rack.get_utilization()), places=1)

    def test_a_rack_with_no_height_is_absent(self):
        self.assertEqual(floor_space_utilisation([make_rack(self.site, u_height=0)]), {})

    def test_it_costs_a_bounded_number_of_queries(self):
        # The point of the function. Per rack it was three queries, so a floor of twenty-six
        # spent seventy-nine where the power colouring beside it spent seven.
        racks = [make_rack(self.site, name=f'R{i}', u_height=10) for i in range(12)]
        with self.assertNumQueries(2):
            floor_space_utilisation(racks)


class FreeBandTest(LensTestCase):
    """
    What will fit is the question a rack drawing is asked most and answered least: the empty
    two thirds of a half-filled cabinet was drawn as nothing at all.
    """

    def setUp(self):
        self.rack = make_rack(self.site, u_height=10)

    def test_an_empty_rack_is_one_band(self):
        bands = build_elevation(self.rack).free
        self.assertEqual(len(bands), 1)
        self.assertEqual(bands[0].units, 10)
        self.assertEqual(bands[0].label, '10U free')

    def test_a_device_splits_the_space_into_two_bands(self):
        make_device(self.site, self.rack, 'srv', self.role, self.manufacturer, position=5, u_height=2)
        bands = sorted(build_elevation(self.rack).free, key=lambda b: b.first_unit)
        self.assertEqual([b.units for b in bands], [4, 4])

    def test_a_full_rack_has_no_bands(self):
        make_device(self.site, self.rack, 'srv', self.role, self.manufacturer, position=1, u_height=10)
        self.assertEqual(build_elevation(self.rack).free, [])

    def test_a_single_free_unit_is_drawn_but_not_labelled(self):
        # There is no room for the text, and "1U" beside a 1U gap says nothing the gap has not.
        make_device(self.site, self.rack, 'a', self.role, self.manufacturer, position=1, u_height=1)
        make_device(self.site, self.rack, 'b', self.role, self.manufacturer, position=3, u_height=8)
        band = next(b for b in build_elevation(self.rack).free if b.units == 1)
        self.assertEqual(band.label, '')

    def test_the_bands_and_the_free_figure_agree(self):
        make_device(self.site, self.rack, 'srv', self.role, self.manufacturer, position=5, u_height=2)
        elevation = build_elevation(self.rack)
        self.assertEqual(sum(b.units for b in elevation.free), elevation.space['free'])


class SummaryTest(LensTestCase):
    def test_a_floor_reports_its_racks_devices_space_and_power(self):
        floor = make_floor(self.site, width=10, depth=10)
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer, position=1, u_height=2)
        place(floor, rack)
        stats = {s.label: s for s in floor_summary(floor, build_layout(floor, None))}
        self.assertEqual(stats['Racks'].value, '1')
        self.assertEqual(stats['Devices'].value, '1')
        self.assertEqual(stats['Space'].value, '20%')
        self.assertIn('8U free of 10', stats['Space'].detail)

    def test_a_floor_with_no_feeds_says_so_rather_than_reporting_nought(self):
        # The rule the whole plugin turns on: nothing recorded must never read as nothing
        # wrong. A power figure of 0% on an unmeasured floor is a clean bill of health.
        floor = make_floor(self.site, width=10, depth=10)
        place(floor, make_rack(self.site))
        stats = {s.label: s for s in floor_summary(floor, build_layout(floor, None))}
        self.assertEqual(stats['Power'].value, '—')
        self.assertEqual(stats['Power'].detail, 'no feeds recorded')

    def test_an_empty_floor_reports_nothing(self):
        floor = make_floor(self.site, width=10, depth=10)
        self.assertEqual(floor_summary(floor, []), [])

    def test_a_rack_reports_its_devices_space_cabling_and_ports(self):
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'srv', self.role, self.manufacturer, position=1, u_height=2, interfaces=4)
        stats = {s.label: s for s in rack_summary(build_elevation(rack))}
        self.assertEqual(stats['Devices'].value, '1')
        self.assertEqual(stats['Free space'].value, '8U')
        self.assertEqual(stats['Free ports'].value, '4')
        self.assertEqual(stats['Cabling'].value, '0')

    def test_the_largest_gap_is_reported_not_just_the_total(self):
        # "30U free" spread over ten gaps of three will not take a 4U chassis, and only the
        # second number says so.
        rack = make_rack(self.site, u_height=10)
        make_device(self.site, rack, 'a', self.role, self.manufacturer, position=5, u_height=1)
        stats = {s.label: s for s in rack_summary(build_elevation(rack))}
        self.assertEqual(stats['Free space'].value, '9U')
        self.assertIn('largest gap 5U', stats['Free space'].detail)
