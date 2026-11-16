"""
Shared fixtures for the test suite.

Nothing here declares a test. A class carrying its own tests must never be subclassed for its
fixture: Python re-runs every one of those tests under the subclass, which inflates the count
without covering anything new.

The fixtures build the smallest inventory each subject needs. A rack with two servers and a
PDU exercises the elevation, the cabling and the power chain; anything larger only makes a
failure harder to read.
"""

import types
from importlib import import_module
from unittest import mock

from core.models import ObjectType
from dcim.models import (
    Cable,
    Device,
    DeviceRole,
    DeviceType,
    Interface,
    Manufacturer,
    PowerFeed,
    PowerOutlet,
    PowerPanel,
    PowerPort,
    Rack,
    Site,
)
from django.apps import apps
from django.test import TestCase

from netbox_spatial_lens.colouring import Level, Reading, registry
from netbox_spatial_lens.models import Floor, RackPlacement

__all__ = (
    'LensTestCase',
    'cable',
    'extension',
    'grant',
    'make_device',
    'make_floor',
    'make_rack',
    'place',
    'power_feed',
    'read',
    'read_devices',
)


class LensTestCase(TestCase):
    """
    A site, a manufacturer and the roles every other fixture needs.
    """

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Test site', slug='test-site')
        cls.manufacturer = Manufacturer.objects.create(name='Acme', slug='acme')
        cls.role = DeviceRole.objects.create(name='Compute', slug='compute', color='2196f3')
        cls.switch_role = DeviceRole.objects.create(name='Access', slug='access', color='00bcd4')


def make_rack(site, name='R1', u_height=12, **kwargs):
    return Rack.objects.create(name=name, site=site, u_height=u_height, **kwargs)


def make_floor(site, name='Floor', width=10, depth=8):
    return Floor.objects.create(name=name, site=site, width=width, depth=depth)


def place(floor, rack, x=100, y=100, rotation=0):
    return RackPlacement.objects.create(floor=floor, rack=rack, x=x, y=y, rotation=rotation)


def make_device(
    site,
    rack,
    name,
    role,
    manufacturer,
    position=1,
    u_height=1,
    interfaces=0,
    power_ports=0,
    outlets=0,
    full_depth=True,
    face='front',
    model=None,
):
    """
    A device and the ports it needs, created directly rather than from templates.

    Templates are how NetBox builds a real device, and going through them here would make each
    fixture a device type plus a template per port for no gain: these tests care what ports
    exist, not how they came to.
    """
    device_type = DeviceType.objects.create(
        manufacturer=manufacturer,
        model=model or f'{name}-type',
        slug=f'{name}-type'.lower(),
        u_height=u_height,
        is_full_depth=full_depth,
    )
    device = Device.objects.create(
        name=name,
        device_type=device_type,
        role=role,
        site=site,
        rack=rack,
        position=position,
        face=face,
        status='active',
    )
    for i in range(interfaces):
        Interface.objects.create(device=device, name=f'eth{i}', type='1000base-t')
    for i in range(power_ports):
        PowerPort.objects.create(device=device, name=f'psu{i}', allocated_draw=100, maximum_draw=200)
    for i in range(outlets):
        PowerOutlet.objects.create(
            device=device,
            name=f'outlet{i}',
            power_port=PowerPort.objects.filter(device=device).first(),
        )
    return device


def cable(a, b):
    """
    One cable joining two terminations.

    Built through `a_terminations` and `b_terminations` rather than by creating
    `CableTermination` rows directly. Those are what make NetBox construct the `CablePath`
    behind the cable, and without a path nothing can be traced: the link exists, the drawing
    shows it, and `trace()` returns nothing at all.
    """
    link = Cable(status='connected', a_terminations=[a], b_terminations=[b])
    link.save()
    return link


def power_feed(rack, name='feed', amperage=16, voltage=230, max_utilization=80):
    panel = PowerPanel.objects.create(site=rack.site, name=f'{name}-panel')
    return PowerFeed.objects.create(
        power_panel=panel,
        rack=rack,
        name=name,
        amperage=amperage,
        voltage=voltage,
        max_utilization=max_utilization,
        status='active',
    )


def grant(user, model: str, actions=('view',), constraints=None) -> None:
    """
    One NetBox object permission, for a test that reads as a permission question.

    `model` is 'app_label.model'. `constraints` are NetBox's own object-level constraints, so
    a test can grant a user one rack of two and assert the other is nowhere on the page.
    """
    from users.models import ObjectPermission

    app, name = model.split('.')
    permission = ObjectPermission.objects.create(
        name=f'{model} {"-".join(actions)}', actions=list(actions), constraints=constraints or None
    )
    permission.users.add(user)
    permission.object_types.add(ObjectType.objects.get(app_label=app, model=name))


def read(level: Level, name: str, items, **context) -> dict[int, Reading]:
    """
    What the registered colouring `name` says of `items`, by item id.
    """
    return registry.get(level, name).evaluate(items, **context)


def read_devices(name: str, mounted) -> dict[int, Reading]:
    """
    What a device colouring says of the mounted devices of an elevation, by device id.
    """
    devices = [m.device for m in mounted]
    return read(Level.DEVICES, name, devices, mounted={m.device.pk: m for m in mounted})


def extension(source: str):
    """
    A patch under which this plugin has a `spatial_lens` module that runs `source` on import.

    The registry then finds it the way it finds the module of a real plugin. Reload the registry
    inside the patch, and again when the test ends.
    """
    app = apps.get_app_config('netbox_spatial_lens')

    def fake_import(name: str):
        if name != f'{app.name}.spatial_lens':
            return import_module(name)
        module = types.ModuleType(name)
        exec(source, module.__dict__)
        return module

    return mock.patch.multiple(
        'netbox_spatial_lens.colouring',
        import_module=fake_import,
        module_has_submodule=lambda package, name: package is app.module,
    )
