"""
Fill in the custom fields the examples in docs/extending.md colour by.

Creates the fields where they are missing, and gives a value only to an object that has none, so
a value set by hand for a capture stays. Seeded, so a run repeats.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from core.models import ObjectType
from dcim.models import Device, Rack, Site
from django.core.management.base import BaseCommand
from extras.models import CustomField, CustomFieldChoiceSet

TIERS = ('Tier 1', 'Tier 2', 'Tier 3')


def _field(name: str, label: str, field_type: str, model, choice_set=None) -> CustomField:
    field, _ = CustomField.objects.get_or_create(
        name=name, defaults={'label': label, 'type': field_type, 'choice_set': choice_set}
    )
    field.object_types.add(ObjectType.objects.get_for_model(model))
    return field


class Command(BaseCommand):
    help = 'Fill in the custom fields the extending examples colour by. Never overwrites a value.'

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=1, help='The random seed, so a run repeats (default: 1).')

    def handle(self, *args, **options):
        rng = random.Random(options['seed'])

        _field('heat_load_kw', 'Heat load (kW)', 'decimal', Rack)
        racks = [
            rack
            for rack in Rack.objects.filter(lens_placement__isnull=False, cooling_capacity__isnull=False)
            if rack.custom_field_data.get('heat_load_kw') is None
        ]
        for rack in racks:
            load = Decimal(str(rack.cooling_capacity)) * Decimal(str(rng.uniform(0.15, 1.0)))
            rack.custom_field_data['heat_load_kw'] = float(round(load, 1))
        Rack.objects.bulk_update(racks, ['custom_field_data'])
        self.stdout.write(f'heat_load_kw: {len(racks)} rack(s)')

        _field('support_end', 'Support ends', 'date', Device)
        devices = [
            device
            for device in Device.objects.filter(rack__isnull=False, position__isnull=False)
            if not device.custom_field_data.get('support_end')
        ]
        for device in devices:
            end = date.today() + timedelta(days=rng.randint(-400, 1500))
            device.custom_field_data['support_end'] = end.isoformat()
        Device.objects.bulk_update(devices, ['custom_field_data'])
        self.stdout.write(f'support_end: {len(devices)} device(s)')

        choice_set, _ = CustomFieldChoiceSet.objects.get_or_create(
            name='Service tiers', defaults={'extra_choices': [[tier, tier] for tier in TIERS]}
        )
        _field('service_tier', 'Service tier', 'select', Site, choice_set=choice_set)
        sites = [site for site in Site.objects.all() if not site.custom_field_data.get('service_tier')]
        for site in sites:
            site.custom_field_data['service_tier'] = rng.choices(TIERS, weights=(1, 3, 5))[0]
        Site.objects.bulk_update(sites, ['custom_field_data'])
        self.stdout.write(f'service_tier: {len(sites)} site(s)')
