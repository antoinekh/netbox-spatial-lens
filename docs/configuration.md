# Configuration

Every setting is optional. Set them under `PLUGINS_CONFIG['netbox_spatial_lens']` in NetBox's `configuration.py`.

| Setting | Default | What it does |
|---|---|---|
| `default_rack_width` | `600` | Width in millimetres used for a rack with no outer width recorded. Such a rack is marked as estimated. |
| `default_rack_depth` | `1070` | Depth in millimetres used for a rack with no outer depth recorded. |
| `grid_size` | `10` | Grid the layout editor snaps to, in centimetres. `0` turns snapping off. |
| `filter_custom_fields` | `[]` | Custom fields to offer as filters, the way tags are: a list of field names. See [Filter by](extending.md#filter-by). |
| `enable_builtin_overlays` | `True` | Floor colourings to offer: `True` for all, `False` for none, or a list from `'power'`, `'cooling'`, `'space'`, `'role'`. |
| `default_overlay` | `'power'` | Floor colouring used when the URL names none. |
| `enable_builtin_device_overlays` | `True` | Rack colourings to offer: `True`, `False`, or a list from `'role'`, `'status'`, `'tenant'`, `'cabling'`, `'power'`. |
| `default_device_overlay` | `'role'` | Rack colouring used when the URL names none. |
| `enable_builtin_site_overlays` | `True` | World map colourings to offer: `True`, `False`, or a list from `'group'`, `'status'`, `'tenant'`, `'region'`. |
| `default_site_overlay` | `'group'` | World map colouring used when the URL names none. |
| `map_tile_url` | OpenStreetMap tiles | Raster tile URL for the globe. `{theme}` in the URL becomes `light` or `dark`. `None` draws the globe with no basemap. |
| `map_attribution` | OpenStreetMap credit | Credit shown on the map for the tiles. |
| `map_js` | MapLibre 5.6.1 on cdnjs | Where the browser loads MapLibre from. Empty turns the world map off. |
| `map_css` | MapLibre 5.6.1 on cdnjs | Where the browser loads MapLibre's stylesheet from. |
| `map_glyphs` | OpenMapTiles fonts | Font server for the site names on the map. `None` draws the map without names. |
| `three_base` | Three.js 0.186.0 on jsDelivr | Where the browser loads Three.js from for the rack view and the 3D floor: a copy of the `three` npm package, with `build/three.module.js` and `examples/jsm/` under it. Empty turns both 3D drawings off; the floor then opens in 2D. |

A name in a URL that no colouring answers to falls back to the default, and then to the first colouring registered, so an old link still opens.

To add a colouring of your own, or to filter by custom fields, see [Extending](extending.md).

## A site with no internet access

The world map, the rack view and the 3D floor need a browser with WebGL, and a copy of MapLibre and of Three.js it can reach. The tiles and the fonts are optional. Host the libraries yourself, and point the settings at your own servers, or turn the optional parts off:

```python
PLUGINS_CONFIG = {
    'netbox_spatial_lens': {
        'map_js': 'https://static.example.internal/maplibre-gl/5.6.1/maplibre-gl.min.js',
        'map_css': 'https://static.example.internal/maplibre-gl/5.6.1/maplibre-gl.min.css',
        # Your own tile server, or None for a globe with no basemap.
        'map_tile_url': 'https://tiles.example.internal/{z}/{x}/{y}.png',
        'map_attribution': 'Internal tiles',
        # Your own glyph server, or None for a map without site names.
        'map_glyphs': None,
        # A copy of the `three` npm package, unpacked as published.
        'three_base': 'https://static.example.internal/three/0.186.0/',
    },
}
```

The 2D floor plan needs nothing from the network. When the 3D floor cannot be drawn, the floor opens in 2D and the 3D button says why.

The world map sends the page's origin, and nothing more, as the `Referer` of each tile request. OpenStreetMap's tile servers refuse a tile requested without one, and NetBox's own `Referrer-Policy` would otherwise leave it out.
