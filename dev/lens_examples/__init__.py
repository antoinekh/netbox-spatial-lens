"""
The colourings in docs/extending.md, registered in the dev stack so they can be seen and captured.

Not a copy of the examples. The code blocks are read out of the page and run, the way
`tests/test_docs.py` runs them, so a capture shows what the page says. The page's own registration
block is the plugin config: this only gives it a name NetBox can load.

Enabled with `make up EXAMPLES=true`. `make examples` fills in the custom fields they colour by.
"""

import re
import sys
import types
from pathlib import Path

EXTENDING = Path(__file__).resolve().parents[2] / 'docs' / 'extending.md'


def _blocks() -> dict[str, str]:
    """Every Python block in docs/extending.md, by its first line."""
    blocks = re.findall(r'```python\n(.*?)```', EXTENDING.read_text(), flags=re.S)
    return {block.splitlines()[0]: block for block in blocks}


def _load(name: str, source: str) -> None:
    """Run `source` as the module `lens_examples.<name>`, so a relative import finds it."""
    module = types.ModuleType(f'{__name__}.{name}')
    exec(source, module.__dict__)
    sys.modules[module.__name__] = module


_examples = _blocks()
for _name in ('lens', 'support', 'tiers'):
    _load(_name, _examples[f'# yourplugin/{_name}.py'])

# The registration block, run as this package, so `from .lens import ...` in its `ready()` resolves.
_registration: dict = {'__name__': __name__, '__package__': __name__}
exec(_examples['# yourplugin/__init__.py'], _registration)


class LensExamplesConfig(_registration['YourPluginConfig']):
    name = 'lens_examples'
    verbose_name = 'Spatial Lens examples'
    version = '0.0.0'
    base_url = 'lens-examples'


config = LensExamplesConfig
