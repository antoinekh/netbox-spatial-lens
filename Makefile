# netbox-spatial-lens development stack.
#
# Its own Compose project, database and ports, so it runs beside the netbox-change-control
# stacks without disturbing them. Run every target from the repository root.

COMPOSE_PROJECT := netbox-spatial-lens
NETBOX_DOCKER   := ../netbox-docker
DEMO_SQL        := ../netbox-demo-data/sql/netbox-demo-v4.7.sql
# Start the stack with netbox-branching alongside the plugin: `make up BRANCHING=true`.
BRANCHING       ?= false
# Start the stack with the colourings from docs/extending.md registered: `make up EXAMPLES=true`.
EXAMPLES        ?= false
RUN := cd $(NETBOX_DOCKER) && NETBOX_BRANCHING=$(BRANCHING) LENS_EXAMPLES=$(EXAMPLES) docker compose -p $(COMPOSE_PROJECT) -f docker-compose.yml -f ../netbox-spatial-lens/dev/docker-compose.yml
EXEC := $(RUN) exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py

.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: up
up:  ## Start the stack with the plugin mounted
	$(RUN) up -d

.PHONY: down
down:  ## Stop the stack
	$(RUN) down

.PHONY: reload
reload:  ## Restart NetBox and the worker to pick up source changes
	$(RUN) restart netbox netbox-worker

.PHONY: migrations
migrations:  ## Generate migrations for the plugin
	$(RUN) exec -T --user $(shell id -u):$(shell id -g) netbox \
	  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py makemigrations netbox_spatial_lens

.PHONY: migrate
migrate:  ## Apply the plugin migrations
	$(EXEC) migrate netbox_spatial_lens

.PHONY: demo-data
demo-data:  ## Drop the database and load the NetBox demo data, then migrate
	@echo "This destroys the $(COMPOSE_PROJECT) database."
	$(RUN) stop netbox netbox-worker
	docker cp $(DEMO_SQL) $$($(RUN) ps -q postgres):/tmp/demo.sql
	$(RUN) exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d postgres -q -c "DROP DATABASE IF EXISTS netbox;"'
	$(RUN) exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d postgres -q -c "CREATE DATABASE netbox OWNER \"$$POSTGRES_USER\";"'
	@# The dump assigns the public schema to a "postgres" role this cluster does not have, and
	@# its header empties search_path, which leaves the ltree operators in the trigger WHEN
	@# clauses unresolvable. Both lines are rewritten before loading.
	$(RUN) exec -T postgres sh -c 'sed -e "s/^ALTER SCHEMA public OWNER TO postgres;/ALTER SCHEMA public OWNER TO \"$$POSTGRES_USER\";/" -e "s/^SELECT pg_catalog.set_config(.search_path., .., false);/SELECT pg_catalog.set_config('"'"'search_path'"'"', '"'"'public'"'"', false);/" /tmp/demo.sql > /tmp/demo-fixed.sql'
	$(RUN) exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d netbox -q -v ON_ERROR_STOP=1 -f /tmp/demo-fixed.sql'
	$(RUN) start netbox
	@echo "Waiting for NetBox to migrate the plugin tables in..."
	$(RUN) up -d --wait netbox netbox-worker

.PHONY: static
static:  ## Collect the plugin's CSS and JS into NetBox's static directory
	@# Runs as root: the static directory is owned by root in the image, and a plugin mounted
	@# on PYTHONPATH rather than pip-installed is not collected by the entrypoint.
	$(RUN) exec -T --user root netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py collectstatic --no-input

.PHONY: enrich
enrich:  ## Fill in the fields the demo data leaves blank, so the views have something to draw
	$(EXEC) lens_enrich --all

.PHONY: autoplace
autoplace:  ## Create a floor per site and lay its racks out in rows
	$(EXEC) lens_autoplace

.PHONY: examples
examples:  ## Fill in the custom fields the extending examples colour by (needs `make up EXAMPLES=true`)
	$(EXEC) lens_examples_data

.PHONY: test
test:  ## Run the plugin test suite inside the container
	$(EXEC) test netbox_spatial_lens --keepdb -v 2

.PHONY: shell
shell:  ## Django shell
	$(RUN) exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell

.PHONY: logs
logs:  ## Follow the NetBox log
	$(RUN) logs -f netbox

.PHONY: check
check:  ## Django system checks
	$(EXEC) check

.PHONY: lint
lint:  ## ruff check and format --check
	uvx ruff@0.14.5 check netbox_spatial_lens
	uvx ruff@0.14.5 format --check netbox_spatial_lens

.PHONY: format
format:  ## Apply ruff fixes
	uvx ruff@0.14.5 check --fix netbox_spatial_lens
	uvx ruff@0.14.5 format netbox_spatial_lens
