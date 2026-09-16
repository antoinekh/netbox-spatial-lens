"""
The examples in docs/extending.md run, and do what the page says they do.

A documented example nobody runs is wrong by the next release. This reads the code blocks out of
the page and runs them, so a change that breaks an example breaks a test.
"""

import re
from datetime import date, timedelta
from pathlib import Path
from unittest import skipUnless

from dcim.models import Device, Site

from netbox_spatial_lens.device_overlays import DeviceOverlay
from netbox_spatial_lens.elevation import build_elevation
from netbox_spatial_lens.overlays import UTILISATION_LEGEND, Overlay
from netbox_spatial_lens.palette import STATUS_COLOURS, utilisation_colour
from netbox_spatial_lens.site_overlays import SiteOverlay
from netbox_spatial_lens.tests.base import LensTestCase, make_device, make_rack

EXTENDING = Path(__file__).resolve().parents[2] / 'docs' / 'extending.md'


def _example(first_line: str) -> str:
    """The Python block in docs/extending.md that starts with `first_line`."""
    for block in re.findall(r'```python\n(.*?)```', EXTENDING.read_text(), flags=re.S):
        if block.startswith(first_line):
            return block
    raise AssertionError(f'no example starting with {first_line!r} in {EXTENDING}')


def _run(first_line: str) -> dict:
    """The names the example starting with `first_line` defines."""
    namespace = {}
    exec(_example(first_line), namespace)
    return namespace


# The docs are in the repository, not in the installed package.
@skipUnless(EXTENDING.exists(), 'docs/extending.md is not shipped with the package')
class HeatExampleTest(LensTestCase):
    def setUp(self):
        self.heat_overlay = _run('# yourplugin/lens.py')['heat_overlay']

    def test_a_rack_with_both_values_is_gauged(self):
        rack = make_rack(self.site, name='Hot', cooling_capacity=10)
        rack.custom_field_data = {'heat_load_kw': 6}
        value = self.heat_overlay([rack])[rack.pk]
        self.assertEqual(value.value, 60)
        self.assertEqual(value.colour, utilisation_colour(60))
        self.assertEqual(value.label, '6 of 10 kW')

    def test_a_rack_with_a_value_missing_is_no_data(self):
        no_load = make_rack(self.site, name='NoLoad', cooling_capacity=10)
        no_capacity = make_rack(self.site, name='NoCapacity')
        no_capacity.custom_field_data = {'heat_load_kw': 6}
        overlay = Overlay('heat', 'Heat', self.heat_overlay, legend=UTILISATION_LEGEND)
        values = overlay.evaluate([no_load, no_capacity])
        self.assertFalse(values[no_load.pk].has_data)
        self.assertFalse(values[no_capacity.pk].has_data)
        self.assertEqual(overlay.legend_for(values.values())[-1].count, 2)


@skipUnless(EXTENDING.exists(), 'docs/extending.md is not shipped with the package')
class SupportExampleTest(LensTestCase):
    def setUp(self):
        example = _run('# yourplugin/support.py')
        self.support_overlay = example['support_overlay']
        self.legend = example['SUPPORT_LEGEND']
        self.rack = make_rack(self.site, u_height=10)

    def _mounted(self, **support_end):
        """The rack's mounted devices, one per name, each with its `support_end`, or none for None."""
        for position, (name, days) in enumerate(support_end.items(), start=1):
            device = make_device(self.site, self.rack, name, self.role, self.manufacturer, position=position)
            data = {} if days is None else {'support_end': (date.today() + timedelta(days=days)).isoformat()}
            Device.objects.filter(pk=device.pk).update(custom_field_data=data)
        return build_elevation(self.rack).devices

    def test_each_device_falls_in_its_band(self):
        mounted = self._mounted(ended=-1, ending=30, supported=800)
        values = self.support_overlay(mounted)
        colours = {m.device.name: values[m.device.pk].colour for m in mounted}
        self.assertEqual(
            colours,
            {'ended': STATUS_COLOURS['red'], 'ending': STATUS_COLOURS['orange'], 'supported': STATUS_COLOURS['green']},
        )

    def test_a_device_with_no_date_is_no_data_and_every_band_is_counted(self):
        mounted = self._mounted(ended=-1, ending=30, supported=800, unknown=None)
        overlay = DeviceOverlay('support', 'Support', self.support_overlay, legend=self.legend)
        values = overlay.evaluate(mounted)
        legend = overlay.legend_for(values.values())
        self.assertEqual([entry.count for entry in legend], [1, 1, 1, 1])
        self.assertEqual(legend[-1].label, 'No data')


@skipUnless(EXTENDING.exists(), 'docs/extending.md is not shipped with the package')
class TierExampleTest(LensTestCase):
    def setUp(self):
        self.tier_overlay = _run('# yourplugin/tiers.py')['tier_overlay']

    def _site(self, name, tier):
        site = Site.objects.create(name=name, slug=name.lower())
        site.custom_field_data = {'service_tier': tier} if tier else {}
        return site

    def test_the_legend_has_one_band_per_tier_in_distinct_colours(self):
        sites = [self._site('Gold1', 'gold'), self._site('Gold2', 'gold'), self._site('Bronze', 'bronze')]
        overlay = SiteOverlay('tier', 'Tier', self.tier_overlay)
        legend = overlay.legend_for(overlay.evaluate(sites).values())
        self.assertEqual([(entry.label, entry.count) for entry in legend], [('bronze', 1), ('gold', 2), ('No data', 0)])
        self.assertEqual(len({entry.colour for entry in legend}), len(legend))

    def test_a_site_with_no_tier_is_no_data(self):
        site = self._site('Loose', None)
        values = SiteOverlay('tier', 'Tier', self.tier_overlay).evaluate([site])
        self.assertFalse(values[site.pk].has_data)


@skipUnless(EXTENDING.exists(), 'docs/extending.md is not shipped with the package')
class RegistrationExampleTest(LensTestCase):
    def test_the_registration_example_names_real_functions(self):
        from netbox_spatial_lens import device_overlays, overlays, site_overlays

        registration = _example('# yourplugin/__init__.py')
        for module, name in (
            (overlays, 'register_overlay'),
            (overlays, 'UTILISATION_LEGEND'),
            (device_overlays, 'register_device_overlay'),
            (site_overlays, 'register_site_overlay'),
        ):
            self.assertIn(f'from {module.__name__} import', registration)
            self.assertIn(name, registration)
            self.assertIn(name, module.__all__, f'{name} is not exported by {module.__name__}')

    def test_the_registration_example_imports_what_the_examples_define(self):
        registration = _example('# yourplugin/__init__.py')
        for first_line, module, names in (
            ('# yourplugin/lens.py', 'lens', ('heat_overlay',)),
            ('# yourplugin/support.py', 'support', ('SUPPORT_LEGEND', 'support_overlay')),
            ('# yourplugin/tiers.py', 'tiers', ('tier_overlay',)),
        ):
            example = _run(first_line)
            self.assertIn(f'from .{module} import {", ".join(names)}', registration)
            for name in names:
                self.assertIn(name, example)
