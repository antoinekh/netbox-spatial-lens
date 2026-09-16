<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg" />
    <img src="docs/images/logo.svg" width="460" alt="netbox spatial lens" />
  </picture>
  <p><strong>Your estate through one lens: world, floor and rack, drawn from NetBox and recoloured by what you need to see</strong></p>
  <p>world &bull; site &bull; floor &bull; rack</p>
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/NetBox-%3E%3D%204.7.0%2C%20%3C%204.8-00857d" alt="NetBox compatibility" />
  <img src="https://img.shields.io/badge/python-%3E%3D%203.12-blue" alt="Python version" />
  <p>
    <strong><a href="docs/">Documentation</a></strong> |
    <strong><a href="COMPATIBILITY.md">Compatibility</a></strong> |
    <strong><a href="docs/configuration.md">Configuration</a></strong> |
    <strong><a href="docs/permissions.md">Permissions</a></strong> |
    <strong><a href="docs/extending.md">Extending</a></strong> |
    <strong><a href="CHANGELOG.md">Changelog</a></strong>
  </p>
</div>

A lens does two things to what you point it at: it brings one place into focus, and it filters what you see there. That is what this is for a network. The world map, the floor plan and the rack in 3D are the same estate at three focal lengths, one click apart, and every one of them recolours on demand by whatever you came to find out.

A NetBox plugin. NetBox knows a rack's height, footprint, power feeds and cooling capability. It does not know where the rack stands in the room, and it will not colour a room by any of those values. This draws the room and colours it.

> [!NOTE]
> **Cowritten with AI.** The code, tests and documents were written with Claude, under a human's direction and review.

> [!WARNING]
> **Not stable yet.** The version is below 1.0. Models, settings and APIs can still change between releases. Read the [changelog](CHANGELOG.md) before you upgrade.

<p align="center">
  <a href="#what-it-does">What it does</a> |
  <a href="#getting-started">Getting started</a> |
  <a href="#where-the-ideas-come-from">Where the ideas come from</a> |
  <a href="#documentation">Documentation</a>
</p>

## What it does

**World → site → floor → rack**, one click each way. Every drawing has a stat strip above it and a legend that filters it.

### The world map

Sites on a globe, sized by rack count and coloured by **group**, **status**, **tenant** or **region**, with the circuits between them coloured by **provider**. The two legends and the **Sites** and **Circuits** finders narrow the map. It needs WebGL and MapLibre, which loads from a CDN by default or from your own copy; tiles are optional.

![A globe with sites in North America and Europe, circuits drawn as great circles across the Atlantic, and two legends naming the site groups and the circuit providers](docs/images/world.png)

### The site

Every room in the site as a small plan with its own figures, on a tab of NetBox's site page.

![The MDF site drawn as four rooms side by side, each with its rack, device, space and power figures above a thumbnail of its real floor plan](docs/images/site.png)

### The floor

The room in 3D, every rack a cabinet at its real position, rotation and height, coloured by **power**, **cooling**, **space** or **role**, with the reading rising up its doors and the cable runs arcing over the tops. Look from the top, at three quarters or from the side, and switch from **Cabinets** to **Devices** to see every rack open with its real devices and their front and rear images. Switch to **2D** for the plan over a scanned drawing, with zoom. Both views share a sortable rack table. Find racks by name or asset tag, narrow them by tag or custom field, and place them in the layout editor.

![A row of eight cabinets standing on a metre grid, their roofs and doors coloured by how full they are, the cables leaving the row running from their tops to the walls, and the hover card of one rack](docs/images/floor-3d.png)

![Row 3 in the Devices view: eight open cabinets on the metre grid, each with its real devices and their rear panels, roofs coloured by rack role, and the hover card of one server naming its rack, type and unit](docs/images/floor-devices.png)

### The rack

The cabinet in 3D, with the real front and rear images of each device type, every cable run through the cable managers, and reserved and free units. Turn it, move it and zoom, or jump to the front, the rear or the side. Devices are coloured by **role**, **status**, **tenant**, **cabling** or **power**. Find devices by name or asset tag, and narrow them by tag or custom field. It needs WebGL and Three.js, which loads from a CDN by default or from your own copy.

![A 48U cabinet seen from behind and to the side, the switch at the top and the servers below it wearing their real rear panels, the data cables dressed up one cable manager and the power leads up the other, beside the port allocation and cabling panels](docs/images/rack.png)

### On every level

In the rack, click a cable, or a row of the cabling list, to trace it end to end, through patch panels and out to a provider, or along a power chain from socket to feed. On the floor, a cable leaving the room opens the cable, or the circuit it reaches.

## Getting started

Install it like any NetBox plugin: `pip install netbox-spatial-lens`, add `netbox_spatial_lens` to `PLUGINS`, and migrate. It also works inside [netbox-branching](https://github.com/netboxlabs/netbox-branching) branches.

### Your first floor

1. **Draw the room:** **Spatial Lens > Floors > Add**. Give its width and depth, and bind it to a **site** (one room) or a **location** (several rooms).
2. **Place the racks:** open the floor, choose **Edit layout**, then drag each rack from the list onto the plan and rotate it. Rack sizes come from NetBox.
3. **Look at it:** colour by power, cooling, space or role, and click a rack to open it.

Optional: add a background plan, and set site coordinates for the world map.

For the development stack, the demo database, and the commands that populate it, see [docs/development.md](docs/development.md).

## Where the ideas come from

- **[net3d](https://github.com/hervehildenbrand/net3d)**: the zoom-through navigation, cable tracing and power chains. Not its architecture, which is a standalone Node app reading the REST API from outside.
- **[NetBox Labs Visual Explorer](https://netboxlabs.com/docs/visual-explorer/floorplans/)**: the geometry model, one queryable row per placement. It has no overlays, which is our reason to exist.
- **[netbox-floorplan-plugin](https://github.com/netbox-community/netbox-floorplan-plugin)**: read as a one-shot importer. Its plan is a Fabric.js blob with no coordinate columns, so an overlay over it would be a JSON walk per rack.
- **[netbox-demo-data](https://github.com/netbox-community/netbox-demo-data)**: what everything is tested against.

## Documentation

| | |
|---|---|
| [Compatibility](COMPATIBILITY.md) | Which NetBox versions each release supports |
| [Configuration](docs/configuration.md) | Every setting, and a site with no internet access |
| [Extending](docs/extending.md) | Colouring from another plugin, filtering by custom fields, and the floor layout API |
| [Modules](docs/modules.md) | What each module and script holds |
| [Permissions](docs/permissions.md) | What to grant, and what each page reads |
| [Development](docs/development.md) | The dev stack, the demo database, and the commands that fill it |
| [Gotchas](docs/gotchas.md) | What NetBox and this stack do that is not obvious |
