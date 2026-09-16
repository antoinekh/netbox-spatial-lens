# Development

The dev stack, the demo database, and the two commands that fill it. None of this is needed to run the plugin: it exists so there is something to look at while working on it.

## The stack

It runs on [netbox-docker](https://github.com/netbox-community/netbox-docker), in its own Compose project, on its own port, so it does not disturb another NetBox stack on the same machine. `dev/` holds the whole of it: a Compose override and one config file. Two sibling checkouts are expected beside this one:

```text
netbox/
├── netbox-spatial-lens/  this repository
├── netbox-docker/        the stack it runs on
└── netbox-demo-data/     the database it is tested against
```

```bash
make up          # start the stack (NetBox 4.7 on http://localhost:8890)
make demo-data   # drop the database and load netbox-demo-data, then migrate
make static      # collect the plugin's CSS and JS
make enrich      # fill in the fields the demo data leaves blank
make autoplace   # create a floor per site and lay its racks out in rows
make enrich      # again, to draw a plan under each floor autoplace created
make test        # run the test suite
```

The override mounts only `dev/configuration/plugins.py` over netbox-docker's own config directory, so `configuration.py`, `extra.py` and `logging.py` stay netbox-docker's and cannot drift from it.

Sign in as `admin` / `admin`. `make help` lists the rest: `reload`, `migrations`, `shell`, `logs`, `lint`, `format`.

Two of these are easy to forget. **A plugin on `PYTHONPATH` is not collected by the entrypoint**, so run `make static` after touching anything under `static/`. And a template change needs `make reload`, not `make static`. [docs/gotchas.md](gotchas.md) has the rest.

## Filling the demo database

netbox-demo-data is an inventory, not a floor plan. It records no rack footprints, no coordinates, no cooling, and most of its racks are empty, so the views have almost nothing to draw. Two commands close that gap.

### `lens_enrich`

Fills in the fields this plugin draws with, and **never overwrites a value that is already there**. Run with no flags it does everything; each flag does one part.

| Flag | Fills in |
|---|---|
| `--racks` | Rack footprints, cooling and airflow |
| `--geo` | Site latitude and longitude, so the world map has points |
| `--fill` | Mounts devices in racks that stand empty |
| `--cable` | Cables and powers the devices `--fill` mounted |
| `--circuits` | Circuits between sites, so the map has links |
| `--europe` | European sites and transatlantic circuits, for a worldwide map |
| `--uplinks` | A cable from each rack's top-of-rack switch to a pair of spines in other racks |
| `--plans` | A schematic architect drawing under each floor, so the background-layer feature has something to show |
| `--all` | Everything above, the same as no flag |
| `--seed` | The random seed, so a run repeats (default: `1`) |

`--plans` draws only under floors that already exist, so run the command again after `lens_autoplace` creates them.

### `lens_autoplace`

Creates a floor per site and lays its unplaced racks out in rows.

> [!CAUTION]
> This is a bootstrap aid for a demo or development database. **Do not run it against a production NetBox.** It invents a room that does not exist: racks in tidy rows, a room sized to fit them, and no relationship to the building. A floor plan whose whole value is that it matches the real room is worth nothing when it was generated, and once the racks are placed nobody can tell which positions were measured and which were guessed. Draw the real room instead: the README's [Your first floor](../README.md#your-first-floor) is three steps.

It never moves a rack somebody has already placed, unless you pass `--replace`.

```bash
# Every site with racks, one floor each.
manage.py lens_autoplace

# One site, in a room of a stated size.
manage.py lens_autoplace ncsu-065 --width 40 --depth 25

# One floor per location rather than one per site, which is the shape a site
# with named rows or halls actually has.
manage.py lens_autoplace ncsu-065 --per-location
```

In the demo data, `MDF` is the site worth looking at: 26 racks, of which 24 are in three rows of eight. With `--per-location` it becomes four rooms, which is what the site page is for.

## The extending examples

`make up EXAMPLES=true` starts the stack with `dev/lens_examples`, a plugin that reads the examples out of [extending.md](extending.md) and registers them: **Heat** on the floor, **Support** in the rack view and **Tier** on the world map. It also offers the demo's `compliancy` custom field as a filter. Without the flag, the stack shows only what the plugin ships.

```bash
make up EXAMPLES=true   # the stack, with the examples registered
make static             # again: recreating the containers drops the collected files
make examples           # create heat_load_kw, support_end and service_tier, and fill them in
```

`make examples` never overwrites a value, and takes the same seed each run. `make test` runs inside the running stack, so with the examples on, the suite also sees their colourings.

## Branching

The dev stack leaves [netbox-branching](https://github.com/netboxlabs/netbox-branching) out by default. `make up BRANCHING=true` mounts a sibling `netbox-branching` checkout and enables it, and `make test` then also runs `tests/test_branching.py`, which is skipped without it.

## Tests

```bash
make test        # the whole suite, inside the container
make lint        # ruff check and format --check
make format      # apply ruff fixes
```

The suite reuses its database between runs. A test that changes a migration needs it dropped: `make demo-data`.

Every behaviour here is meant to be covered by a test rather than by a paragraph. [Permissions](permissions.md) says which tests cover the permission rules, and the query-count tests in `tests/test_elevation.py` are the guard against a drawing quietly becoming one query per object.
