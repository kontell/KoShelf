"""Render resources/icons/*.png from Material Symbols.

Run: python3 tools/make-icons.py   (needs inkscape; dev-only, not shipped)

Kodi's own Default*.png names cover almost every folder in this add-on and are
preferred, because they resolve out of whichever skin the user runs and so
match their theme. These are only for the handful Kodi has no icon for.

Material Symbols are Apache-2.0. Icons downloaded from fonts.google.com keep
their original file name in tools/ as provenance; the rest are inlined below
because a single path is not worth a file.
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
DEST = ROOT / "resources" / "icons"

# Material Symbols share this viewBox.
VIEWBOX = "0 -960 960 960"
FILL = "#E3E3E3"

# name -> single path d, in the Material Symbols coordinate space.
INLINE = {
    "sort": "M120-240v-80h240v80H120Zm0-200v-80h480v80H120Zm0-200v-80h720v80H120Z",
    "navigate_next": "M504-480 320-664l56-56 240 240-240 240-56-56 184-184Z",
    "login": (
        "M480-120v-80h280v-560H480v-80h280q33 0 56.5 23.5T840-760v560q0 33-23.5 "
        "56.5T760-120H480Zm-80-160-55-58 102-102H120v-80h327L345-622l55-58 200 "
        "200-200 200Z"
    ),
}

# name -> downloaded SVG in tools/, used as-is apart from the fill.
FROM_FILE = {
    "books": "auto_stories_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
    "continue": "books_movies_and_music_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
}

SIZE = 256


def render(name, svg_text):
    DEST.mkdir(parents=True, exist_ok=True)
    tmp = DEST / (name + ".svg")
    tmp.write_text(svg_text)
    try:
        subprocess.run(
            [
                "inkscape",
                str(tmp),
                "--export-type=png",
                "-w",
                str(SIZE),
                "-h",
                str(SIZE),
                "--export-filename={}".format(DEST / (name + ".png")),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        tmp.unlink(missing_ok=True)
    print("  {:<16} {:>6} bytes".format(name, (DEST / (name + ".png")).stat().st_size))


def main():
    for name, d in sorted(INLINE.items()):
        render(
            name,
            '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
            'viewBox="{v}"><path fill="{f}" d="{d}"/></svg>'.format(
                s=SIZE, v=VIEWBOX, f=FILL, d=d
            ),
        )
    for name, filename in sorted(FROM_FILE.items()):
        source = TOOLS / filename
        if not source.exists():
            sys.exit("missing source SVG: {}".format(source))
        svg = source.read_text()
        # Normalise size and fill; the downloads come at 24px and whatever
        # colour was picked in the web UI.
        svg = re.sub(r'height="[^"]*"', 'height="{}px"'.format(SIZE), svg, count=1)
        svg = re.sub(r'width="[^"]*"', 'width="{}px"'.format(SIZE), svg, count=1)
        svg = re.sub(r'fill="[^"]*"', 'fill="{}"'.format(FILL), svg, count=1)
        render(name, svg)


if __name__ == "__main__":
    main()
