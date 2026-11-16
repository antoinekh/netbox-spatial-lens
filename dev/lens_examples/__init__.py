"""
The colourings in docs/extending.md, as a plugin of the dev stack, so they can be seen and captured.

Not a copy of the example. Its `spatial_lens` module reads the code block out of the page and runs
it, the way `tests/test_docs.py` does, so a capture shows what the page says. Nothing is registered
here: the plugin finds that module by itself, which is the mechanism the page documents.

Enabled with `make up EXAMPLES=true`. `make examples` fills in the custom fields they colour by.
"""

from netbox.plugins import PluginConfig


class LensExamplesConfig(PluginConfig):
    name = 'lens_examples'
    verbose_name = 'Spatial Lens examples'
    version = '0.0.0'
    base_url = 'lens-examples'


config = LensExamplesConfig
