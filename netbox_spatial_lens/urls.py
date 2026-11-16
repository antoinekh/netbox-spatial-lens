from django.urls import include, path
from utilities.urls import get_model_urls

from netbox_spatial_lens import views

urlpatterns = (
    # <app_label>.<model> is how the rack page already names a termination, so the caller
    # never has to know which model a port belongs to.
    path(
        'trace/<str:termination_type>/<int:termination_id>/',
        views.TraceView.as_view(),
        name='trace',
    ),
    path('world/', views.WorldView.as_view(), name='world'),
    path('floors/', views.FloorListView.as_view(), name='floor_list'),
    path('floors/add/', views.FloorEditView.as_view(), name='floor_add'),
    # Bulk routes must exist even where they are barely used: NetBox's list template renders
    # a bulk action button whichever way, and an unrouted one comes out as formaction="None",
    # which posts to /floors/None and answers "the requested page does not exist".
    path('floors/import/', views.FloorBulkImportView.as_view(), name='floor_bulk_import'),
    path('floors/edit/', views.FloorBulkEditView.as_view(), name='floor_bulk_edit'),
    path('floors/delete/', views.FloorBulkDeleteView.as_view(), name='floor_bulk_delete'),
    path('floors/<int:pk>/', include(get_model_urls('netbox_spatial_lens', 'floor'))),
    path('floor-layers/', views.FloorLayerListView.as_view(), name='floorlayer_list'),
    path('floor-layers/add/', views.FloorLayerEditView.as_view(), name='floorlayer_add'),
    path('floor-layers/import/', views.FloorLayerBulkImportView.as_view(), name='floorlayer_bulk_import'),
    path('floor-layers/edit/', views.FloorLayerBulkEditView.as_view(), name='floorlayer_bulk_edit'),
    path('floor-layers/delete/', views.FloorLayerBulkDeleteView.as_view(), name='floorlayer_bulk_delete'),
    path('floor-layers/<int:pk>/', include(get_model_urls('netbox_spatial_lens', 'floorlayer'))),
    path('rack-placements/', views.RackPlacementListView.as_view(), name='rackplacement_list'),
    path('rack-placements/add/', views.RackPlacementEditView.as_view(), name='rackplacement_add'),
    path(
        'rack-placements/import/',
        views.RackPlacementBulkImportView.as_view(),
        name='rackplacement_bulk_import',
    ),
    path('rack-placements/edit/', views.RackPlacementBulkEditView.as_view(), name='rackplacement_bulk_edit'),
    path(
        'rack-placements/delete/',
        views.RackPlacementBulkDeleteView.as_view(),
        name='rackplacement_bulk_delete',
    ),
    path('rack-placements/<int:pk>/', include(get_model_urls('netbox_spatial_lens', 'rackplacement'))),
)
