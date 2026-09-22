###################################################################
#  Base configuration for running the test suite in CI.           #
#  Not intended for production use.                               #
###################################################################
import os

ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'NAME': 'netbox',
        'USER': 'netbox',
        'PASSWORD': 'netbox',
        'HOST': 'localhost',
        'PORT': '',
        'CONN_MAX_AGE': 300,
    },
}

PLUGINS = ['netbox_spatial_lens']

PLUGINS_CONFIG = {
    # Left at its defaults so the suite exercises the shipped behaviour. Individual tests
    # override what they need.
    'netbox_spatial_lens': {},
}

# netbox-branching is optional. The job that installs it sets LENS_BRANCHING, which also runs
# tests/test_branching.py; every other job checks the plugin on a plain NetBox.
if os.environ.get('LENS_BRANCHING', 'false').lower() == 'true':
    from netbox_branching.utilities import DynamicSchemaDict

    # netbox-branching must be last in PLUGINS, and it serves every request from a schema it
    # picks at request time, so DATABASES has to be its dict subclass and its router has to be
    # installed.
    PLUGINS.append('netbox_branching')
    PLUGINS_CONFIG['netbox_branching'] = {}
    DATABASES = DynamicSchemaDict(DATABASES)
    DATABASE_ROUTERS = ['netbox_branching.database.BranchAwareRouter']

REDIS = {
    'tasks': {
        'HOST': 'localhost',
        'PORT': 6379,
        'PASSWORD': '',
        'DATABASE': 0,
        'SSL': False,
    },
    'caching': {
        'HOST': 'localhost',
        'PORT': 6379,
        'PASSWORD': '',
        'DATABASE': 1,
        'SSL': False,
    },
}

# NetBox 4.7 raises InvalidMailer when something sends mail and no server is named. The plugin
# sends none; this is only so a test which does cannot fail for a reason unrelated to the plugin.
EMAIL = {
    'SERVER': 'localhost',
    'PORT': 25,
}

SECRET_KEY = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

API_TOKEN_PEPPERS = {
    1: 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
}
