# Modules

What each part of the plugin holds. The Python modules are under `netbox_spatial_lens/`, the scripts under `netbox_spatial_lens/static/netbox_spatial_lens/`.

| Module | Holds |
|---|---|
| `models` | `Floor`, `RackPlacement` and `FloorLayer`, geometry only |
| `signals` | Removing a background image from storage when no layer uses it any more |
| `layout` / `world` | Turning those into a drawing |
| `elevation` / `scene` | A rack in rack units, then the same rack in millimetres for the 3D drawing, with every cable routed through the cable managers |
| `floor_scene` | A floor in millimetres for the 3D drawing: cabinets, the arcs between racks and the cabling to the walls, and each rack's devices for the Devices view |
| `cabling` / `ports` / `power` / `floor_cabling` | Resolved in bulk, never per object |
| `tracing` | Following a path end to end, and a power chain past the PDU |
| `overlays` / `device_overlays` / `site_overlays` | The colourings of each level and their built-ins. `overlays` also holds what the three share: the `Registry`, the legend rules and which colouring a page opens with |
| `palette` | Every colour that carries meaning, in one place |
| `tags` | The tags in use on a floor or in a rack, for the Tags finder |
| `field_filters` | Custom fields offered as filters, the way tags are |
| `geometry` | Footprints, the scale, and the one type size a drawing gets |
| `templatetags/lens` | Static URLs that change whenever the file does, the palette as CSS variables, and the 3D pages' import map |
| `legend.js` | Picking bands, shared by all three levels |
| `finder.js` | Searching and ticking a long list, shared by the map and the rack |
| `state.js` | What a drawing is narrowed to, kept in the URL hash |
| `zoom.js` | Zooming into a floor plan and moving round it, on the floor page and in the editor |
| `floor.js` | The floor: the 3D and 2D switch, the plan's hover card, the find box and the rack table |
| `floor3d.js` | The floor on a 3D stage: cabinets or devices, cabling, filters and the hover card |
| `stage3d.js` | What every 3D drawing shares: loading Three.js, light and shadow, labels, the hover card and clicks, the camera and its views, and the message shown when it cannot be drawn |
| `cabinet3d.js` | A cabinet and its devices as meshes, shared by the rack and the floor's Devices view |
| `rack3d.js` | The rack on a 3D stage: device images, cables and selection |
| `rack_panel.js` | The column beside the rack: port allocation, cabling, reservations and the traced path |
| `world.js` | The MapLibre globe, and the message shown when it cannot be drawn |
| `editor.js` | Dragging and saving a placement |
| `lens.css` | The styles of every page, drawn from the palette's CSS variables |

To add a colouring from another plugin, filter by custom fields, or read a floor through the REST API, see [extending.md](extending.md).
