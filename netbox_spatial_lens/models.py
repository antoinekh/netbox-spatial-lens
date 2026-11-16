"""
Floor geometry.

NetBox knows a rack's height, footprint, power feeds and cooling capability. It does not know
where the rack stands in the room. These two models hold that, and nothing else: a `Floor` is
a room, and a `RackPlacement` is one rack standing in it.

Footprints are deliberately absent. A placement stores a position and an angle; how big the
rack is, is read from the rack itself at render time. That way a re-measured rack changes size
on the floor without anybody redrawing it, and the picture cannot disagree with the inventory.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from netbox.models import NetBoxModel, PrimaryModel

from netbox_spatial_lens.choices import MeasurementUnitChoices

__all__ = (
    'Floor',
    'FloorLayer',
    'RackPlacement',
)

# Centimetres per unit, for the two units a floor can be quoted in.
CM_PER_UNIT = {
    MeasurementUnitChoices.METRES: 100,
    MeasurementUnitChoices.FEET: 30.48,
}


# A room or an image with no size cannot be drawn: the plan's viewBox and every scale derived
# from it divide by these.
SMALLEST_ROOM = Decimal('0.01')
SMALLEST_LAYER = Decimal('0.1')


class Floor(PrimaryModel):
    """
    A room that racks stand in, bound to a site or to a location but never to both.

    A site with one room needs one floor bound to the site. A site with several rooms needs a
    floor per location. Both netbox-floorplan and NetBox Labs' Visual Explorer draw the line
    the same way, and a floor bound to both would leave two answers to "which floor is this
    rack on".
    """

    name = models.CharField(
        max_length=100,
        help_text='Identifies this floor. "Hall 1", "Suite B".',
    )
    site = models.ForeignKey(
        to='dcim.Site',
        on_delete=models.CASCADE,
        related_name='lens_floors',
        blank=True,
        null=True,
    )
    location = models.ForeignKey(
        to='dcim.Location',
        on_delete=models.CASCADE,
        related_name='lens_floors',
        blank=True,
        null=True,
    )
    width = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=(MinValueValidator(SMALLEST_ROOM),),
        help_text='Room width, in the unit below.',
    )
    depth = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=(MinValueValidator(SMALLEST_ROOM),),
        help_text='Room depth, in the unit below.',
    )
    unit = models.CharField(
        max_length=2,
        choices=MeasurementUnitChoices,
        default=MeasurementUnitChoices.METRES,
    )

    class Meta:
        ordering = ('site', 'location', 'name')
        constraints = (
            models.UniqueConstraint(
                fields=('site', 'name'),
                name='%(app_label)s_%(class)s_unique_site_name',
            ),
            models.UniqueConstraint(
                fields=('location', 'name'),
                name='%(app_label)s_%(class)s_unique_location_name',
            ),
        )
        verbose_name = 'floor'

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse('plugins:netbox_spatial_lens:floor', args=[self.pk])

    def clean(self) -> None:
        super().clean()
        if self.site and self.location:
            raise ValidationError('A floor belongs to a site or to a location, not to both.')
        if not self.site and not self.location:
            raise ValidationError('A floor must name either a site or a location.')

    @property
    def effective_site(self):
        """
        The site this floor is in, however it was bound.

        A placement is validated against this, so a floor bound to a location still refuses a
        rack from somewhere else entirely.
        """
        return self.site or (self.location.site if self.location else None)

    @staticmethod
    def in_site(site, queryset=None):
        """
        Every floor in a site, however each one was bound.

        A floor names a site or a location, never both, so "the rooms in this site" is two
        conditions rather than one. Written here because the world map, the site page and the
        level strip all ask it, and a version of it that forgot the location half is what made
        a site's other rooms unreachable from the map.
        """
        from django.db.models import Q

        floors = Floor.objects.all() if queryset is None else queryset
        return floors.filter(Q(site=site) | Q(location__site=site))

    def rack_locations(self):
        """
        The locations a rack on this floor may be in, or None where any in the site will do.

        A floor bound to a location takes the racks in that location and in the locations
        nested inside it, such as a cage within a hall. The unplaced-racks panel and the
        placement's own validation both read this, so what the panel offers is exactly what the
        API accepts.
        """
        if not self.location_id:
            return None
        return self.location.get_descendants(include_self=True)

    @property
    def width_cm(self) -> float:
        return float(self.width) * CM_PER_UNIT[self.unit]

    @property
    def depth_cm(self) -> float:
        return float(self.depth) * CM_PER_UNIT[self.unit]


class RackPlacement(NetBoxModel):
    """
    One rack standing on one floor.

    x and y are centimetres from the floor's top-left corner, to the centre of the rack.
    Measuring to the centre rather than to a corner means a rotation does not move the rack,
    which is what makes dragging and rotating feel right in the editor.

    Centimetres rather than a fraction of the room, because a room can be resized and the
    racks should not move; and integers of centimetres rather than floats, because a rack
    dragged back and forth should land on the same number it started from.
    """

    floor = models.ForeignKey(
        to='netbox_spatial_lens.Floor',
        on_delete=models.CASCADE,
        related_name='placements',
    )
    rack = models.OneToOneField(
        to='dcim.Rack',
        on_delete=models.CASCADE,
        related_name='lens_placement',
    )
    x = models.DecimalField(
        max_digits=8,
        decimal_places=1,
        help_text='Centimetres from the left edge, to the centre of the rack.',
    )
    y = models.DecimalField(
        max_digits=8,
        decimal_places=1,
        help_text='Centimetres from the top edge, to the centre of the rack.',
    )
    rotation = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(359.9)),
        help_text='Degrees clockwise. 0 faces the top of the plan.',
    )

    class Meta:
        ordering = ('floor', 'rack')
        verbose_name = 'rack placement'

    def __str__(self) -> str:
        return f'{self.rack} on {self.floor}'

    def get_absolute_url(self) -> str:
        return self.floor.get_absolute_url()

    def clean(self) -> None:
        super().clean()
        if not self.floor_id:
            return
        floor = self.floor

        if self.rack_id:
            floor_site = floor.effective_site
            if floor_site and self.rack.site_id != floor_site.pk:
                raise ValidationError(
                    {'rack': f'{self.rack} is at {self.rack.site}, but this floor is at {floor_site}.'}
                )
            # Two rooms in one site must not borrow each other's cabinets.
            locations = floor.rack_locations()
            if locations is not None and not locations.filter(pk=self.rack.location_id).exists():
                raise ValidationError({'rack': f'{self.rack} is not in {floor.location}, the location of this floor.'})

        # The centre of the rack stands in the room. The editor keeps it there; this keeps the
        # API and the forms to the same rule.
        errors = {}
        if self.x is not None and not 0 <= float(self.x) <= floor.width_cm:
            errors['x'] = f'Must be between 0 and {floor.width_cm:g} cm, the width of {floor}.'
        if self.y is not None and not 0 <= float(self.y) <= floor.depth_cm:
            errors['y'] = f'Must be between 0 and {floor.depth_cm:g} cm, the depth of {floor}.'
        if errors:
            raise ValidationError(errors)


# What a background layer may upload: the raster formats every browser draws. An SVG or a PDF
# is not among them. An SVG served from NetBox's own origin can carry script that runs when
# somebody opens its URL, and making it safe would need a sanitiser this plugin does not ship.
# Either one can still be exported to PNG, or linked with `external_url` from another host.
LAYER_IMAGE_FORMATS = {
    'PNG': ('png',),
    'JPEG': ('jpg', 'jpeg'),
    'WEBP': ('webp',),
    'GIF': ('gif',),
}


def validate_layer_image(file) -> None:
    """
    Accept a new upload only if it is a PNG, JPEG, WebP or GIF, by its content and its name.

    The content is read with Pillow, which NetBox already requires, so an HTML page renamed to
    `.png` is refused. The name is checked too, because the web server chooses the content type
    from the extension: a real PNG named `.html` would be served as a page.

    A file already in storage is not checked again. The layers uploaded before this rule, SVG
    plans among them, stay editable; only replacing their file applies the rule.
    """
    if getattr(file, '_committed', True):
        return

    from PIL import Image

    extension = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else ''
    try:
        file.seek(0)
        with Image.open(file) as image:
            found = image.format
            image.verify()
    except Exception:
        raise ValidationError('This file is not an image. Upload a PNG, JPEG, WebP or GIF.') from None
    finally:
        file.seek(0)

    if found not in LAYER_IMAGE_FORMATS:
        raise ValidationError(f'{found} images are not accepted. Upload a PNG, JPEG, WebP or GIF.')
    if extension not in LAYER_IMAGE_FORMATS[found]:
        raise ValidationError(f'This is a {found} image, so its name must end in .{LAYER_IMAGE_FORMATS[found][0]}.')


def layer_upload_path(instance, filename: str) -> str:
    """
    Where an uploaded background is stored.

    Namespaced by plugin and floor so two floors cannot collide on a filename, and so a floor's
    images can be found on disk without consulting the database.
    """
    return f'netbox-spatial-lens/floor-{instance.floor_id}/{filename}'


class FloorLayer(NetBoxModel):
    """
    A background image beneath the racks: an architectural drawing, a CAD export, a photograph.

    Placed in room centimetres rather than in pixels, which is what calibration means here:
    you say where the image's corners sit in the room, and it stretches to fit. That keeps the
    image and the racks in one coordinate system, so moving a rack never moves the drawing
    under it and resizing the room never silently rescales the image.

    Several layers can stack. `weight` orders them and `opacity` decides how much of each
    shows, which is how a floor plan is put under a photograph, or a rack grid over both.

    Raster images only: PNG, JPEG, WebP or GIF, see `validate_layer_image`. Rasterising a PDF
    on the server would mean a rendering dependency in a plugin whose whole shape is "no build
    step, no extra services", so the layer form converts a PDF to PNG in the browser, and the
    API and the import take an image or an `external_url`.
    """

    floor = models.ForeignKey(
        to='netbox_spatial_lens.Floor',
        on_delete=models.CASCADE,
        related_name='layers',
    )
    name = models.CharField(max_length=100)
    file = models.FileField(
        upload_to=layer_upload_path,
        blank=True,
        validators=(validate_layer_image,),
        help_text='PNG, JPEG, WebP or GIF. Export an SVG or a PDF to PNG, or link it below.',
    )
    external_url = models.URLField(
        max_length=500,
        blank=True,
        help_text='Serve the image from elsewhere instead of uploading it.',
    )

    x = models.DecimalField(
        max_digits=8,
        decimal_places=1,
        default=0,
        help_text="Centimetres from the room's left edge to the image's left edge.",
    )
    y = models.DecimalField(
        max_digits=8,
        decimal_places=1,
        default=0,
        help_text="Centimetres from the room's top edge to the image's top edge.",
    )
    width = models.DecimalField(
        max_digits=8,
        decimal_places=1,
        validators=(MinValueValidator(SMALLEST_LAYER),),
        help_text='How wide the image is, in room centimetres.',
    )
    height = models.DecimalField(
        max_digits=8,
        decimal_places=1,
        validators=(MinValueValidator(SMALLEST_LAYER),),
        help_text='How tall the image is, in room centimetres.',
    )
    rotation = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(359.9)),
        help_text='Degrees clockwise about the image centre.',
    )
    opacity = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        # A Decimal, not the float 0.6: the float is 0.59999…, which the field's own two-place
        # rule refuses, so a layer created without an opacity failed its own validation.
        default=Decimal('0.60'),
        validators=(MinValueValidator(0), MaxValueValidator(1)),
        help_text='0 is invisible, 1 is opaque. A background wants to sit under the racks.',
    )
    weight = models.PositiveSmallIntegerField(
        default=100, help_text='Drawing order. Lower is drawn first, and so sits underneath.'
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ('floor', 'weight', 'name')
        constraints = (
            models.UniqueConstraint(
                fields=('floor', 'name'),
                name='%(app_label)s_%(class)s_unique_floor_name',
            ),
        )
        verbose_name = 'background layer'

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return self.floor.get_absolute_url()

    def clean(self) -> None:
        super().clean()
        if bool(self.file) == bool(self.external_url):
            raise ValidationError('A layer needs either an uploaded file or an external URL, not both.')

    @property
    def source(self) -> str:
        """
        Where the browser should fetch this layer from.
        """
        if self.file:
            return self.file.url
        return self.external_url

    @property
    def centre_x(self) -> float:
        return float(self.x) + float(self.width) / 2

    @property
    def centre_y(self) -> float:
        return float(self.y) + float(self.height) / 2
