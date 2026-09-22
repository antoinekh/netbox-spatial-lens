# Changelog

## Unreleased

- **CI:** GitHub Actions run ruff and the test suite on NetBox 4.7 with Python 3.12 to 3.14, with and without netbox-branching, and publish a GitHub release to PyPI with trusted publishing. The PyPI page gets the README with its captures and links pointed at the release tag.
- **Floor Devices view:** moves more smoothly in a large room: about a quarter of the draw calls per frame on a hall of 80 racks (21,700 before with 1,500 devices, 5,700 after with 1,750). Each device is three draw groups instead of six and shares its box with devices of the same size, the devices of a rack share one chassis material and leave the shadow to the cabinet, each cabinet frame is three merged meshes, and a device's name is painted on a canvas only for a face that has no image.
- **Docs:** retook every 3D capture on a hall of 80 racks in eight rows of ten, to show the plugin at data centre scale, and added a capture of the Devices view narrowed to one row by the find box.
- **Docs:** `extending.md` covers colourings and custom field filters together, with a tested example and a capture for each level.

## v0.3.0 (2026-09-15)

- **Renamed:** the plugin is now NetBox Spatial Lens. Install `netbox-spatial-lens`, and use `netbox_spatial_lens` in `PLUGINS` and `PLUGINS_CONFIG`. The URLs move to `/plugins/spatial-lens/` and `/api/plugins/spatial-lens/`, the rack and site tabs to `spatial-lens/`, the permissions to `netbox_spatial_lens.*`, and the commands to `lens_enrich` and `lens_autoplace`. The migrations were rewritten under the new name, so an existing install must drop its `netbox_atlas_*` tables and migrate again.
- **Menu:** the Spatial Lens entry in NetBox's navigation now has the layers-search icon instead of the floor plan.
- **Site page:** every room is read in one pass, so a site with many rooms costs the same number of queries as a site with one.
- **Docs:** retook every capture under the new name, listed every `lens_enrich` flag, and run `lens_enrich` again after `lens_autoplace` in the first start, so each new floor gets a plan.

## v0.2.0 (2026-09-15)

- **Rack view:** now drawn in 3D with Three.js, replacing the 2D elevation: device type front and rear images, every cable through the cable managers, camera presets.
- **Floor view:** opens in 3D, with cabinets at their real position, rotation and height, coloured by the overlay, cable runs arcing over the racks, and a switch back to the 2D plan.
- **Floor Devices view:** opens every rack to show its real devices and their images, served by the new `GET /api/plugins/atlas/floors/<id>/devices/`.
- **Setting:** `three_base` says where Three.js loads from, for sites with no internet access.
- **Fixed:** OpenStreetMap tiles on the world map load again; the page now sends its origin as `Referer`.

## v0.1.0 (2026-09-15)

First version.

### Added

- **World map:** sites on a MapLibre globe, sized by rack count and coloured by group, status, tenant or region, with the circuits between them coloured by provider.
- **Site page:** a tab on NetBox's site page that draws every room in the site as a small plan, and lists the racks that stand on no floor.
- **Floor plans:** racks at their real positions, coloured by power, cooling, space or role, with a gauge on each rack, a background plan (PNG, JPEG, WebP or GIF), cable runs, zoom and a sortable rack table.
- **Layout editor:** drag, rotate and place racks, or lay them out automatically.
- **Rack view:** the front and rear faces with ports, cabling, reserved units and free space, coloured by role, status, tenant, cabling or power.
- **Tracing:** a network path through patch panels to a provider, and a power chain from socket to feed.
- **Legends and finders that filter:** pick several legend bands, tick rows, find racks and devices by name or asset tag, and narrow them by tag or by a select custom field; what you picked is kept in the URL.
