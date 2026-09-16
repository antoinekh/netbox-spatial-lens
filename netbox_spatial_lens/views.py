"""
Views.

The floor view and the editor draw the same picture from the same data. The editor adds drag
and rotate, and saves through the REST API rather than through a private endpoint of its own,
so there is one way to write a placement and one set of permissions guarding it.
"""

from dataclasses import dataclass

from circuits.models import Circuit
from dcim.models import Device, Rack, Site
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from netbox.plugins import get_plugin_config
from netbox.views import generic
from utilities.views import ViewTab, register_model_view

from netbox_spatial_lens import filtersets, forms, tables
from netbox_spatial_lens.cabling import kind_legend
from netbox_spatial_lens.device_overlays import get_device_overlays, resolve_device_overlay
from netbox_spatial_lens.elevation import build_elevation, rack_summary
from netbox_spatial_lens.field_filters import cells_for, field_filters
from netbox_spatial_lens.floor_cabling import build_floor_exits, build_floor_runs, cabling_legend
from netbox_spatial_lens.floor_scene import build_floor_scene
from netbox_spatial_lens.geometry import floor_viewport, metre_ticks, rack_footprint_cm
from netbox_spatial_lens.layout import (
    build_layout,
    build_layouts,
    floor_summary,
    rack_rows,
    resolve_overlay,
    unplaced_racks,
)
from netbox_spatial_lens.models import Floor, FloorLayer, RackPlacement
from netbox_spatial_lens.overlays import get_overlays
from netbox_spatial_lens.palette import (
    HIGHLIGHT,
    HIGHLIGHT_DARK,
    LABEL,
    LABEL_DARK,
    LABEL_HALO,
    LABEL_HALO_DARK,
    STATUS_COLOURS,
)
from netbox_spatial_lens.ports import rack_allocation
from netbox_spatial_lens.scene import build_scene
from netbox_spatial_lens.site_overlays import get_site_overlays, resolve_site_overlay
from netbox_spatial_lens.tags import tags_in_use
from netbox_spatial_lens.templatetags.lens import lens_static
from netbox_spatial_lens.tracing import trace_from
from netbox_spatial_lens.world import build_world

__all__ = (
    'FloorBulkDeleteView',
    'FloorBulkEditView',
    'FloorDeleteView',
    'FloorEditView',
    'FloorLayerBulkDeleteView',
    'FloorLayerBulkEditView',
    'FloorLayerEditView',
    'FloorLayerListView',
    'FloorLayoutView',
    'FloorListView',
    'FloorView',
    'RackLensView',
    'RackPlacementBulkDeleteView',
    'RackPlacementBulkEditView',
    'RackPlacementDeleteView',
    'RackPlacementEditView',
    'RackPlacementListView',
    'TraceView',
    'WorldView',
)


@dataclass
class ThreeStage:
    """
    What a page drawing on a 3D stage (`stage3d.js`) needs from the server.

    `imports` is the page's import map: Three.js from the `three_base` setting, and the stage
    module itself under a name, so the drawing imports it by that name and still gets the URL
    that changes whenever the file does. `config` is merged into the drawing's own config, and
    tells the stage whether it may load Three.js at all.
    """

    imports: dict[str, str]
    config: dict


def three_stage() -> ThreeStage:
    # A copy of the `three` npm package, laid out as published. `three/addons/` is how Three.js's
    # own examples import their controls, so the files under it load unchanged from any copy.
    base = get_plugin_config('netbox_spatial_lens', 'three_base') or ''
    if base and not base.endswith('/'):
        base = f'{base}/'
    # The stage module is always mapped, even with Three.js turned off, so the page can still
    # load it and say on the stage why nothing is drawn.
    imports = {
        'lens/stage3d': lens_static('netbox_spatial_lens/stage3d.js'),
        'lens/cabinet3d': lens_static('netbox_spatial_lens/cabinet3d.js'),
    }
    if base:
        imports.update({'three': f'{base}build/three.module.js', 'three/addons/': f'{base}examples/jsm/'})
    return ThreeStage(imports=imports, config={'enabled': bool(base), 'threeBase': base})


class FloorListView(generic.ObjectListView):
    # The site column reads `effective_site`, which for a floor bound to a location is the
    # location's site, so both are fetched with the floor.
    queryset = Floor.objects.select_related('site', 'location__site').annotate(placement_count=Count('placements'))
    table = tables.FloorTable
    filterset = filtersets.FloorFilterSet
    filterset_form = forms.FloorFilterForm


@register_model_view(Floor)
class FloorView(generic.ObjectView):
    queryset = Floor.objects.all()
    template_name = 'netbox_spatial_lens/floor.html'

    def get_extra_context(self, request, instance):
        overlay = resolve_overlay(request.GET.get('overlay'))
        # Only the racks the reader may open. A placement is the plugin's own object and
        # NetBox will show it; the cabinet on the other end of it is not.
        racks = Rack.objects.restrict(request.user, 'view')
        devices = Device.objects.restrict(request.user, 'view')
        placed = build_layout(instance, overlay, racks=racks, devices=devices)
        # Custom fields offered as filters, like tags: each rack carries its values for the
        # finder and the table, and names them in its hover card.
        filters = field_filters((p.rack for p in placed), Rack)
        for p in placed:
            p.field_cells = cells_for(filters, p.rack)
            p.facts.extend((cell.filter.label, cell.sort_value) for cell in p.field_cells if cell.values)
        view = floor_viewport(instance)
        step = int(view.step / 100)
        # Off by default: the runs are the answer to a specific question, and drawn over a
        # busy room unasked they are noise across every other overlay.
        show_runs = request.GET.get('runs') == '1'
        runs = build_floor_runs(placed) if show_runs else []
        # Drawn under the same toggle: a room whose only cabling leaves the building would
        # otherwise answer "show me the cabling" with an empty plan.
        exits = build_floor_exits(placed, instance, user=request.user) if show_runs else []
        stage = three_stage()
        return {
            'three_imports': stage.imports,
            'floor3d_config': {
                **stage.config,
                'scene': build_floor_scene(instance, placed, runs, exits).as_json(),
                # The devices in each rack, fetched only when the reader switches to them.
                'devicesUrl': reverse('plugins-api:netbox_spatial_lens-api:floor-devices', args=[instance.pk]),
                'colours': {'highlight': HIGHLIGHT, 'highlightDark': HIGHLIGHT_DARK},
            },
            'overlays': get_overlays(),
            'overlay': overlay,
            'stats': floor_summary(instance, placed),
            # The scale, so the plan is a drawing rather than a picture of one.
            'view': view,
            'x_ticks': metre_ticks(instance.width_cm, step),
            'y_ticks': metre_ticks(instance.depth_cm, step),
            'legend': overlay.legend_for([p.value for p in placed]) if overlay else [],
            'placed_racks': placed,
            'rack_rows': rack_rows(placed),
            'rack_tags': tags_in_use(p.rack for p in placed),
            'field_filters': filters,
            'unplaced_racks': unplaced_racks(instance, racks=racks),
            'layers': instance.layers.filter(enabled=True),
            'show_runs': show_runs,
            'runs': runs,
            'exits': exits,
            'cabling_legend': cabling_legend(runs, exits) if show_runs else [],
        }


@register_model_view(Floor, 'layout', path='layout')
class FloorLayoutView(generic.ObjectView):
    """
    The placement editor.

    It is a tab on the floor rather than a separate page, so leaving edit mode does not lose
    your place, and the permission it needs is the ordinary one for changing a placement.
    """

    queryset = Floor.objects.all()
    template_name = 'netbox_spatial_lens/floor_layout.html'
    tab = ViewTab(label='Edit layout', permission='netbox_spatial_lens.change_rackplacement')

    def get_extra_context(self, request, instance):
        view = floor_viewport(instance)
        step = int(view.step / 100)
        racks = Rack.objects.restrict(request.user, 'view')
        devices = Device.objects.restrict(request.user, 'view')
        return {
            'placed_racks': build_layout(instance, None, racks=racks, devices=devices),
            # What the editor may do besides moving a rack. The tab needs change; placing a rack
            # needs add and taking one off the floor needs delete, and a control the API would
            # refuse is not offered.
            'can_add': request.user.has_perm('netbox_spatial_lens.add_rackplacement'),
            'can_delete': request.user.has_perm('netbox_spatial_lens.delete_rackplacement'),
            # Each with its footprint, so a rack put down in the editor is drawn at its own size
            # rather than at a default one that changes on the next reload.
            'unplaced_racks': [(rack, *rack_footprint_cm(rack)) for rack in unplaced_racks(instance, racks=racks)],
            'grid_size': get_plugin_config('netbox_spatial_lens', 'grid_size'),
            'layers': instance.layers.filter(enabled=True),
            'view': view,
            'x_ticks': metre_ticks(instance.width_cm, step),
            'y_ticks': metre_ticks(instance.depth_cm, step),
        }


@register_model_view(Floor, 'edit')
class FloorEditView(generic.ObjectEditView):
    queryset = Floor.objects.all()
    form = forms.FloorForm


@register_model_view(Floor, 'delete')
class FloorDeleteView(generic.ObjectDeleteView):
    queryset = Floor.objects.all()


class FloorBulkEditView(generic.BulkEditView):
    queryset = Floor.objects.all()
    filterset = filtersets.FloorFilterSet
    table = tables.FloorTable
    form = forms.FloorBulkEditForm


class FloorBulkDeleteView(generic.BulkDeleteView):
    queryset = Floor.objects.all()
    filterset = filtersets.FloorFilterSet
    table = tables.FloorTable


class RackPlacementListView(generic.ObjectListView):
    queryset = RackPlacement.objects.select_related('floor', 'rack', 'rack__site', 'rack__location')
    table = tables.RackPlacementTable
    filterset = filtersets.RackPlacementFilterSet
    filterset_form = forms.RackPlacementFilterForm


@register_model_view(RackPlacement, 'edit')
class RackPlacementEditView(generic.ObjectEditView):
    queryset = RackPlacement.objects.all()
    form = forms.RackPlacementForm


@register_model_view(RackPlacement, 'delete')
class RackPlacementDeleteView(generic.ObjectDeleteView):
    queryset = RackPlacement.objects.all()


@register_model_view(Site, 'lens', path='spatial-lens')
class SiteLensView(generic.ObjectView):
    """
    The rooms in a site.

    The level between the world and a floor. A site is one room often enough that the map used
    to go straight to a floor, which told anyone with several rooms that they had one: the
    other rooms were reachable only from the Floors list, if you knew to look. This names all
    of them, and the racks in the site that stand on none of them.
    """

    queryset = Site.objects.all()
    template_name = 'netbox_spatial_lens/site.html'
    tab = ViewTab(label='Spatial Lens', permission='dcim.view_site', badge=lambda site: Floor.in_site(site).count())

    def get_extra_context(self, request, instance):
        floors = list(
            Floor.in_site(instance, Floor.objects.restrict(request.user, 'view')).select_related('site', 'location')
        )
        racks = Rack.objects.restrict(request.user, 'view').filter(site=instance)
        devices = Device.objects.restrict(request.user, 'view')

        # A thumbnail of each room, drawn from the same layout the floor page draws, so this
        # page is an index of plans rather than a table of names. Read for every room at once,
        # with space and power measured once for the summaries, so a site of many rooms costs
        # what a site of one does.
        overlay = resolve_overlay(request.GET.get('overlay'))
        layouts = build_layouts(floors, overlay, racks=racks, devices=devices, measure=True)
        rooms = []
        for floor in floors:
            placed = layouts[floor.pk]
            view = floor_viewport(floor)
            step = int(view.step / 100)
            rooms.append(
                {
                    'floor': floor,
                    'view': view,
                    'x_ticks': metre_ticks(floor.width_cm, step),
                    'y_ticks': metre_ticks(floor.depth_cm, step),
                    'placed': placed,
                    'stats': floor_summary(floor, placed),
                }
            )

        # A rack in the site that stands on no floor at all. The honesty rule: a cabinet
        # nobody has placed is named and counted here, rather than being absent from every
        # picture and therefore from the tally too.
        return {
            'rooms': rooms,
            'overlay': overlay,
            'overlays': get_overlays(),
            'unplaced': list(racks.filter(lens_placement__isnull=True).order_by('name')),
        }


@register_model_view(Rack, 'lens', path='spatial-lens')
class RackLensView(generic.ObjectView):
    """
    The inside of a rack in 3D: the device type images on real boxes at their U positions, and
    every cable through the cable managers.

    Registered as a tab on NetBox's own rack page rather than as a page of this plugin's own.
    A rack is a NetBox object and this is another way of looking at it, so it belongs beside
    the elevation NetBox already draws instead of in a separate part of the menu.
    """

    queryset = Rack.objects.select_related('site', 'location', 'role')
    template_name = 'netbox_spatial_lens/rack.html'
    tab = ViewTab(label='Spatial Lens', permission='dcim.view_rack')

    def get_extra_context(self, request, instance):
        elevation = build_elevation(instance, devices_queryset=Device.objects.restrict(request.user, 'view'))
        devices = elevation.devices

        # How the devices are coloured, chosen in the URL so a coloured rack is a link
        # somebody can send. An unknown name falls back rather than failing, the same way an
        # unknown floor overlay does.
        overlays = get_device_overlays()
        overlay = resolve_device_overlay(request.GET.get('colour'))
        # Custom fields offered as filters, like tags.
        filters = field_filters((m.device for m in devices), Device)
        for mounted in devices:
            mounted.field_cells = cells_for(filters, mounted.device)
        if overlay:
            values = overlay.evaluate(devices)
            for mounted in devices:
                value = values.get(mounted.device.pk)
                if value is not None:
                    mounted.colour = value.colour
                    mounted.value = value
                    mounted.band = overlay.band_of(value)
        placement = RackPlacement.objects.filter(rack=instance).select_related('floor').first()
        # Each device's own cabling, rendered up front so selecting one costs no request, the
        # same way the allocation panel works. A run is listed under both of its ends, because
        # "what is this device cabled to" is the question at either end of the wire.
        runs_by_device = {}
        for run in elevation.runs:
            runs_by_device.setdefault(run.local_device.pk, []).append(run)
            if run.peer_device is not None:
                runs_by_device.setdefault(run.peer_device.pk, []).append(run)

        stage = three_stage()

        return {
            'elevation': elevation,
            'device_tags': tags_in_use(m.device for m in devices),
            'field_filters': filters,
            'stats': rack_summary(elevation),
            'device_overlays': overlays,
            'device_overlay': overlay,
            'device_legend': (overlay.legend_for([m.value for m in devices if m.value]) if overlay else []),
            'runs_by_device': [(mounted, runs_by_device.get(mounted.device.pk, [])) for mounted in devices],
            # The way back up to the floor this rack stands on, so the two views are a
            # round trip rather than a one-way link.
            'floor': placement.floor if placement else None,
            'rack_allocation': rack_allocation(elevation),
            'cable_legend': kind_legend(elevation.runs),
            'internal_runs': [r for r in elevation.runs if r.internal],
            'external_runs': [r for r in elevation.runs if not r.internal],
            'three_imports': stage.imports,
            'rack3d_config': {
                **stage.config,
                'scene': build_scene(elevation).as_json(),
                # The drawing lights and tints its own meshes, so it needs the colours a
                # stylesheet would otherwise have painted: the selection in both themes, and
                # the red reserved units are drawn in.
                'colours': {
                    'highlight': HIGHLIGHT,
                    'highlightDark': HIGHLIGHT_DARK,
                    'reserved': STATUS_COLOURS['red'],
                },
            },
        }


class WorldView(generic.ObjectListView):
    """
    Sites and the circuits between them.

    Built on ObjectListView so it inherits NetBox's permission handling for sites, rather
    than on a bare view that would have to restate it. The list itself is never rendered;
    the template draws the map instead.

    `self.queryset` is the restricted one: NetBox's permission mixin narrows it in dispatch,
    and it is handed to the builder rather than being ignored in favour of `Site.objects.all()`.
    A user who may see one region gets a map of that region.
    """

    queryset = Site.objects.all()
    template_name = 'netbox_spatial_lens/world.html'

    def get(self, request):
        # An unknown name falls back rather than failing: a shared link carrying a colouring a
        # later release removed should still open the map, which is how the floor behaves too.
        # Resolved once, here, so the map and the toolbar name the same colouring.
        overlay = resolve_site_overlay(request.GET.get('overlay'))
        world = build_world(
            self.queryset,
            overlay=overlay,
            # Restricted like the sites are: the map must not become a way to read circuits a
            # user may not open anywhere else in NetBox.
            circuits=Circuit.objects.restrict(request.user, 'view'),
        )

        # Where a site marker takes you: its one room where it has one, the site's rooms where
        # it has several, and the site's Spatial Lens tab where it has none, which lists its racks and
        # offers to add a floor. It used to be a dictionary keyed by site, which kept the last
        # floor per site and dropped the rest, and it read `site_id` alone, so a room bound to a
        # location was not in it at all. A site's other rooms were then reachable only from the
        # Floors list.
        rooms = {}
        for floor in Floor.objects.restrict(request.user, 'view').select_related('location'):
            site_id = floor.site_id or (floor.location.site_id if floor.location else None)
            if site_id:
                rooms.setdefault(site_id, []).append(floor)
        for node in world.nodes:
            floors = rooms.get(node.object_id) if node.kind == 'site' else None
            if not floors:
                continue
            if len(floors) == 1:
                node.url, node.action = floors[0].get_absolute_url(), 'Open the floor'
            else:
                node.url, node.action = reverse('dcim:site_lens', args=[node.object_id]), 'Open the rooms'

        return render(
            request,
            self.template_name,
            {
                'world': world,
                'model': Site,
                'overlay': overlay,
                'overlays': get_site_overlays(),
                # Handed to the page as data rather than baked into the script, so a
                # deployment can point at its own tile server or its own copy of MapLibre.
                #
                # Rendered with `json_script` rather than dumped and marked safe. `json.dumps`
                # does not escape "<", so a site, tenant, provider or circuit whose name holds
                # a closing script tag would end the tag early and put the rest of its name on
                # the page as markup.
                'map_config': {
                    'tileUrl': get_plugin_config('netbox_spatial_lens', 'map_tile_url'),
                    'attribution': get_plugin_config('netbox_spatial_lens', 'map_attribution'),
                    'mapCss': get_plugin_config('netbox_spatial_lens', 'map_css'),
                    'mapJs': get_plugin_config('netbox_spatial_lens', 'map_js'),
                    'glyphs': get_plugin_config('netbox_spatial_lens', 'map_glyphs'),
                    # The map draws its own lines, so it needs the palette too rather
                    # than a fourth copy of the same hex values.
                    'colours': {
                        'highlight': HIGHLIGHT,
                        # The map draws its own labels now, so it needs the two colours a
                        # name is made of as well as the ones the marks wear.
                        'label': LABEL,
                        'halo': LABEL_HALO,
                        # The same three for the dark theme, which the script picks when the
                        # page is dark.
                        'dark': {'highlight': HIGHLIGHT_DARK, 'label': LABEL_DARK, 'halo': LABEL_HALO_DARK},
                    },
                    'nodes': [
                        {
                            'key': n.key,
                            'label': n.label,
                            'kind': n.kind,
                            'lat': n.lat,
                            'lon': n.lon,
                            'radius': n.radius,
                            'colour': n.colour,
                            'band': n.band,
                            'detail': n.detail,
                            'url': n.url,
                            'action': n.action,
                            'status': n.status,
                            'facts': n.facts,
                            'links': n.link_count,
                        }
                        for n in world.nodes
                        if n.lat is not None and n.lon is not None
                    ],
                    'links': [
                        {
                            'id': link.circuit.pk,
                            'a': link.a.key,
                            'z': link.z.key,
                            'width': link.width,
                            'label': link.label,
                            'colour': link.colour,
                            'url': link.circuit.get_absolute_url(),
                        }
                        for link in world.links
                        if link.a.lat is not None and link.z.lat is not None
                    ],
                },
            },
        )


class TraceView(LoginRequiredMixin, View):
    """
    The full path leaving one termination, as JSON.

    Fetched on demand rather than rendered with the rack. A rack of forty switches has
    hundreds of connected ports, and tracing every one to draw a page nobody has clicked on
    yet would cost far more than the answer is worth.

    It reads only what the caller may see. The starting termination is looked up with the
    caller's permissions, so one they may not view answers 404 like a missing one, and every
    object along the path is named only if they may view it.
    """

    def get(self, request, termination_type, termination_id):
        if not request.user.has_perm('dcim.view_cable'):
            return JsonResponse({'detail': 'Permission denied.'}, status=403)

        trace = trace_from(termination_type, termination_id, user=request.user)
        if trace is None:
            return JsonResponse({'detail': 'No such termination.'}, status=404)

        return JsonResponse(
            {
                'origin': {'label': trace.origin_label, 'device': trace.origin_device},
                'complete': trace.complete,
                'reaches': trace.reaches,
                'hops': [
                    {
                        'index': hop.index,
                        'from': {'label': hop.from_label, 'device': hop.from_device},
                        'to': {'label': hop.to_label, 'device': hop.to_device},
                        'cable': {'label': hop.cable_label, 'id': hop.cable_id},
                        'device_id': hop.device_id,
                        'rack_id': hop.rack_id,
                        'rack': hop.rack_label,
                        'kind': hop.kind,
                    }
                    for hop in trace.hops
                ],
            }
        )


class RackPlacementBulkEditView(generic.BulkEditView):
    queryset = RackPlacement.objects.select_related('floor', 'rack')
    filterset = filtersets.RackPlacementFilterSet
    table = tables.RackPlacementTable
    form = forms.RackPlacementBulkEditForm


class RackPlacementBulkDeleteView(generic.BulkDeleteView):
    queryset = RackPlacement.objects.select_related('floor', 'rack')
    filterset = filtersets.RackPlacementFilterSet
    table = tables.RackPlacementTable


class FloorLayerListView(generic.ObjectListView):
    queryset = FloorLayer.objects.select_related('floor')
    table = tables.FloorLayerTable
    filterset = filtersets.FloorLayerFilterSet
    filterset_form = forms.FloorLayerFilterForm


@register_model_view(FloorLayer, 'edit')
class FloorLayerEditView(generic.ObjectEditView):
    queryset = FloorLayer.objects.all()
    form = forms.FloorLayerForm


@register_model_view(FloorLayer, 'delete')
class FloorLayerDeleteView(generic.ObjectDeleteView):
    queryset = FloorLayer.objects.all()


class FloorLayerBulkEditView(generic.BulkEditView):
    queryset = FloorLayer.objects.select_related('floor')
    filterset = filtersets.FloorLayerFilterSet
    table = tables.FloorLayerTable
    form = forms.FloorLayerBulkEditForm


class FloorLayerBulkDeleteView(generic.BulkDeleteView):
    queryset = FloorLayer.objects.select_related('floor')
    filterset = filtersets.FloorLayerFilterSet
    table = tables.FloorLayerTable
