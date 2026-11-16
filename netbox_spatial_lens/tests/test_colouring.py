"""
What every colouring shares: readings, bands, legends, the registry, and the rule that no data
is never good news.
"""

import copy

from django.conf import settings
from django.test import override_settings

from netbox_spatial_lens.colouring import (
    COMPLETION,
    NO_DATA_COLOUR,
    NO_DATA_KEY,
    NO_DATA_LABEL,
    NO_READING,
    UTILISATION,
    Band,
    Colouring,
    Level,
    Reading,
    Registry,
    Scale,
    registry,
)
from netbox_spatial_lens.tests.base import LensTestCase, extension, make_floor, make_rack

LOGGER = 'netbox.plugins.netbox_spatial_lens.colouring'


def colouring(fn=None, bands=(), name='x', level=Level.RACKS) -> Colouring:
    return Colouring(level, name, name.title(), fn or (lambda items, context: {}), bands=tuple(bands))


class ReadingTest(LensTestCase):
    def test_an_item_with_no_reading_is_no_data(self):
        rack = make_rack(self.site)
        reading = colouring().evaluate([rack])[rack.pk]
        self.assertIs(reading, NO_READING)
        self.assertFalse(reading.has_data)
        self.assertEqual((reading.colour, reading.label, reading.band), (NO_DATA_COLOUR, NO_DATA_LABEL, NO_DATA_KEY))

    def test_a_reading_of_nought_is_data(self):
        # Nought per cent and "nobody recorded it" must not collapse into the same answer.
        reading = UTILISATION.reading(0, '0%')
        self.assertTrue(reading.has_data)
        self.assertEqual(reading.gauge, 0)

    def test_a_reading_of_none_is_no_data(self):
        rack = make_rack(self.site)
        self.assertFalse(colouring(lambda racks, context: {rack.pk: None}).evaluate([rack])[rack.pk].has_data)

    def test_a_declared_band_gives_the_colour(self):
        rack = make_rack(self.site)
        bands = [Band('Low', '#111111'), Band('High', '#222222')]
        answer = colouring(lambda racks, context: {rack.pk: Reading('9 kW', band='high')}, bands)
        reading = answer.evaluate([rack])[rack.pk]
        self.assertEqual((reading.colour, reading.band, reading.label), ('#222222', 'high', '9 kW'))

    def test_a_band_that_is_not_declared_is_no_data_and_is_logged(self):
        rack = make_rack(self.site)
        answer = colouring(lambda racks, context: {rack.pk: Reading('?', band='typo')}, [Band('Low', '#111111')])
        with self.assertLogs(LOGGER, level='WARNING'):
            self.assertFalse(answer.evaluate([rack])[rack.pk].has_data)

    def test_labels_with_no_colour_get_distinct_ones(self):
        racks = [make_rack(self.site, name=f'R{i}') for i in range(3)]
        names = dict(zip((rack.pk for rack in racks), ('Acme', 'Globex', 'Acme'), strict=True))
        answer = colouring(lambda items, context: {pk: Reading(name) for pk, name in names.items()})
        readings = answer.evaluate(racks)
        first, second, third = (readings[rack.pk] for rack in racks)
        self.assertEqual(first.colour, third.colour)
        self.assertNotEqual(first.colour, second.colour)
        self.assertNotIn(NO_DATA_COLOUR, (first.colour, second.colour))
        self.assertEqual(first.band, 'Acme')

    def test_a_colour_given_is_kept_and_not_handed_to_another_label(self):
        racks = [make_rack(self.site, name=f'R{i}') for i in range(2)]
        given = {racks[0].pk: Reading('Edge', colour='#3f7fbf'), racks[1].pk: Reading('Core')}
        readings = colouring(lambda items, context: given).evaluate(racks)
        self.assertEqual(readings[racks[0].pk].colour, '#3f7fbf')
        self.assertNotEqual(readings[racks[1].pk].colour, '#3f7fbf')


class ScaleTest(LensTestCase):
    def test_a_number_falls_in_the_first_band_it_is_under(self):
        self.assertEqual([UTILISATION.band(n).key for n in (0, 49.9, 50, 89, 90, 140)], [
            'under-50', 'under-50', '50-to-74', '75-to-89', '90-and-over', '90-and-over',
        ])  # fmt: skip

    def test_a_reading_carries_its_band_and_its_gauge(self):
        reading = UTILISATION.reading(62, '62% of 8 kW')
        self.assertEqual((reading.band, reading.gauge, reading.label), ('50-to-74', 0.62, '62% of 8 kW'))

    def test_the_gauge_stays_between_empty_and_full(self):
        self.assertEqual(UTILISATION.reading(140, 'over').gauge, 1)

    def test_nought_and_one_hundred_are_bands_of_their_own_for_completion(self):
        # A rack with a single port cabled is not "nothing cabled", and one with a single port
        # left is not finished.
        self.assertEqual([COMPLETION.band(n).label for n in (0, 1, 99, 100)], [
            'Nothing cabled', 'Under 25%', '75 to 99%', 'Fully cabled',
        ])  # fmt: skip

    def test_a_scale_is_its_own_legend(self):
        scale = Scale((50, Band('Low', '#111111')), (None, Band('High', '#222222')))
        self.assertEqual([entry.label for entry in colouring(bands=scale).legend([])], ['Low', 'High', NO_DATA_LABEL])


class LegendTest(LensTestCase):
    def test_every_entry_carries_a_count(self):
        # The legend is usually read as a tally, so a colour without a number beside it is
        # only half the answer.
        entries = colouring(bands=[Band('Low', '#111111')]).legend([Reading('a', band='low'), Reading('b', band='low')])
        self.assertEqual((entries[0].count, entries[0].key), (2, 'low'))

    def test_a_band_nothing_falls_in_is_kept_with_a_zero(self):
        # The bands are the scale; a scale with gaps is harder to read than one with zeroes.
        self.assertEqual(colouring(bands=[Band('Low', '#111111')]).legend([])[0].count, 0)

    def test_the_no_data_entry_is_counted_and_is_last(self):
        entries = colouring().legend([NO_READING, NO_READING, Reading('Some', band='Some', colour='#111111')])
        self.assertEqual((entries[-1].label, entries[-1].count, entries[-1].key), (NO_DATA_LABEL, 2, NO_DATA_KEY))

    def test_a_categorical_colouring_builds_its_legend_from_the_drawing(self):
        # The bug this guards: role coloured four groups of racks and the legend read only
        # "No data", because the colouring declared none and none was derived.
        racks = [make_rack(self.site, name=f'R{i}') for i in range(4)]
        names = dict(zip((rack.pk for rack in racks), ('Storage', 'Compute', 'Compute', None), strict=True))
        answer = colouring(lambda items, context: {pk: Reading(name) for pk, name in names.items() if name})
        entries = answer.legend(answer.evaluate(racks).values())
        self.assertEqual([(e.label, e.count) for e in entries], [('Compute', 2), ('Storage', 1), (NO_DATA_LABEL, 1)])

    def test_two_names_sharing_a_colour_are_two_bands(self):
        # Two roles in NetBox can wear one colour. Keyed on the colour they were counted and
        # picked together: the legend said "2" beside each and one click selected both.
        racks = [make_rack(self.site, name=f'R{i}') for i in range(2)]
        given = {racks[0].pk: Reading('Compute', colour='#111111'), racks[1].pk: Reading('Storage', colour='#111111')}
        answer = colouring(lambda items, context: given)
        readings = answer.evaluate(racks)
        named = [(e.label, e.count, e.key) for e in answer.legend(readings.values())[:-1]]
        self.assertEqual(named, [('Compute', 1, 'Compute'), ('Storage', 1, 'Storage')])
        self.assertEqual(readings[racks[0].pk].band, 'Compute')


class ContextTest(LensTestCase):
    def test_the_function_is_told_where_it_is_asked(self):
        seen = {}

        def remember(racks, context):
            seen['context'] = context
            return {}

        floor = make_floor(self.site)
        colouring(remember).evaluate([], user='reader', scope=floor)
        context = seen['context']
        self.assertEqual((context.level, context.user, context.scope), (Level.RACKS, 'reader', floor))

    def test_visible_narrows_a_queryset_to_what_the_reader_may_view(self):
        from dcim.models import Rack
        from utilities.testing import create_test_user

        from netbox_spatial_lens.colouring import Context

        make_rack(self.site)
        reader = create_test_user()
        self.assertEqual(Context(Level.RACKS, user=reader).visible(Rack.objects.all()).count(), 0)
        self.assertEqual(Context(Level.RACKS).visible(Rack.objects.all()).count(), 1)


class BrokenColouringTest(LensTestCase):
    def test_a_colouring_that_raises_does_not_take_the_floor_down(self):
        def explode(racks, context):
            raise RuntimeError('boom')

        rack = make_rack(self.site)
        with self.assertLogs(LOGGER, level='ERROR'):
            readings = colouring(explode).evaluate([rack])
        self.assertFalse(readings[rack.pk].has_data)


class RegistryTest(LensTestCase):
    """
    One registry for the four levels. Built fresh here, because the real one is process-wide.
    """

    def setUp(self):
        super().setUp()
        self.registry = Registry()
        self.registry.builtin(colouring(name='one'))
        self.registry.builtin(colouring(name='two', bands=[Band('Black', '#000000')]))
        self.registry.builtin(colouring(name='map', level=Level.SITES))

    def _settings(self, **values):
        config = copy.deepcopy(settings.PLUGINS_CONFIG)
        config['netbox_spatial_lens'].update(values)
        return override_settings(PLUGINS_CONFIG=config)

    def names(self, level=Level.RACKS):
        return [c.name for c in self.registry.all(level)]

    def test_true_registers_every_builtin_of_the_level_in_order(self):
        with self._settings(builtin_rack_colourings=True):
            self.assertEqual(self.names(), ['one', 'two'])
            self.assertEqual(self.registry.get(Level.RACKS, 'two').bands[0].label, 'Black')
            self.assertEqual(self.names(Level.SITES), ['map'])

    def test_false_registers_none(self):
        with self._settings(builtin_rack_colourings=False):
            self.assertEqual(self.names(), [])

    def test_a_list_registers_the_named_ones_and_skips_an_unknown_name(self):
        with self._settings(builtin_rack_colourings=['two', 'typo']), self.assertLogs(LOGGER, 'WARNING'):
            self.assertEqual(self.names(), ['two'])

    def test_a_later_registration_replaces_an_earlier_one(self):
        with self._settings(builtin_rack_colourings=True), self.assertLogs(LOGGER, 'WARNING'):
            replaced = self.registry.register(colouring(name='one'))
            self.assertIs(self.registry.get(Level.RACKS, 'one'), replaced)
            self.assertEqual(len(self.names()), 2)

    def test_no_name_and_an_unknown_name_are_nothing(self):
        self.assertIsNone(self.registry.get(Level.RACKS, None))
        self.assertIsNone(self.registry.get(Level.RACKS, 'no-such-colouring'))

    def test_the_named_colouring_wins(self):
        with self._settings(default_rack_colouring='one'):
            self.assertEqual(self.registry.resolve(Level.RACKS, 'two').name, 'two')

    def test_an_unknown_name_and_no_name_fall_back_to_the_default(self):
        with self._settings(default_rack_colouring='two'):
            self.assertEqual(self.registry.resolve(Level.RACKS, 'no-such-thing').name, 'two')
            self.assertEqual(self.registry.resolve(Level.RACKS, None).name, 'two')

    def test_a_default_nothing_answers_to_falls_back_to_the_first_registered(self):
        # The case the map once missed: the default colouring switched off, or misspelt, while
        # others are still on offer.
        with self._settings(default_rack_colouring='no-such-default'):
            self.assertEqual(self.registry.resolve(Level.RACKS, None).name, 'one')

    def test_nothing_registered_is_none(self):
        with self._settings(builtin_rack_colourings=False):
            self.assertIsNone(self.registry.resolve(Level.RACKS, 'one'))


class DiscoveryTest(LensTestCase):
    """
    The `spatial_lens` module of an installed app is imported when the registry is first read.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(registry.reload)

    def test_a_colouring_declared_there_is_offered(self):
        source = (
            'from netbox_spatial_lens.extend import Level, Reading, colouring\n'
            "@colouring(Level.SITES, 'probe', label='Probe')\n"
            'def probe(sites, context):\n'
            "    return {site.pk: Reading('Seen') for site in sites}\n"
        )
        with extension(source):
            registry.reload()
        found = registry.get(Level.SITES, 'probe')
        self.assertIsNotNone(found)
        self.assertEqual(found.evaluate([self.site])[self.site.pk].label, 'Seen')

    def test_a_module_that_fails_is_logged_and_the_rest_still_load(self):
        with extension('raise RuntimeError("broken extension")'), self.assertLogs(LOGGER, 'ERROR'):
            registry.reload()
        self.assertIsNotNone(registry.get(Level.RACKS, 'power'))
