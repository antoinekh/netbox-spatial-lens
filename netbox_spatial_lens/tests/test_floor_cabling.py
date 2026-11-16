"""
The cables drawn across a floor.

The subject is the aggregation, not the drawing: one line per pair of racks, counting the
cables that actually leave a cabinet and ignoring the ones that never do.
"""

from netbox_spatial_lens.floor_cabling import build_floor_exits, build_floor_runs, cabling_facts, count_cables
from netbox_spatial_lens.layout import build_layout
from netbox_spatial_lens.tests.base import LensTestCase, cable, make_device, make_floor, make_rack, place


class FloorRunTest(LensTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.floor = make_floor(cls.site, width=20, depth=20)
        cls.rack_a = make_rack(cls.site, name='RA')
        cls.rack_b = make_rack(cls.site, name='RB')
        cls.rack_c = make_rack(cls.site, name='RC')
        for index, rack in enumerate((cls.rack_a, cls.rack_b, cls.rack_c)):
            place(cls.floor, rack, x=100 + index * 200, y=100)
        cls.a1 = make_device(cls.site, cls.rack_a, 'a1', cls.role, cls.manufacturer, interfaces=4)
        cls.a2 = make_device(cls.site, cls.rack_a, 'a2', cls.role, cls.manufacturer, position=3, interfaces=2)
        cls.b1 = make_device(cls.site, cls.rack_b, 'b1', cls.role, cls.manufacturer, interfaces=4)
        cls.c1 = make_device(cls.site, cls.rack_c, 'c1', cls.role, cls.manufacturer, interfaces=2)

    def placed(self):
        return build_layout(self.floor, None)

    def link(self, near, far, index=0):
        cable(near.interfaces.all()[index], far.interfaces.all()[index])

    def test_a_cable_between_two_racks_is_one_run(self):
        self.link(self.a1, self.b1)
        runs = build_floor_runs(self.placed())
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].count, 1)
        self.assertEqual({runs[0].a.rack, runs[0].b.rack}, {self.rack_a, self.rack_b})

    def test_many_cables_between_the_same_racks_stay_one_run(self):
        # The reason the aggregation exists: forty fibres must not be forty overlapping lines.
        for index in range(3):
            self.link(self.a1, self.b1, index=index)
        runs = build_floor_runs(self.placed())
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].count, 3)

    def test_a_cable_inside_one_rack_is_not_a_run(self):
        self.link(self.a1, self.a2)
        self.assertEqual(build_floor_runs(self.placed()), [])

    def test_each_pair_of_racks_gets_its_own_run(self):
        self.link(self.a1, self.b1)
        self.link(self.a2, self.c1)
        runs = build_floor_runs(self.placed())
        self.assertEqual(len(runs), 2)
        self.assertEqual(count_cables(runs), 2)

    def test_a_run_is_the_same_whichever_end_it_was_walked_from(self):
        self.link(self.a1, self.b1)
        self.link(self.b1, self.a1, index=1)
        runs = build_floor_runs(self.placed())
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].count, 2)

    def test_a_busier_run_is_drawn_thicker_and_last(self):
        for index in range(4):
            self.link(self.a1, self.b1, index=index)
        self.link(self.a2, self.c1)
        runs = build_floor_runs(self.placed())
        self.assertEqual([run.count for run in runs], [1, 4])
        self.assertGreater(runs[1].width, runs[0].width)

    def test_a_rack_says_what_it_is_cabled_to(self):
        self.link(self.a1, self.b1)
        self.link(self.a1, self.b1, index=1)
        self.link(self.a2, self.c1)
        facts = cabling_facts(build_floor_runs(self.placed()), [])
        self.assertEqual(facts[self.rack_a.pk], '3 cables to 2 racks')
        self.assertEqual(facts[self.rack_c.pk], '1 cable to 1 rack')

    def test_a_rack_nobody_placed_carries_no_run(self):
        unplaced = make_rack(self.site, name='RD')
        far = make_device(self.site, unplaced, 'd1', self.role, self.manufacturer, interfaces=1)
        self.link(self.a1, far)
        self.assertEqual(build_floor_runs(self.placed()), [])

    def test_one_rack_cannot_have_a_run(self):
        floor = make_floor(self.site, name='Lonely')
        place(floor, make_rack(self.site, name='RE'))
        self.assertEqual(build_floor_runs(build_layout(floor, None)), [])

    def test_the_query_count_does_not_grow_with_the_cabling(self):
        # The point of reading _rack_id off the termination rather than walking to the device.
        for index in range(4):
            self.link(self.a1, self.b1, index=index)
        placed = self.placed()
        with self.assertNumQueries(1):
            build_floor_runs(placed)


class FloorExitTest(LensTestCase):
    """
    The cabling that leaves the room, which is all the cabling a branch office has.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.floor = make_floor(cls.site, width=20, depth=20)
        cls.rack = make_rack(cls.site, name='RA')
        place(cls.floor, cls.rack, x=200, y=200)
        cls.device = make_device(cls.site, cls.rack, 'a1', cls.role, cls.manufacturer, interfaces=4)

    def circuit_end(self, cid='CID-1'):
        from circuits.models import Circuit, CircuitTermination, CircuitType, Provider

        provider, _ = Provider.objects.get_or_create(name='Acme Telecom', slug='acme-telecom')
        kind, _ = CircuitType.objects.get_or_create(name='Transit', slug='transit')
        circuit = Circuit.objects.create(cid=cid, provider=provider, type=kind, status='active')
        return CircuitTermination.objects.create(circuit=circuit, term_side='A', termination=self.site)

    def test_a_circuit_is_an_exit(self):
        cable(self.device.interfaces.all()[0], self.circuit_end())
        exits = build_floor_exits(build_layout(self.floor, None), self.floor)
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].kind, 'circuit')
        self.assertIn('CID-1', exits[0].label)
        self.assertIn('Acme Telecom', exits[0].label)

    def test_an_exit_ends_just_outside_a_wall(self):
        """
        Outside, not on.

        A rack standing near a wall is the one whose stub had nowhere to go: a cabinet 75 cm
        from the left wall drew a line shorter than itself, hidden underneath it, and the plan
        showed a dot against the wall joined to nothing. Crossing the wall is also the truer
        picture, since the far end of these cables is not in this room at all.
        """
        cable(self.device.interfaces.all()[0], self.circuit_end())
        exit_ = build_floor_exits(build_layout(self.floor, None), self.floor)[0]
        width, depth = self.floor.width_cm, self.floor.depth_cm
        outside = exit_.x < 0 or exit_.x > width or exit_.y < 0 or exit_.y > depth
        self.assertTrue(outside, f'{exit_.x},{exit_.y} is inside the room')
        # And not so far outside that it leaves the drawing: the plan's margin is what it ends
        # in, so the overshoot has to stay a small fraction of the room.
        margin = 0.1 * min(width, depth)
        self.assertLess(min(exit_.x, exit_.y), margin)
        self.assertLess(max(exit_.x - width, exit_.y - depth), margin)

    def test_cables_to_the_same_circuit_are_one_exit(self):
        end = self.circuit_end()
        cable(self.device.interfaces.all()[0], end)
        # A second circuit, so the rack has two destinations rather than two lines to one.
        cable(self.device.interfaces.all()[1], self.circuit_end(cid='CID-2'))
        exits = build_floor_exits(build_layout(self.floor, None), self.floor)
        self.assertEqual(len(exits), 2)
        self.assertEqual({e.count for e in exits}, {1})

    def test_two_exits_from_one_rack_do_not_land_on_the_same_point(self):
        cable(self.device.interfaces.all()[0], self.circuit_end())
        cable(self.device.interfaces.all()[1], self.circuit_end(cid='CID-2'))
        exits = build_floor_exits(build_layout(self.floor, None), self.floor)
        self.assertNotEqual((exits[0].x, exits[0].y), (exits[1].x, exits[1].y))

    def test_a_rack_on_another_floor_is_named_by_its_site_and_rack(self):
        elsewhere = make_rack(self.site, name='RZ')
        far = make_device(self.site, elsewhere, 'z1', self.role, self.manufacturer, interfaces=1)
        cable(self.device.interfaces.all()[0], far.interfaces.all()[0])
        exits = build_floor_exits(build_layout(self.floor, None), self.floor)
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].kind, 'rack')
        self.assertIn('RZ', exits[0].label)

    def test_a_far_end_in_no_rack_of_this_site_is_not_another_site(self):
        unracked = make_device(self.site, None, 'wall', self.role, self.manufacturer, position=None, interfaces=1)
        cable(self.device.interfaces.all()[0], unracked.interfaces.all()[0])
        exits = build_floor_exits(build_layout(self.floor, None), self.floor)
        self.assertEqual([item.kind for item in exits], ['other'])

    def test_a_far_end_in_no_rack_of_another_site_is_named_by_that_site(self):
        from dcim.models import Site

        branch = Site.objects.create(name='Branch', slug='branch')
        unracked = make_device(branch, None, 'far-wall', self.role, self.manufacturer, position=None, interfaces=1)
        cable(self.device.interfaces.all()[0], unracked.interfaces.all()[0])
        exits = build_floor_exits(build_layout(self.floor, None), self.floor)
        self.assertEqual([(item.kind, item.label) for item in exits], [('site', 'Branch')])

    def test_one_cable_to_a_rack_elsewhere_opens_that_cable(self):
        # The stub is a drawing of cabling, so clicking it has to land on cabling. It used to
        # go to the far rack's page, which answered a question nobody had asked of the line.
        elsewhere = make_rack(self.site, name='RZ')
        far = make_device(self.site, elsewhere, 'z1', self.role, self.manufacturer, interfaces=2)
        link = cable(self.device.interfaces.all()[0], far.interfaces.all()[0])
        exit_ = build_floor_exits(build_layout(self.floor, None), self.floor)[0]
        self.assertEqual(exit_.url, link.get_absolute_url())

    def test_several_cables_to_one_rack_open_exactly_those_cables(self):
        # One stub can stand for forty fibres. There is no single cable to open, so it opens
        # the list of the ones it drew, and nothing else on either rack.
        elsewhere = make_rack(self.site, name='RZ')
        far = make_device(self.site, elsewhere, 'z1', self.role, self.manufacturer, interfaces=2)
        links = [cable(self.device.interfaces.all()[i], far.interfaces.all()[i]) for i in range(2)]
        exit_ = build_floor_exits(build_layout(self.floor, None), self.floor)[0]
        self.assertEqual(exit_.count, 2)
        self.assertTrue(exit_.url.startswith('/dcim/cables/?'))
        for link in links:
            self.assertIn(f'id={link.pk}', exit_.url)

    def test_a_circuit_exit_still_opens_its_circuit(self):
        # The one stub whose label names something other than cabling. It reads "CID-1 (Acme
        # Telecom)", and clicking it goes where the label says.
        end = self.circuit_end()
        cable(self.device.interfaces.all()[0], end)
        exit_ = build_floor_exits(build_layout(self.floor, None), self.floor)[0]
        self.assertEqual(exit_.url, end.circuit.get_absolute_url())

    def test_cabling_that_stays_on_the_floor_is_not_an_exit(self):
        second = make_rack(self.site, name='RB')
        place(self.floor, second, x=600, y=200)
        far = make_device(self.site, second, 'b1', self.role, self.manufacturer, interfaces=1)
        cable(self.device.interfaces.all()[0], far.interfaces.all()[0])
        self.assertEqual(build_floor_exits(build_layout(self.floor, None), self.floor), [])

    def test_a_floor_with_no_cabling_has_no_exits(self):
        self.assertEqual(build_floor_exits(build_layout(self.floor, None), self.floor), [])

    def test_the_query_count_does_not_grow_with_the_cabling(self):
        for index in range(3):
            cable(self.device.interfaces.all()[index], self.circuit_end(cid=f'CID-{index}'))
        placed = build_layout(self.floor, None)
        with self.assertNumQueries(3):
            build_floor_exits(placed, self.floor)
