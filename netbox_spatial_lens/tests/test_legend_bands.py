"""
Legend bands are keys, not colours, and the floor does not walk the same query twice.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext

from netbox_spatial_lens.overlays import (
    NO_DATA_KEY,
    LegendEntry,
    Overlay,
    RackValue,
    floor_space_utilisation,
)
from netbox_spatial_lens.tests.base import LensTestCase, make_rack


class LegendBandTest(LensTestCase):
    def test_two_names_sharing_a_colour_are_two_bands(self):
        # Two roles in NetBox can wear one colour. Keyed on the colour they were counted and
        # picked together: the legend said "2" beside each and one click selected both.
        overlay = Overlay('x', 'X', lambda racks: {})
        entries = overlay.legend_for([RackValue('#111', 'Compute', 'Compute'), RackValue('#111', 'Storage', 'Storage')])
        named = [(e.label, e.count, e.key) for e in entries[:-1]]
        self.assertEqual(named, [('Compute', 1, 'Compute'), ('Storage', 1, 'Storage')])

    def test_a_value_falls_in_the_band_its_legend_entry_names(self):
        overlay = Overlay('x', 'X', lambda racks: {})
        value = RackValue('#111', 'Compute', 'Compute')
        entry = overlay.legend_for([value])[0]
        self.assertEqual(overlay.band_of(value), entry.key)

    def test_a_declared_legend_keys_on_the_names_of_its_bands(self):
        # Placed by colour, named by label: a link that carries the band outlives the palette.
        overlay = Overlay('x', 'X', lambda racks: {}, legend=[LegendEntry('#111', '90% and over')])
        value = RackValue('#111', '95% used', 95)
        self.assertEqual(overlay.band_of(value), '90-and-over')
        entry = overlay.legend_for([value])[0]
        self.assertEqual((entry.key, entry.count), ('90-and-over', 1))

    def test_no_data_has_a_key_of_its_own(self):
        overlay = Overlay('x', 'X', lambda racks: {})
        self.assertEqual(overlay.band_of(RackValue()), NO_DATA_KEY)
        self.assertEqual(overlay.legend_for([RackValue()])[-1].key, NO_DATA_KEY)


class UtilisationReuseTest(LensTestCase):
    def test_the_second_ask_for_the_same_racks_costs_nothing(self):
        # The floor asks once for the overlay and once for the stat strip.
        racks = [make_rack(self.site, name='R1'), make_rack(self.site, name='R2')]
        first = floor_space_utilisation(racks)
        with CaptureQueriesContext(connection) as queries:
            second = floor_space_utilisation(racks)
        self.assertEqual(len(queries), 0)
        self.assertEqual(first, second)
