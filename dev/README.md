# Dev stack

This directory holds the development NetBox for netbox-spatial-lens: a Compose override (`docker-compose.yml`) and one config file (`configuration/plugins.py`). The stack runs on [netbox-docker](https://github.com/netbox-community/netbox-docker) under its own Compose project (`netbox-spatial-lens`), so it does not touch another NetBox stack on the same machine.

## Prerequisites

- Docker with the Compose plugin.
- `uv`, for `make lint` and `make format`.
- Three sibling checkouts beside this repository:

```text
netbox/
├── netbox-spatial-lens/  this repository
├── netbox-docker/        the stack it runs on
├── netbox-demo-data/     the demo database (sql/netbox-demo-v4.7.sql)
└── netbox-branching/     optional, only for `make up BRANCHING=true`
```

```bash
cd ..
git clone https://github.com/netbox-community/netbox-docker.git
git clone https://github.com/netbox-community/netbox-demo-data.git
git clone https://github.com/netboxlabs/netbox-branching.git   # optional
```

## Ports

| Service | Host port |
|---|---|
| NetBox web | 8890 |
| PostgreSQL | 5435 |

## First start

Run every command from the repository root, not from `dev/`.

```bash
make up          # start NetBox 4.7 with the plugin mounted
make demo-data   # drop the database, load netbox-demo-data, migrate (destroys the dev database)
make static      # collect the plugin CSS and JS
make enrich      # fill in footprints, coordinates, cabling and circuits the demo data lacks
make autoplace   # create a floor per site and lay the racks out in rows
make enrich      # again, to draw a plan under each floor autoplace created
```

Open http://localhost:8890 and sign in as `admin` / `admin`.

## Day to day

```bash
make up          # start the stack; the database volume keeps its data
make down        # stop the stack
make reload      # restart NetBox and the worker after a Python or template change
make static      # collect again after a change under static/
make migrate     # apply plugin migrations
make migrations  # generate plugin migrations
make test        # run the test suite in the container
make lint        # ruff check and format --check
make logs        # follow the NetBox log
make shell       # Django shell
```

`make help` lists every target.

## Things to know

- The plugin source is mounted, not installed. A Python or template change needs `make reload`. A change under `static/` needs `make static`.
- `make up BRANCHING=true` also mounts `../netbox-branching` and enables it. `make test` then also runs `tests/test_branching.py`.
- `make up EXAMPLES=true` also enables `dev/lens_examples`, the colourings from `docs/extending.md`, and the `compliancy` custom field filter. `make examples` fills in the fields they read. See [docs/development.md](../docs/development.md#the-extending-examples).
- The override mounts only `configuration/plugins.py` over netbox-docker's config directory, so `configuration.py`, `extra.py` and `logging.py` stay netbox-docker's own.
- After `make demo-data`, a write can fail with `duplicate key value violates unique constraint "core_job_pkey"`, because the dump does not advance the ID sequences. The row itself is often already saved: the error comes from the job queued after the commit. Reset the sequences once. The NetBox image has no `psql`, so `manage.py dbshell` does not work; generate the SQL in the NetBox container and run it in the PostgreSQL container:

```bash
cd ../netbox-docker
docker compose -p netbox-spatial-lens -f docker-compose.yml -f ../netbox-spatial-lens/dev/docker-compose.yml exec -T netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py sqlsequencereset \
  core dcim circuits extras ipam tenancy users virtualization vpn wireless netbox_spatial_lens 2>/dev/null \
  | grep -v "loaded config" > /tmp/seqreset.sql
docker compose -p netbox-spatial-lens -f docker-compose.yml -f ../netbox-spatial-lens/dev/docker-compose.yml exec -T postgres \
  sh -c 'psql -q -U "$POSTGRES_USER" -d netbox' < /tmp/seqreset.sql
```

[docs/development.md](../docs/development.md) describes the bootstrap commands and the tests in more detail.
