from netbox.plugins import PluginConfig

__version__ = '0.3.0'


class SpatialLensConfig(PluginConfig):
    name = 'netbox_spatial_lens'
    verbose_name = 'NetBox Spatial Lens'
    description = 'World map, floor plans and rack elevations for NetBox, recoloured by power, cooling and space'
    version = __version__
    base_url = 'spatial-lens'
    # The rack cooling fields this plugin colours by (cooling_capability, cooling_capacity)
    # arrived in NetBox 4.7, so there is no earlier release to support.
    min_version = '4.7.0'
    max_version = '4.7.99'
    default_settings = {  # noqa: RUF012
        # Footprint used when a rack declares no outer_width or outer_depth, in millimetres.
        # 600x1070 is a standard 19-inch cabinet. A rack drawn at this size is reported as
        # estimated rather than silently passed off as measured.
        'default_rack_width': 600,
        'default_rack_depth': 1070,
        # Grid the editor snaps to, in centimetres. 0 disables snapping.
        'grid_size': 10,
        # Custom fields offered as filters, the way tags are, on the floor (racks) and in the rack
        # view (devices): a list of field names. Only select and multiselect fields are used.
        'filter_custom_fields': [],
        # Which built-in overlays to register. True for all, False for none, or a list of
        # names from 'power', 'cooling', 'space' and 'role'.
        'enable_builtin_overlays': True,
        # Overlay selected when a floor is opened without one named.
        'default_overlay': 'power',
        # Which built-in device colourings a rack offers. True for all, False for none, or a
        # list from 'role', 'status', 'tenant', 'cabling' and 'power'.
        'enable_builtin_device_overlays': True,
        # Colouring selected when a rack is opened without one named.
        'default_device_overlay': 'role',
        # Which built-in site colourings the world map offers. True for all, False for none, or
        # a list from 'group', 'status', 'tenant' and 'region'.
        'enable_builtin_site_overlays': True,
        # Colouring selected when the map is opened without one named.
        'default_site_overlay': 'group',
        # Tiles for the world map. OpenStreetMap's own tiles are the default because they
        # need no API key; CARTO's basemaps now watermark every tile without one. Point this
        # at your own tile server, or set it to None, on a site with no egress. Without tiles
        # the globe is drawn on a plain ground, with the same sites and circuits on it.
        #
        # A URL containing {theme} gets 'light' or 'dark' substituted, so a basemap offering
        # both follows the NetBox theme.
        'map_tile_url': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        'map_attribution': '&copy; OpenStreetMap contributors',
        # Where MapLibre is served from. Bundling it would put a minified library in a Python
        # package; naming it here lets a deployment host its own copy instead.
        #
        # MapLibre rather than Leaflet because it draws a globe: zoomed out, an estate on two
        # continents reads as one earth rather than as a strip of repeating flat maps with the
        # same site on it three times, and there is no antimeridian to fall off. It needs WebGL:
        # a browser without it, or one that cannot load these two files, is told so on the page,
        # and the figures, legends and lists there still work.
        'map_css': 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/5.6.1/maplibre-gl.min.css',
        'map_js': 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/5.6.1/maplibre-gl.min.js',
        # Where the map's letters come from. A raster basemap carries no fonts of its own, and a
        # renderer that draws its own labels needs them. Point this at your own glyph server on
        # a site with no egress; without it the markers are drawn and the names are not.
        'map_glyphs': 'https://fonts.openmaptiles.org/{fontstack}/{range}.pbf',
        # Where the 3D rack and floor drawings load Three.js from: a copy of the `three` npm
        # package, laid out as published, so `build/three.module.js` and `examples/jsm/` sit under
        # it. Pinned, because the addons under `examples/jsm/` must come from the same release as
        # the core. Empty turns both drawings off: the rack page keeps its panels and figures, and
        # the floor opens on its 2D plan.
        'three_base': 'https://cdn.jsdelivr.net/npm/three@0.186.0/',
    }

    def ready(self) -> None:
        super().ready()

        from . import (
            device_overlays,
            overlays,
            signals,  # noqa: F401  (connects the receivers)
            site_overlays,
        )

        for level in (overlays, device_overlays, site_overlays):
            level.registry.register_configured_builtins()


config = SpatialLensConfig
