"""
What a floor and a placement will and will not accept.
"""

from dcim.models import Location, Site
from django.core.exceptions import ValidationError

from netbox_spatial_lens.models import Floor, RackPlacement
from netbox_spatial_lens.tests.base import LensTestCase, make_floor, make_rack


class FloorTest(LensTestCase):
    def test_a_floor_belongs_to_a_site_or_a_location_not_both(self):
        location = Location.objects.create(site=self.site, name='Hall', slug='hall')
        floor = Floor(name='Both', site=self.site, location=location, width=1, depth=1)
        with self.assertRaises(ValidationError):
            floor.clean()

    def test_a_floor_must_name_one_of_them(self):
        with self.assertRaises(ValidationError):
            Floor(name='Neither', width=1, depth=1).clean()

    def test_a_location_floor_knows_its_site(self):
        location = Location.objects.create(site=self.site, name='Hall', slug='hall')
        floor = Floor.objects.create(name='Hall floor', location=location, width=1, depth=1)
        self.assertEqual(floor.effective_site, self.site)

    def test_a_room_with_no_size_is_refused(self):
        for width, depth in ((0, 5), (5, 0), (-3, 5)):
            with self.subTest(width=width, depth=depth), self.assertRaises(ValidationError):
                Floor(name='Flat', site=self.site, width=width, depth=depth).full_clean()

    def test_dimensions_convert_to_centimetres(self):
        metric = make_floor(self.site, width=10, depth=5)
        self.assertEqual((metric.width_cm, metric.depth_cm), (1000, 500))

    def test_feet_convert_too(self):
        imperial = Floor.objects.create(name='Imperial', site=self.site, width=10, depth=10, unit='ft')
        self.assertAlmostEqual(imperial.width_cm, 304.8, places=1)


class RackPlacementTest(LensTestCase):
    def test_a_rack_from_another_site_is_refused(self):
        # Otherwise a floor plan could show a rack that is not in the building.
        elsewhere = Site.objects.create(name='Elsewhere', slug='elsewhere')
        floor = make_floor(self.site)
        stray = make_rack(elsewhere, name='Stray')
        with self.assertRaises(ValidationError):
            RackPlacement(floor=floor, rack=stray, x=0, y=0).clean()

    def test_a_rack_is_placed_once(self):
        from django.db.utils import IntegrityError

        floor = make_floor(self.site)
        second = make_floor(self.site, name='Second')
        rack = make_rack(self.site)
        RackPlacement.objects.create(floor=floor, rack=rack, x=0, y=0)
        with self.assertRaises(IntegrityError):
            RackPlacement.objects.create(floor=second, rack=rack, x=0, y=0)
