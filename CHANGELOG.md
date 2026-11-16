# Changelog

## Unreleased

- **Docs:** the README shows a 15 second showreel video below the introduction.
- **World map:** the racks and the devices of the sites are counted in one query each. Counted together, the database joined every rack of a site with every device of it, so a site of 500 racks and 20,000 devices cost ten million rows.
- **Floor Devices view:** the server answers faster on a large floor. The tags of all the devices are read in one query, and each device type and role is read once instead of once per device: about 1 s before and 350 ms after on a hall of 80 racks and 2,200 devices.
- **Rack view:** the cable queries of a rack no longer join the cable table to sort their rows.
- **Floor plans:** the cable run queries no longer join and sort on the cable table, which the totals do not need, and the racks not yet placed are counted by the database instead of read in full.
- **Fixed:** the world map counts only the racks and the devices the reader may view. The site markers, the hover cards and the figures above the map counted every rack and device of a site.
- **Fixed:** in the layout editor, a second Save after a failure sends only the changes that failed. It sent every change again, so a rack placed by the first Save was refused by the second, and the editor could not finish the save.
- **Fixed:** the rack view draws a cable between a mounted device and a device of the same rack that has no U position. The cable was dropped when its A end was on the device with no position.
- **Fixed:** the power figure of a rack on the floor agrees with NetBox in three more cases: a PDU inlet that declares its own draw, a PDU fed by another PDU, and a PDU with a second inlet that no feed of the rack supplies. The floor and the rack view now use the same calculation.
- **Fixed:** with Cable runs on, a cable to something of the same site that stands in no rack (a power feed, a wall-mounted device) is drawn as "Off the plan". It was drawn and counted as "To another site", under the name of its own site.
- **Fixed:** the world map does not draw a provider network the reader may not view, nor the circuits that end on it.
- **Fixed:** a floor needs a width and a depth above zero, and a background layer a width and a height above zero. A zero or negative size was accepted and gave a plan that could not be drawn. Run `manage.py migrate` after the upgrade.
- **Fixed:** in the rack view, a cable between two ports of one device is listed once under that device, not twice.
- **Fixed:** on the 2D plan and in the layout editor, the name of a rack turned to face down the plan is upright. It was drawn upside down.
- **Import:** floors, rack placements and background layers can be imported from CSV, YAML or JSON with the Import button of each list. A row names its site, then the floor and the rack by name. The button was shown before, with no page behind it.
- **Fixed:** on the 2D plan, a cable run recedes with its racks when a legend band, the find box or a finder narrows the room, as it does in 3D. The runs stayed at full strength over the dimmed racks.
- **3D drawings:** the stage is as tall as the window leaves, so the whole room or rack is on the first screen, and a camera preset is fitted again when the window changes size. The world map and the 2D plan follow the same rule.
- **Floor in 3D:** rack names no longer overlap. A name gives way to a nearer one and comes back when you zoom in, turn the room or hover its rack.
- **Toolbars:** only the colouring keeps the primary colour. The 3D and 2D switch, Cable runs, the camera presets and the display controls are neutral buttons, and the Names button says its name.
- **Figures and site page:** the figures above a drawing stand on the card itself instead of each in a grey tile, with a dot in the colour of their band. On the site page each room is a NetBox card, no longer a box inside a card, and the racks on no floor have a card of their own.
- **Fixed:** the floor plan, the layout editor and the port allocation bars are drawn correctly for a reader whose language writes a comma for the decimal mark (French, German). The numbers in the SVG were written with the comma, so the racks were drawn at wrong positions.

## v0.4.0 (2026-09-22)

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
