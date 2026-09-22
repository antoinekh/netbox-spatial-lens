"""
Rewrite the relative links in README.md to absolute GitHub URLs, for the PyPI project page.

GitHub resolves `docs/images/floor-3d.png` against the repository; PyPI has no repository to
resolve it against, so every capture and every link to a page in docs/ breaks there. The
release workflow runs this before the build, pinned to the release tag, so the page on PyPI
shows the images and pages of the version it describes. The README in the repository keeps its
relative links, which are what GitHub and a local checkout need.

    python .github/scripts/pypi_readme.py v0.4.0
"""

import re
import sys
from pathlib import Path

REPOSITORY = 'antoinekh/netbox-spatial-lens'
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')

# A link target in Markdown, `](target)`, or in an HTML attribute, `src="target"`.
MARKDOWN_TARGET = re.compile(r'(\]\()([^)\s]+)(\))')
HTML_TARGET = re.compile(r'((?:src|srcset|href)=")([^"]+)(")')


def absolute(target: str, ref: str) -> str:
    """The URL a relative `target` has on GitHub at `ref`. Anything else is left as it is."""
    if target.startswith(('http://', 'https://', 'mailto:', '#')):
        return target
    path = target.removeprefix('./')
    if path.lower().endswith(IMAGE_SUFFIXES):
        # raw.githubusercontent.com serves an SVG as text/plain unless asked to sanitise it,
        # and a browser will not draw text/plain as an image.
        query = '?sanitize=true' if path.lower().endswith('.svg') else ''
        return f'https://raw.githubusercontent.com/{REPOSITORY}/{ref}/{path}{query}'
    kind = 'tree' if path.endswith('/') else 'blob'
    return f'https://github.com/{REPOSITORY}/{kind}/{ref}/{path}'


def rewrite(text: str, ref: str) -> str:
    def replace(match: re.Match[str]) -> str:
        before, target, after = match.groups()
        return f'{before}{absolute(target, ref)}{after}'

    return HTML_TARGET.sub(replace, MARKDOWN_TARGET.sub(replace, text))


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f'usage: {sys.argv[0]} <git ref>')
    readme = Path('README.md')
    readme.write_text(rewrite(readme.read_text(encoding='utf-8'), sys.argv[1]), encoding='utf-8')


if __name__ == '__main__':
    main()
