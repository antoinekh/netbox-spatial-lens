from dcim.models import Location, Rack, Site
from django import forms
from netbox.forms import (
    NetBoxModelBulkEditForm,
    NetBoxModelFilterSetForm,
    NetBoxModelForm,
    NetBoxModelImportForm,
)
from utilities.forms import BOOLEAN_WITH_BLANK_CHOICES
from utilities.forms.fields import (
    CommentField,
    CSVChoiceField,
    CSVModelChoiceField,
    DynamicModelChoiceField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet
from utilities.forms.widgets import BulkEditNullBooleanSelect

from netbox_spatial_lens.choices import MeasurementUnitChoices
from netbox_spatial_lens.models import Floor, FloorLayer, RackPlacement

__all__ = (
    'FloorBulkEditForm',
    'FloorFilterForm',
    'FloorForm',
    'FloorImportForm',
    'FloorLayerFilterForm',
    'FloorLayerForm',
    'FloorLayerImportForm',
    'RackPlacementBulkEditForm',
    'RackPlacementFilterForm',
    'RackPlacementForm',
    'RackPlacementImportForm',
)


class FloorBindingMixin:
    """
    Keeps the location when a floor names both a site and one of its locations.

    The site narrows the location list, so choosing a site and then one of its locations is the
    ordinary way to bind a floor to a location. The model takes one or the other, so the site is
    dropped here rather than the form being refused for being filled in as asked.
    """

    def clean(self):
        # NetBoxModelForm.clean() returns nothing, so the data is read off the form.
        super().clean()
        site, location = self.cleaned_data.get('site'), self.cleaned_data.get('location')
        if site and location:
            if location.site_id != site.pk:
                raise forms.ValidationError({'location': f'{location} is not in {site}.'})
            self.cleaned_data['site'] = None
        return self.cleaned_data


class FloorForm(FloorBindingMixin, NetBoxModelForm):
    site = DynamicModelChoiceField(queryset=Site.objects.all(), required=False)
    location = DynamicModelChoiceField(
        queryset=Location.objects.all(),
        required=False,
        query_params={'site_id': '$site'},
    )
    comments = CommentField()

    fieldsets = (
        FieldSet('name', 'site', 'location', name='Floor'),
        FieldSet('width', 'depth', 'unit', name='Dimensions'),
        FieldSet('description', 'tags', name='Detail'),
    )

    class Meta:
        model = Floor
        fields = ('name', 'site', 'location', 'width', 'depth', 'unit', 'description', 'comments', 'tags')

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The site field also narrows the location list, so a floor bound to a location shows
        # its site here, the way the user filled the form in.
        if self.instance.location_id and not self.instance.site_id:
            self.initial['site'] = self.instance.location.site_id


class SiteScopedImportForm(NetBoxModelImportForm):
    """
    An import whose rows name a site, and then things in that site by their name alone.

    A floor, a location and a rack are each unique by name within a site only, so the site
    column is what makes "Hall 1" or "R101" mean one object.
    """

    site = CSVModelChoiceField(queryset=Site.objects.all(), to_field_name='name', help_text='Name of the site')

    def __init__(self, data=None, *args, **kwargs) -> None:
        super().__init__(data, *args, **kwargs)
        # A column the model has a default for may be left out of the file, and keeps the default.
        defaulted = {field.name for field in self._meta.model._meta.fields if field.has_default()}
        for name in defaulted & self.fields.keys():
            self.fields[name].required = False
        if not data:
            return
        # By the column's own key: a header such as `site.slug` names the site another way.
        site = Site.objects.filter(**{self.fields['site'].to_field_name: data.get('site')}).first()
        for name, field in self.fields.items():
            if name == 'floor':
                field.queryset = Floor.in_site(site) if site else Floor.objects.none()
            elif name in ('location', 'rack'):
                field.queryset = field.queryset.filter(site=site)


class FloorImportForm(FloorBindingMixin, SiteScopedImportForm):
    location = CSVModelChoiceField(
        queryset=Location.objects.all(),
        required=False,
        to_field_name='name',
        help_text='Name of a location in the site, to bind the floor to it instead of to the site',
    )
    unit = CSVChoiceField(choices=MeasurementUnitChoices, required=False, help_text='Unit of the width and the depth')

    class Meta:
        model = Floor
        fields = ('site', 'location', 'name', 'width', 'depth', 'unit', 'description', 'comments', 'tags')

    def clean_unit(self) -> str:
        return self.cleaned_data['unit'] or MeasurementUnitChoices.METRES


class RackPlacementImportForm(SiteScopedImportForm):
    floor = CSVModelChoiceField(queryset=Floor.objects.all(), to_field_name='name', help_text='Name of the floor')
    rack = CSVModelChoiceField(queryset=Rack.objects.all(), to_field_name='name', help_text='Name of the rack')

    class Meta:
        model = RackPlacement
        fields = ('site', 'floor', 'rack', 'x', 'y', 'rotation', 'tags')


class FloorLayerImportForm(SiteScopedImportForm):
    floor = CSVModelChoiceField(queryset=Floor.objects.all(), to_field_name='name', help_text='Name of the floor')

    class Meta:
        model = FloorLayer
        # No `file`: a CSV row cannot carry an upload, so an imported layer links its image.
        fields = (
            'site',
            'floor',
            'name',
            'external_url',
            'x',
            'y',
            'width',
            'height',
            'rotation',
            'opacity',
            'weight',
            'enabled',
            'tags',
        )


class FloorFilterForm(NetBoxModelFilterSetForm):
    model = Floor
    site_id = DynamicModelChoiceField(queryset=Site.objects.all(), required=False, label='Site')
    location_id = DynamicModelChoiceField(
        queryset=Location.objects.all(),
        required=False,
        label='Location',
        query_params={'site_id': '$site_id'},
    )
    unit = forms.ChoiceField(choices=[('', 'All'), *MeasurementUnitChoices], required=False)
    tag = TagFilterField(model)


class RackPlacementForm(NetBoxModelForm):
    floor = DynamicModelChoiceField(queryset=Floor.objects.all())
    rack = DynamicModelChoiceField(queryset=Rack.objects.all())

    class Meta:
        model = RackPlacement
        fields = ('floor', 'rack', 'x', 'y', 'rotation', 'tags')


class RackPlacementFilterForm(NetBoxModelFilterSetForm):
    model = RackPlacement
    site_id = DynamicModelChoiceField(queryset=Site.objects.all(), required=False, label='Site')
    location_id = DynamicModelChoiceField(
        queryset=Location.objects.all(),
        required=False,
        label='Location',
        query_params={'site_id': '$site_id'},
    )
    floor_id = DynamicModelChoiceField(queryset=Floor.objects.all(), required=False, label='Floor')
    rack_id = DynamicModelChoiceField(
        queryset=Rack.objects.all(),
        required=False,
        label='Rack',
        query_params={'site_id': '$site_id', 'location_id': '$location_id'},
    )
    tag = TagFilterField(model)


class FloorLayerFilterForm(NetBoxModelFilterSetForm):
    model = FloorLayer
    floor_id = DynamicModelChoiceField(queryset=Floor.objects.all(), required=False, label='Floor')
    enabled = forms.NullBooleanField(
        required=False,
        label='Enabled',
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    tag = TagFilterField(model)


class FloorBulkEditForm(NetBoxModelBulkEditForm):
    """
    The fields worth changing across several floors at once.

    Site and location are deliberately absent: moving a floor to another site would orphan
    every placement on it, since a placement is validated against the floor's site.
    """

    model = Floor
    description = forms.CharField(max_length=200, required=False)
    width = forms.DecimalField(max_digits=8, decimal_places=2, required=False)
    depth = forms.DecimalField(max_digits=8, decimal_places=2, required=False)
    unit = forms.ChoiceField(choices=[('', '---------'), *MeasurementUnitChoices], required=False)

    nullable_fields = ('description',)


class RackPlacementBulkEditForm(NetBoxModelBulkEditForm):
    """
    Rotation is the only field worth setting in bulk.

    Setting x or y across a selection would stack every rack on one spot, which is never what
    anybody means; rotating a whole row to face the other way is a real thing to want.
    """

    model = RackPlacement
    rotation = forms.DecimalField(max_digits=4, decimal_places=1, required=False)


class FloorLayerForm(NetBoxModelForm):
    floor = DynamicModelChoiceField(queryset=Floor.objects.all())

    fieldsets = (
        FieldSet('floor', 'name', 'file', 'external_url', name='Image'),
        FieldSet('x', 'y', 'width', 'height', 'rotation', name='Where it sits, in room centimetres'),
        FieldSet('opacity', 'weight', 'enabled', name='How it is drawn'),
        FieldSet('tags', name='Detail'),
    )

    class Meta:
        model = FloorLayer
        fields = (
            'floor',
            'name',
            'file',
            'external_url',
            'x',
            'y',
            'width',
            'height',
            'rotation',
            'opacity',
            'weight',
            'enabled',
            'tags',
        )


class FloorLayerBulkEditForm(NetBoxModelBulkEditForm):
    """
    The two things worth changing across a selection: whether the layers draw at all, and how
    strongly. Position and size describe one image each, so they are not offered here.
    """

    model = FloorLayer
    opacity = forms.DecimalField(max_digits=3, decimal_places=2, required=False)
    weight = forms.IntegerField(required=False)
    enabled = forms.NullBooleanField(required=False, widget=BulkEditNullBooleanSelect())
