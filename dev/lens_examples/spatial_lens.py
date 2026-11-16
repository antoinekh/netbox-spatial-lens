"""
The example module of docs/extending.md, run from the page itself.
"""

import re
from pathlib import Path

EXTENDING = Path(__file__).resolve().parents[2] / 'docs' / 'extending.md'

_example = next(
    block
    for block in re.findall(r'```python\n(.*?)```', EXTENDING.read_text(), flags=re.S)
    if block.startswith('# yourplugin/spatial_lens.py')
)
exec(compile(_example, str(EXTENDING), 'exec'))
