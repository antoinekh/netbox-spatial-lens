"""
The example in docs/extending.md runs, and does what the page says it does.

A documented example nobody runs is wrong by the next release. This reads the module out of the
page and imports it the way the plugin does, so a change that breaks the example breaks a test.
"""

import re
from datetime import date, timedelta
from pathlib import Path
from unittest import skipUnless

from dcim.models import Device, Site
from utilities.testing import create_test_user

from netbox_spatial_lens import extend
from netbox_spatial_lens.colouring import Level, registry
from netbox_spatial_lens.elevation import build_elevation
from netbox_spatial_lens.palette import STATUS_COLOURS
from netbox_spatial_lens.tests.base import (
    LensTestCase,
    extension,
    grant,
    make_device,
    make_rack,
    read,
    read_devices,
)

EXTENDING = Path(__file__).resolve().parents[2] / 'docs' / 'extending.md'
EXAMPLE = '# yourplugin/spatial_lens.py'


def _example() -> str:
    """The Python block in docs/extending.md that is the example module."""
    for block in re.findall(r'```python\n(.*?)```', EXTENDING.read_text(), flags=re.S):
        if block.startswith(EXAMPLE):
            return block
    raise AssertionError(f'no example starting with {EXAMPLE!r} in {EXTENDING}')


# The docs are in the repository, not in the installed package.
@skipUnless(EXTENDING.exists(), 'docs/extending.md is not shipped with the package')
class ExampleTestCase(LensTestCase):
    """
    The example, found as the `spatial_lens` module of an installed app, which is how a real one
    is found.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(registry.reload)
        with extension(_example()):
            registry.reload()


class HeatExampleTest(ExampleTestCase):
    def test_a_rack_with_both_values_is_gauged(self):
        rack = make_rack(self.site, name='Hot', cooling_capacity=10)
        rack.custom_field_data = {'heat_load_kw': 6}
        reading = read(Level.RACKS, 'heat', [rack])[rack.pk]
        self.assertEqual((reading.gauge, reading.band, reading.label), (0.6, '50-to-74', '6 of 10 kW'))
        self.assertEqual(reading.colour, extend.UTILISATION.band(60).colour)

    def test_a_rack_with_a_value_missing_is_no_data(self):
        no_load = make_rack(self.site, name='NoLoad', cooling_capacity=10)
        no_capacity = make_rack(self.site, name='NoCapacity')
        no_capacity.custom_field_data = {'heat_load_kw': 6}
        heat = registry.get(Level.RACKS, 'heat')
        readings = heat.evaluate([no_load, no_capacity])
        self.assertFalse(readings[no_load.pk].has_data)
        self.assertFalse(readings[no_capacity.pk].has_data)
        self.assertEqual(heat.legend(readings.values())[-1].count, 2)


class FailedExampleTest(ExampleTestCase):
    def setUp(self):
        super().setUp()
        self.rack = make_rack(self.site, name='Broken', u_height=10)
        self.other = make_rack(self.site, name='Sound', u_height=10)
        device = make_device(self.site, self.rack, 'dead', self.role, self.manufacturer)
        Device.objects.filter(pk=device.pk).update(status='failed')

    def test_a_rack_with_a_failed_device_names_it_in_its_card(self):
        readings = read(Level.RACKS, 'failed', [self.rack, self.other])
        broken, sound = readings[self.rack.pk], readings[self.other.pk]
        self.assertEqual((broken.band, broken.label, list(broken.facts)), ('some', '1 failed', [('Failed', 'dead')]))
        self.assertEqual((sound.band, sound.label), ('none', 'No failed device'))

    def test_a_device_the_reader_may_not_view_is_not_named(self):
        reader = create_test_user()
        grant(reader, 'dcim.rack')
        reading = read(Level.RACKS, 'failed', [self.rack], user=reader)[self.rack.pk]
        self.assertEqual(reading.band, 'none')


class SupportExampleTest(ExampleTestCase):
    def setUp(self):
        super().setUp()
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
        readings = read_devices('support', mounted)
        colours = {m.device.name: readings[m.device.pk].colour for m in mounted}
        self.assertEqual(
            colours,
            {'ended': STATUS_COLOURS['red'], 'ending': STATUS_COLOURS['orange'], 'supported': STATUS_COLOURS['green']},
        )

    def test_a_device_with_no_date_is_no_data_and_every_band_is_counted(self):
        mounted = self._mounted(ended=-1, ending=30, supported=800, unknown=None)
        legend = registry.get(Level.DEVICES, 'support').legend(read_devices('support', mounted).values())
        self.assertEqual([entry.count for entry in legend], [1, 1, 1, 1])
        self.assertEqual(legend[-1].label, 'No data')


class TierExampleTest(ExampleTestCase):
    def _site(self, name, tier):
        site = Site.objects.create(name=name, slug=name.lower())
        site.custom_field_data = {'service_tier': tier} if tier else {}
        return site

    def test_the_legend_has_one_band_per_tier_in_distinct_colours(self):
        sites = [self._site('Gold1', 'gold'), self._site('Gold2', 'gold'), self._site('Bronze', 'bronze')]
        tier = registry.get(Level.SITES, 'tier')
        legend = tier.legend(tier.evaluate(sites).values())
        self.assertEqual([(entry.label, entry.count) for entry in legend], [('bronze', 1), ('gold', 2), ('No data', 0)])
        self.assertEqual(len({entry.colour for entry in legend}), len(legend))

    def test_a_site_with_no_tier_is_no_data(self):
        site = self._site('Loose', None)
        self.assertFalse(read(Level.SITES, 'tier', [site])[site.pk].has_data)


class PublicInterfaceTest(ExampleTestCase):
    def test_the_example_imports_only_from_the_public_module(self):
        imported = re.findall(r'^from netbox_spatial_lens(\S*) import (.+)$', _example(), flags=re.M)
        self.assertEqual([module for module, _ in imported], ['.extend'])
        for name in imported[0][1].split(', '):
            self.assertIn(name, extend.__all__)

    def test_the_page_names_every_public_name(self):
        page = EXTENDING.read_text()
        for name in extend.__all__:
            self.assertIn(f'`{name}', page, f'{name} is public and docs/extending.md does not say what it is')
