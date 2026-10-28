"""Draw the LiOD logo as SVG paths (no font needed to display it): the letters on top, the i
in the accent colour, and the tagline underneath ending under the D, as in
static/img/logo-liod.svg.

    manage.py make_logo
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONTS = settings.BASE_DIR / "static" / "fonts" / "outfit"
OUT = settings.BASE_DIR / "static" / "img"
TAGLINE = "Location Intelligence from OpenData"
# (letters, accent, tagline) colours for light and dark backgrounds
THEMES = {
    "logo-liod.svg": ("#14294A", "#12B3A6", "#5A6A83"),
    "logo-liod-light.svg": ("#FFFFFF", "#5EE0D3", "#BFD3EA"),
}


def text_paths(font, text, size, x, baseline, tracking=0.0):
    """[(char, svg path, start x)] for `text` set at `size` px from (x, baseline), and the
    end x."""
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    paths = []
    for char in text:
        name = cmap[ord(char)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        paths.append((char, pen.getCommands(), x))
        x += glyphs[name].width * scale + tracking
    return paths, x - tracking


class Command(BaseCommand):
    help = "Draw the LiOD logo (SVG paths) in static/img"

    def handle(self, *args, **options):
        bold = TTFont(FONTS / "outfit-latin-700.woff")
        medium = TTFont(FONTS / "outfit-latin-400.woff")
        letters, end = text_paths(bold, "LiOD", 78, 0, 70, tracking=4)
        # the tagline is fitted to end under the D, starting under the I
        start = letters[1][2]
        _probe, probe_end = text_paths(medium, TAGLINE, 13, 0, 0, tracking=0.3)
        size = 13 * (end - start) / probe_end
        tagline, _end = text_paths(medium, TAGLINE, size, start, 92, tracking=0.3 * size / 13)
        width, height = round(end) + 2, 100
        for filename, (ink, accent, muted) in THEMES.items():
            parts = [
                f'<path fill="{accent if char == "i" else ink}" d="{d}"/>'
                for char, d, _x in letters
            ]
            parts.append(f'<path fill="{muted}" d="{"".join(d for _c, d, _x in tagline)}"/>')
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
                f'width="{width}" height="{height}" role="img" '
                f'aria-label="LiOD: {TAGLINE}">{"".join(parts)}</svg>\n'
            )
            (OUT / filename).write_text(svg, encoding="utf-8")
            self.stdout.write(f"{OUT / filename}")
        self.header(bold, medium)

    def header(self, bold, medium):
        """A wide version for the site header, footers and report covers, where the stacked
        tagline would be too small: the letters, a thin rule, then the tagline beside them."""
        letters, end = text_paths(bold, "LiOD", 78, 0, 70, tracking=4)
        rule_x = end + 16
        first, end1 = text_paths(medium, "Location Intelligence", 25, rule_x + 16, 40)
        second, end2 = text_paths(medium, "from OpenData", 25, rule_x + 16, 70)
        width, height = round(max(end1, end2)) + 4, 84
        tagline = "".join(d for _c, d, _x in first + second)
        for source, filename in (
            ("logo-liod.svg", "logo-liod-header.svg"),
            ("logo-liod-light.svg", "logo-liod-header-light.svg"),
        ):
            ink, accent, muted = THEMES[source]
            parts = [
                f'<path fill="{accent if char == "i" else ink}" d="{d}"/>'
                for char, d, _x in letters
            ]
            parts.append(f'<rect x="{rule_x:.1f}" y="14" width="2" height="58" fill="{accent}"/>')
            parts.append(f'<path fill="{muted}" d="{tagline}"/>')
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
                f'width="{width}" height="{height}" role="img" '
                f'aria-label="LiOD: {TAGLINE}">{"".join(parts)}</svg>\n'
            )
            (OUT / filename).write_text(svg, encoding="utf-8")
            self.stdout.write(f"{OUT / filename}")
