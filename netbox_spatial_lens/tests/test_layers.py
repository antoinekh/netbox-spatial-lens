"""
Background images under the racks.

The model's job is to hold one image and where it sits in the room; the view's job is to draw
the enabled ones, in order, beneath everything else.
"""

from django.core.exceptions import ValidationError
from django.urls import reverse
from utilities.testing import create_test_user

from netbox_spatial_lens.models import FloorLayer
from netbox_spatial_lens.tests.base import LensTestCase, make_floor, make_rack, place


class FloorLayerTest(LensTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.floor = make_floor(cls.site, width=20, depth=20)

    def layer(self, name='Plan', **kwargs):
        fields = {'external_url': 'https://example.invalid/plan.png', 'width': 2000, 'height': 2000}
        fields.update(kwargs)
        return FloorLayer.objects.create(floor=self.floor, name=name, **fields)

    def test_a_layer_needs_a_file_or_a_url(self):
        with self.assertRaises(ValidationError):
            FloorLayer(floor=self.floor, name='Empty', width=100, height=100).clean()

    def test_a_layer_cannot_have_both(self):
        # Two sources would leave the drawing to guess which one the operator meant.
        layer = FloorLayer(
            floor=self.floor,
            name='Both',
            file='netbox-spatial-lens/plan.png',
            external_url='https://example.invalid/plan.png',
            width=100,
            height=100,
        )
        with self.assertRaises(ValidationError):
            layer.clean()

    def test_a_layer_with_no_size_is_refused(self):
        for width, height in ((0, 100), (100, 0), (-50, 100)):
            layer = FloorLayer(
                floor=self.floor, name='Flat', external_url='https://example.invalid/p.png', width=width, height=height
            )
            with self.subTest(width=width, height=height), self.assertRaises(ValidationError):
                layer.full_clean()

    def test_the_source_is_wherever_the_image_lives(self):
        self.assertEqual(self.layer().source, 'https://example.invalid/plan.png')

    def test_the_centre_is_derived_from_the_corner_and_the_size(self):
        layer = self.layer(x=100, y=200, width=400, height=600)
        self.assertEqual((layer.centre_x, layer.centre_y), (300, 500))

    def test_layers_are_ordered_by_weight(self):
        self.layer(name='Photo', weight=200)
        self.layer(name='Drawing', weight=50)
        self.assertEqual([layer.name for layer in self.floor.layers.all()], ['Drawing', 'Photo'])


class FloorLayerViewTest(LensTestCase):
    """
    That the floor page actually draws them, and draws them under the racks.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.floor = make_floor(cls.site, width=20, depth=20)
        place(cls.floor, make_rack(cls.site, name='RA'))

    def setUp(self):
        self.user = create_test_user()
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)

    def floor_page(self, **params):
        url = reverse('plugins:netbox_spatial_lens:floor', args=[self.floor.pk])
        return self.client.get(url, params)

    def test_an_enabled_layer_is_drawn(self):
        FloorLayer.objects.create(
            floor=self.floor,
            name='Plan',
            external_url='https://example.invalid/plan.png',
            width=2000,
            height=2000,
        )
        body = self.floor_page().content.decode()
        self.assertIn('https://example.invalid/plan.png', body)
        # Under the racks, or the drawing hides the thing the page is about.
        self.assertLess(body.index('lens-layers'), body.index('lens-racks'))

    def test_a_disabled_layer_is_not(self):
        FloorLayer.objects.create(
            floor=self.floor,
            name='Old plan',
            external_url='https://example.invalid/old.png',
            width=100,
            height=100,
            enabled=False,
        )
        self.assertNotIn('https://example.invalid/old.png', self.floor_page().content.decode())

    def test_cable_runs_are_off_until_they_are_asked_for(self):
        self.assertNotIn('lens-floor-runs', self.floor_page().content.decode())
        self.assertIn('runs=1', self.floor_page().content.decode())


def _image_bytes(image_format: str) -> bytes:
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new('RGB', (4, 3), '#ffffff').save(out, format=image_format)
    return out.getvalue()


class LayerUploadTest(LensTestCase):
    """
    What a background layer will take as an upload: the raster images a browser draws, and
    nothing that NetBox's own address could serve as a page or as a script.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.floor = make_floor(cls.site, width=20, depth=20)

    def upload(self, name: str, content: bytes) -> FloorLayer:
        from django.core.files.uploadedfile import SimpleUploadedFile

        layer = FloorLayer(floor=self.floor, name=name, width=100, height=100)
        layer.file = SimpleUploadedFile(name, content)
        return layer

    def test_the_usual_image_formats_are_accepted(self):
        for name, image_format in (('plan.png', 'PNG'), ('photo.jpg', 'JPEG'), ('scan.webp', 'WEBP'), ('a.gif', 'GIF')):
            with self.subTest(name=name):
                self.upload(name, _image_bytes(image_format)).full_clean()

    def assert_file_refused(self, layer: FloorLayer) -> None:
        # On the file itself: a refusal for some other field would pass for the wrong reason.
        with self.assertRaises(ValidationError) as caught:
            layer.full_clean()
        self.assertEqual(list(caught.exception.message_dict), ['file'])

    def test_a_page_named_like_an_image_is_refused(self):
        self.assert_file_refused(self.upload('plan.png', b'<html><script>alert(1)</script></html>'))

    def test_an_svg_is_refused(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        self.assert_file_refused(self.upload('plan.svg', svg))

    def test_an_image_named_like_a_page_is_refused(self):
        # The web server picks the content type from the name, so this would be served as HTML.
        self.assert_file_refused(self.upload('plan.html', _image_bytes('PNG')))

    def test_a_layer_made_without_an_opacity_is_valid(self):
        # The default was the float 0.6, which the field's two-place rule refused.
        layer = FloorLayer(
            floor=self.floor,
            name='Plain',
            external_url='https://example.invalid/p.png',
            width=1,
            height=1,
        )
        layer.full_clean()

    def test_a_layer_stored_before_the_rule_stays_editable(self):
        layer = FloorLayer(
            floor=self.floor, name='Old', file='netbox-spatial-lens/floor-1/plan.svg', width=100, height=100
        )
        layer.full_clean()

    def test_the_demo_plan_is_a_png_of_the_room_shape(self):
        from io import BytesIO

        from PIL import Image

        from netbox_spatial_lens.management.commands.lens_enrich import Command

        with Image.open(BytesIO(Command()._plan_png(750, 1208, 17))) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.size, (1500, 2416))
