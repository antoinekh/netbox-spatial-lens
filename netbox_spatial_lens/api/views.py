"""
REST API.

The placement editor writes through these endpoints rather than through a private one of its
own, so there is a single way to move a rack and a single permission guarding it.
"""

from django.db.models import Count
from netbox.api.viewsets import NetBoxModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response

from netbox_spatial_lens import filtersets
from netbox_spatial_lens.api.serializers import FloorLayerSerializer, FloorSerializer, RackPlacementSerializer
from netbox_spatial_lens.models import Floor, FloorLayer, RackPlacement

__all__ = (
    'FloorLayerViewSet',
    'FloorViewSet',
    'RackPlacementViewSet',
)


class FloorViewSet(NetBoxModelViewSet):
    queryset = Floor.objects.prefetch_related('tags').annotate(placement_count=Count('placements'))
    serializer_class = FloorSerializer
    filterset_class = filtersets.FloorFilterSet

    @action(detail=True, methods=['get'])
    def layout(self, request, pk=None):
        """
        Everything one render of this floor needs, in a single response.

        The web view builds the same structure server-side. This endpoint exists so a second
        renderer, such as a 3D projection, consumes the floor without restating how a
        footprint is resolved or how a colouring is evaluated.
        """
        from dcim.models import Device, Rack

        from netbox_spatial_lens.colouring import Level, registry
        from netbox_spatial_lens.floor_cabling import build_floor_exits, build_floor_runs
        from netbox_spatial_lens.layout import build_layout

        floor = self.get_object()
        colouring = registry.resolve(Level.RACKS, request.GET.get('colour'))
        # Restricted as the floor page is: a placement is the plugin's own object, the rack and
        # the devices behind it are not, and the API must not show what the page hides.
        placed = build_layout(
            floor,
            colouring,
            racks=Rack.objects.restrict(request.user, 'view'),
            devices=Device.objects.restrict(request.user, 'view'),
            user=request.user,
        )
        # As on the page: the runs cost a query, so they are sent only when asked for.
        show_runs = request.GET.get('runs') == '1'
        runs = build_floor_runs(placed) if show_runs else []
        exits = build_floor_exits(placed, floor, user=request.user) if show_runs else []

        return Response(
            {
                'floor': {
                    'id': floor.pk,
                    'name': floor.name,
                    'width_cm': floor.width_cm,
                    'depth_cm': floor.depth_cm,
                },
                'colouring': {
                    'name': colouring.name,
                    'label': colouring.label,
                    'legend': [
                        {'band': e.key, 'colour': e.colour, 'label': e.label, 'count': e.count}
                        for e in colouring.legend(p.value for p in placed)
                    ],
                }
                if colouring
                else None,
                'racks': [
                    {
                        'rack_id': p.rack.pk,
                        'name': p.rack.name,
                        'x': p.x,
                        'y': p.y,
                        'rotation': p.rotation,
                        'width': p.width,
                        'depth': p.depth,
                        'u_height': p.rack.u_height,
                        'estimated_footprint': p.estimated,
                        'colour': p.colour,
                        'label': p.label,
                        'band': p.band,
                        # Where this rack sits between empty and full, or null where the
                        # colouring measures a name rather than a quantity. A second renderer
                        # needs the magnitude for the same reason the plan does: a band alone
                        # cannot tell 12% from 48%.
                        'fraction': p.fraction,
                        'facts': [[label, value] for label, value in p.facts],
                    }
                    for p in placed
                ],
                'layers': [
                    {
                        'id': layer.pk,
                        'name': layer.name,
                        'source': layer.source,
                        'x': float(layer.x),
                        'y': float(layer.y),
                        'width': float(layer.width),
                        'height': float(layer.height),
                        'rotation': float(layer.rotation),
                        'opacity': float(layer.opacity),
                    }
                    for layer in floor.layers.filter(enabled=True)
                ],
                'runs': [
                    {
                        'rack_a': run.a.rack.pk,
                        'rack_b': run.b.rack.pk,
                        'count': run.count,
                    }
                    for run in runs
                ],
                'exits': [
                    {
                        'rack': item.rack.rack.pk,
                        'label': item.label,
                        'kind': item.kind,
                        'count': item.count,
                        'x': item.x,
                        'y': item.y,
                    }
                    for item in exits
                ],
            }
        )

    @action(detail=True, methods=['get'])
    def devices(self, request, pk=None):
        """
        The devices in every rack on this floor, placed in their cabinets.

        What the floor's Devices view draws, fetched when the reader switches to it rather than
        rendered into every floor page. Restricted like the layout: racks and devices the caller
        may not view are left out.
        """
        from dcim.models import Device, Rack

        from netbox_spatial_lens.floor_scene import build_floor_devices

        return Response(
            build_floor_devices(
                self.get_object(),
                racks=Rack.objects.restrict(request.user, 'view'),
                devices=Device.objects.restrict(request.user, 'view'),
            )
        )


class RackPlacementViewSet(NetBoxModelViewSet):
    queryset = RackPlacement.objects.prefetch_related('tags').select_related('floor', 'rack')
    serializer_class = RackPlacementSerializer
    filterset_class = filtersets.RackPlacementFilterSet


class FloorLayerViewSet(NetBoxModelViewSet):
    queryset = FloorLayer.objects.prefetch_related('tags').select_related('floor')
    serializer_class = FloorLayerSerializer
    filterset_class = filtersets.FloorLayerFilterSet
