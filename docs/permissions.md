# Permissions

Two questions, and the plugin answers them separately.

1. **May this person use the plugin at all?** That is a permission on the plugin's own three models.
2. **What may they see through it?** That is NetBox's permissions on the inventory, and the plugin does not widen them.

The second one is the point. A drawing is a query result with a picture around it, so a floor plan that ignored NetBox's object permissions would be a way to read cabinets the rest of NetBox refuses to show. Every page here restricts what it draws to the reader's own view of the inventory.

## What to grant

The plugin adds three models. Everything else it draws belongs to NetBox.

| Model | What it is | Grant it to |
|---|---|---|
| `netbox_spatial_lens.floor` | A room: a width, a depth, a site or a location | anyone who opens a floor plan |
| `netbox_spatial_lens.rackplacement` | A rack, an x, a y and a rotation | `view` to read a plan; `add`, `change` and `delete` to use the editor |
| `netbox_spatial_lens.floorlayer` | A scanned plan or photograph under the racks | anyone who should see or manage backgrounds |

A reader needs `view` on all three. Someone laying racks out needs `change` on `netbox_spatial_lens.rackplacement`, which is what the **Edit layout** tab checks before it appears. Putting a rack down from the unplaced panel also needs `add`, and taking a saved rack off the floor needs `delete`; the editor does not offer either action to a user who lacks it. The **Background layers** panel of the editor, where a layer is shown, ordered and calibrated, needs `change` on `netbox_spatial_lens.floorlayer`, and its **Add a layer** button needs `add`.

Grant them as you grant any NetBox permission: **Admin → Permissions → Add**, pick the object types, tick the actions, and assign to users or groups. Object-level constraints work the same way, so a permission on `netbox_spatial_lens.floor` constrained to `{"site__group__name": "Branch Offices"}` gives that group's rooms and no others.

## What the drawings read

None of these are the plugin's own objects, and every one of them is read through the reader's permissions.

| Page | Reads | Restricted on |
|---|---|---|
| World map | Sites, circuits, provider networks, floors, the rack and device counts of each site | `dcim.site`, `circuits.circuit`, `circuits.providernetwork`, `netbox_spatial_lens.floor`, `dcim.rack`, `dcim.device` |
| Site | Floors, rack placements, racks | `netbox_spatial_lens.floor`, `dcim.rack` |
| Floor, in 3D and in 2D | Rack placements, racks, the device count on each rack | `netbox_spatial_lens.rackplacement`, `dcim.rack`, `dcim.device` |
| Floor, cable runs | What a cable leaving the room reaches | `circuits.circuit`, `dcim.rack`, `dcim.site` |
| Floor, Devices view | The devices in each placed rack, with their device type images | `dcim.rack`, `dcim.device` |
| Layout editor | The same, plus the unplaced panel | `dcim.rack` |
| Rack | Devices with their device type images, and the device at the far end of each cable | `dcim.device` |
| Tracing | The starting port, and every port, device, rack, cable, circuit and power feed on the path | `dcim.cable` to trace at all, then each object by its own model |
| REST API, `floors/<pk>/layout/` | The same as the floor | the same as the floor |
| REST API, `floors/<pk>/devices/` | The same as the floor's Devices view | the same as the Devices view |

So a user who may not see a rack does not see it on the floor plan, it is not counted in the strip above the plan, it is not in a legend band, and it is not offered in the editor's unplaced panel. A user who may see a rack but not its contents gets the cabinet and its free space, not an inventory of the machines in it. A user with no circuit permission gets the map without the circuits, rather than every CID, provider and commit rate in the estate.

Where a drawing reaches past what the reader may see, it says so without naming it. A cable from a visible device to a hidden one is drawn, and its far end reads **Restricted**. A trace starts only from a port the reader may view, and answers "no such termination" for any other; along the path, every object the reader may not view is named **Restricted**. A cable leaving the room towards a circuit, rack or site the reader may not view is drawn and labelled "off the plan".

## What this does not do

**It does not hide that something is there.** A rack you may not see is absent from the plan, so the room is drawn with a gap in it and the tally beside it counts what you can see. The plugin will not invent a placeholder for an object it may not name, and it will not pretend the room is smaller than it is.

**A floor is not a permission boundary of its own.** It binds to a site or a location, and it inherits nothing from them. Someone with `view` on every floor sees every room, whatever the racks in them turn out to be. Constrain `netbox_spatial_lens.floor` if the rooms themselves are sensitive.

## Checking it

The behaviour is covered by tests rather than by this document. `netbox_spatial_lens/tests/test_views.py` holds a `PermissionTest` that grants a user `view` on one rack of two and asserts the other is neither drawn nor counted, on the floor and on the world map, and `TraceViewTest` asserts a user who may not read cables is refused a trace. `netbox_spatial_lens/tests/test_visibility.py` covers the rest: a trace from a port the reader may not see, a hop onto a device they may not see, a far end in the rack's cabling, and the API layout. The 3D drawings are covered too: `test_scene.py` asserts a hidden device is not in the rack's scene and a hidden far end is not named, and `test_floor_scene.py` asserts a hidden rack is not in the room and a hidden device is not in the Devices view or its API.
