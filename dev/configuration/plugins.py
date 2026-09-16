# netbox-spatial-lens, plus the extending examples and netbox-branching when the stack is started with them.
#
# Branching is off by default: the plugin does not depend on it, and leaving it out keeps the
# stack close to a plain NetBox. `make up BRANCHING=true` turns it on, which is how the plugin
# is checked against a branch. See the Makefile.
import os
import sys

PLUGINS = ['netbox_spatial_lens']

PLUGINS_CONFIG = {
    'netbox_spatial_lens': {},
}

# The extending examples, off by default so the stack shows the plugin as installed: the
# colourings from docs/extending.md, and the demo's rack and device custom field offered as a
# filter. `make up EXAMPLES=true` turns them on; listed after the plugin they extend.
if os.environ.get('LENS_EXAMPLES', 'false').lower() == 'true':
    PLUGINS.append('lens_examples')
    PLUGINS_CONFIG['netbox_spatial_lens']['filter_custom_fields'] = ['compliancy']

if os.environ.get('NETBOX_BRANCHING', 'false').lower() == 'true':
    from netbox_branching.utilities import DynamicSchemaDict

    # netbox-branching must be last in PLUGINS, and it serves every request from a schema it
    # picks at request time, so DATABASES has to be its dict subclass and its router has to be
    # installed. The connection settings are still the ones netbox-docker built from the
    # environment: this file loads after configuration.py, so it re-wraps what that made rather
    # than restating the host, name and password.
    PLUGINS.append('netbox_branching')
    PLUGINS_CONFIG['netbox_branching'] = {}

    DATABASES = DynamicSchemaDict(sys.modules['netbox.configuration.configuration'].DATABASES)
    DATABASE_ROUTERS = ['netbox_branching.database.BranchAwareRouter']
