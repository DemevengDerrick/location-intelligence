"""Regulatory red flags (TRD §4): setback strips, protected areas, public-utility (DUP) zones,
infrastructure corridors and custom risk zones over or near the parcel.

Setback rules are admin-editable (SiteSetting "setback_rules"); features come from the local
OpenStreetMap copy and the admin-maintained reference layers (FR-50). Distances are measured
from mapped centrelines and outlines, so they are indicative: the commune's urban planning
office has the final word.
"""

import math

from django.contrib.gis.geos import GeometryCollection, Polygon
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.gazetteer.models import ReferenceLayer, ReferenceLayerKind
from apps.osm.models import Category
from apps.osm.queries import in_box
from apps.parcels.geometry import utm_srid_for

from ..config import setback_rules, thresholds
from ..formatting import fmt
from ..layers import vector_layer
from ..maps import ParcelMap
from ..models import Rating
from ..providers import osm_provider
from .base import Module, ModuleOutput
from .imagery import radius_bounds

MIN_OVERLAP_M2 = 1  # below this, an overlap is a mapping artefact
AREA_KINDS = {
    ReferenceLayerKind.PROTECTED_AREA: "protected",
    ReferenceLayerKind.DUP_CORRIDOR: "dup",
    ReferenceLayerKind.INFRASTRUCTURE: "infrastructure",
    ReferenceLayerKind.RISK_ZONE: "risk_zone",
}
STYLE = {
    "setback": {"facecolor": "#F6A04D", "edgecolor": "#B35806", "alpha": 0.45, "hatch": "///"},
    "protected": {"facecolor": "#A6DBA0", "edgecolor": "#1B7837", "alpha": 0.5, "hatch": "\\\\"},
    "dup": {"facecolor": "#F4A582", "edgecolor": "#B2182B", "alpha": 0.5, "hatch": "xx"},
    "infrastructure": {"facecolor": "#D8B365", "edgecolor": "#8C510A", "alpha": 0.5},
    "risk_zone": {"facecolor": "#FEE08B", "edgecolor": "#D73027", "alpha": 0.5, "hatch": ".."},
}
LINE_COLOURS = {
    "waterway": "#2166AC",
    "road": "#555555",
    "railway": "#111111",
    "power_line": "#762A83",
    "coastline": "#2166AC",
    "water": "#2166AC",
}


def _union(geoms):
    geoms = [g for g in geoms if g and not g.empty]
    if not geoms:
        return None
    return GeometryCollection(*geoms, srid=geoms[0].srid).unary_union


def _in_language(value):
    """A {"fr": ..., "en": ...} label in the active language (plain strings pass through)."""
    if isinstance(value, dict):
        return value.get(translation.get_language() or "fr") or value.get("en", "")
    return value or ""


class RedFlagsModule(Module):
    name = "red_flags"
    title = gettext_lazy("Regulatory red flags")

    def run(self, parcel):
        t = thresholds()
        rules = setback_rules()
        osm = osm_provider()
        if osm is None:
            raise RuntimeError("No OpenStreetMap import is loaded (manage.py load_osm)")
        geom = parcel.geometry
        srid = utm_srid_for(geom.centroid)
        parcel_m = geom.transform(srid, clone=True)
        x0, y0, x1, y1 = parcel_m.extent
        half_diagonal = math.hypot(x1 - x0, y1 - y0) / 2
        widest = max([r["distance_m"] for r in rules] or [0])
        reach = half_diagonal + max(widest, t.constraint_near_m) + 50
        bounds = radius_bounds(geom.centroid, reach)

        constraints, strips, drawn_lines = [], [], []
        for rule in rules:
            features = [
                f
                for f in in_box(osm, rule["category"], *bounds)
                if not rule.get("kinds") or f.kind in rule["kinds"]
            ]
            if not features:
                continue
            drawn_lines += [(rule["category"], f.geom) for f in features]
            strip = _union(
                [f.geom.transform(srid, clone=True).buffer(rule["distance_m"]) for f in features]
            )
            overlap = parcel_m.intersection(strip).area if strip else 0
            if overlap < MIN_OVERLAP_M2:
                continue
            strips.append(strip)
            names = sorted({f.name for f in features if f.name and strip.intersects(parcel_m)})
            constraints.append(
                {
                    "type": "setback",
                    "key": rule["key"],
                    "label": rule["label"],
                    "name": ", ".join(names[:3]),
                    "overlap_m2": round(overlap),
                    "overlap_pct": round(overlap / parcel_m.area * 100, 1),
                    "distance_m": 0,
                    "basis": rule.get("basis"),
                    "confirmed": bool(rule.get("confirmed")),
                }
            )
        setback_union = _union(strips)
        setback_pct = (
            round(parcel_m.intersection(setback_union).area / parcel_m.area * 100, 1)
            if setback_union
            else 0.0
        )

        areas = self._areas(osm, bounds)
        for kind, name, source, shape in areas:
            shape_m = shape.transform(srid, clone=True)
            distance = parcel_m.distance(shape_m)
            if distance > t.constraint_near_m:
                continue
            overlap = parcel_m.intersection(shape_m).area if shape_m.dims == 2 else 0
            constraints.append(
                {
                    "type": kind,
                    "key": kind,
                    "label": None,
                    "name": name,
                    "source": source,
                    "overlap_m2": round(overlap) if overlap >= MIN_OVERLAP_M2 else 0,
                    "overlap_pct": round(overlap / parcel_m.area * 100, 1)
                    if overlap >= MIN_OVERLAP_M2
                    else 0.0,
                    "distance_m": round(distance),
                    "basis": None,
                    "confirmed": True,
                }
            )
        results = {
            "constraints": constraints,
            "setback_overlap_pct": setback_pct,
            "buildable_pct": round(100 - setback_pct, 1),
            "search_m": t.constraint_near_m,
            "osm_data": osm.data_timestamp,
            "reference_features": ReferenceLayer.objects.filter(is_active=True).count(),
        }
        rating = self._rate(results, t)

        def draw():
            figure = ParcelMap(geom, extent=max(150, half_diagonal * 2.5))
            labels = {
                "protected": _("Protected area"),
                "dup": _("Public-utility (DUP) zone"),
                "infrastructure": _("Infrastructure corridor"),
                "risk_zone": _("Risk zone"),
            }
            seen = set()
            for kind, _name, _source, shape in areas:
                if shape.dims == 2:
                    figure.add(
                        shape,
                        label=labels[kind] if kind not in seen else None,
                        zorder=2,
                        linewidth=0.8,
                        **STYLE[kind],
                    )
                else:
                    for line in _lines(shape):
                        figure.add_line(
                            line,
                            label=labels[kind] if kind not in seen else None,
                            color=STYLE[kind]["edgecolor"],
                            linewidth=2.0,
                        )
                seen.add(kind)
            if setback_union:
                figure.add(
                    setback_union.transform(4326, clone=True),
                    label=_("Setback strips"),
                    zorder=3,
                    linewidth=0.6,
                    **STYLE["setback"],
                )
            for category, shape in drawn_lines:
                for line in _lines(shape):
                    figure.add_line(
                        line, color=LINE_COLOURS.get(category, "#555555"), linewidth=1.2
                    )
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Setback rules as set in the admin; features © OpenStreetMap contributors "
                    "(ODbL), data of %(date)s, and official layers where uploaded."
                )
                % {"date": osm.data_timestamp[:10]}
            )

        charts = {}
        if constraints:
            charts["constraints"] = {"table": self.per_language(lambda: self._table(results))}
        else:
            charts["constraints"] = {
                "reason": self.per_language(
                    lambda: (
                        _("No regulatory constraint was found within %(d)s m of the parcel.")
                        % {"d": fmt(t.constraint_near_m)}
                    )
                )
            }
        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "setback_rules": rules,
                "setback_red_pct": t.setback_red_pct,
                "constraint_near_m": t.constraint_near_m,
            },
            datasets={"osm-roads-services": osm.data_timestamp, "reference-layers": "admin"},
            maps={"constraints": self.render_maps(draw)},
            charts=charts,
            layers=self._layers(constraints, strips, areas, drawn_lines),
        )

    @staticmethod
    def _layers(constraints, strips, areas, drawn_lines):
        setbacks = [c for c in constraints if c["type"] == "setback"]
        layers = [
            vector_layer(
                "setbacks",
                lambda: _("Setback strips"),
                [(strip, {"rule": c["label"]}) for strip, c in zip(strips, setbacks, strict=True)],
                kind="fill",
                color=STYLE["setback"]["facecolor"],
                outline=STYLE["setback"]["edgecolor"],
                opacity=0.45,
                hover=[("rule", lambda: _("Constraint"))],
            )
        ]
        for kind in ("protected", "dup", "infrastructure", "risk_zone"):
            found = [
                (shape, {"name": name or "–", "source": source or "–"})
                for k, name, source, shape in areas
                if k == kind
            ]
            if found:
                layers.append(
                    vector_layer(
                        kind,
                        lambda kind=kind: _kind_labels()[kind],
                        found,
                        kind="fill",
                        color=STYLE[kind]["facecolor"],
                        outline=STYLE[kind]["edgecolor"],
                        opacity=0.45,
                        hover=[("name", lambda: _("Name")), ("source", lambda: _("Source"))],
                    )
                )
        lines = [(shape, {}) for _category, shape in drawn_lines]
        if lines:
            layers.append(
                vector_layer(
                    "constraint-features",
                    lambda: _("Rivers, roads and lines with setbacks"),
                    lines,
                    kind="line",
                    color="#555555",
                    width=1.5,
                )
            )
        return layers

    @staticmethod
    def _areas(osm, bounds):
        """(kind, name, source, geometry) for protected areas, DUP zones, corridors and risk
        zones: OSM protected areas plus the admin-maintained reference layers."""
        box = Polygon.from_bbox(bounds)
        box.srid = 4326
        found = [
            ("protected", f.name or f.kind, "OpenStreetMap", f.geom)
            for f in in_box(osm, Category.PROTECTED, *bounds)
        ]
        layers = ReferenceLayer.objects.filter(is_active=True, geometry__bboverlaps=box)
        for layer in layers:
            shape = layer.geometry
            buffer_m = layer.properties.get("buffer_m") or 0
            if not buffer_m and layer.properties.get("width_m"):
                buffer_m = float(layer.properties["width_m"]) / 2
            if buffer_m:
                srid = utm_srid_for(shape.centroid)
                shape = shape.transform(srid, clone=True).buffer(float(buffer_m))
                shape = shape.transform(4326, clone=True)
            found.append((AREA_KINDS[layer.kind], layer.name, layer.source, shape))
        return found

    @staticmethod
    def _rate(r, t):
        items = r["constraints"]
        if r["setback_overlap_pct"] >= t.setback_red_pct or any(
            c["type"] in {"protected", "dup"} and c["overlap_m2"] for c in items
        ):
            return Rating.RED
        if items:
            return Rating.AMBER
        return Rating.GREEN

    @staticmethod
    def _describe(c):
        if c["type"] == "setback":
            text = _("%(rule)s covers %(m2)s m² (%(pct)s %%) of the parcel") % {
                "rule": _in_language(c["label"]),
                "m2": fmt(c["overlap_m2"]),
                "pct": fmt(c["overlap_pct"]),
            }
            return text if c["confirmed"] else f"{text}*"
        what = {
            "protected": _("the protected area"),
            "dup": _("the public-utility (DUP) zone"),
            "infrastructure": _("the infrastructure corridor"),
            "risk_zone": _("the risk zone"),
        }[c["type"]]
        name = f" « {c['name']} »" if c["name"] else ""
        if c["overlap_m2"]:
            return _("%(what)s%(name)s covers %(pct)s %% of the parcel") % {
                "what": what,
                "name": name,
                "pct": fmt(c["overlap_pct"]),
            }
        return _("%(what)s%(name)s is %(d)s m away") % {
            "what": what,
            "name": name,
            "d": fmt(c["distance_m"]),
        }

    def _table(self, r):
        rows = []
        for c in r["constraints"]:
            if c["type"] == "setback":
                label = _in_language(c["label"]) + ("" if c["confirmed"] else "*")
                basis = _in_language(c["basis"])
            else:
                label = str(_kind_labels()[c["type"]])
                label += f" « {c['name']} »" if c["name"] else ""
                basis = c.get("source") or ""
            rows.append(
                [
                    label,
                    f"{fmt(c['overlap_m2'])} m² ({fmt(c['overlap_pct'])} %)"
                    if c["overlap_m2"]
                    else "–",
                    "–" if c["overlap_m2"] else f"{fmt(c['distance_m'])} m",
                    basis,
                ]
            )
        return {
            "caption": _("Constraints on or near the parcel"),
            "columns": [_("Constraint"), _("On the parcel"), _("Distance"), _("Basis or source")],
            "rows": rows,
        }

    def finding_values(self, results):
        items = [self._describe(c) for c in results["constraints"]]
        unconfirmed = any(
            c["type"] == "setback" and not c["confirmed"] for c in results["constraints"]
        )
        note = (
            _("* Indicative width, to be confirmed by a lawyer or the planning office.")
            if unconfirmed
            else ""
        )
        return {
            "items": _("; ").join(items),
            "note": note,
            "buildable": fmt(results["buildable_pct"]),
        }

    def key_figure(self, results):
        count = len(results["constraints"])
        if not count:
            return _("No constraint found")
        if results["setback_overlap_pct"]:
            return _("%(n)s constraint(s) · %(pct)s %% in setbacks") % {
                "n": count,
                "pct": fmt(results["setback_overlap_pct"]),
            }
        return _("%(n)s constraint(s) nearby") % {"n": count}


def _kind_labels():
    return {
        "protected": _("Protected area"),
        "dup": _("Public-utility (DUP) zone"),
        "infrastructure": _("Infrastructure corridor"),
        "risk_zone": _("Risk zone"),
    }


def _lines(geom):
    if geom.geom_type in {"MultiLineString", "GeometryCollection"}:
        return [g for g in geom if g.geom_type == "LineString"]
    if geom.geom_type == "LineString":
        return [geom]
    return []
