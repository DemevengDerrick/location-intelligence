"""Access and services (TRD §4): road access, and the time to reach the nearest paved road,
school, health facility, market and water point on foot and by car.

Roads and services come from the local OpenStreetMap copy (apps.osm); times from the
self-hosted Valhalla router. Routes start where Valhalla joins the road network nearest the
parcel centre; the walk from the parcel to that road is added to every time.
"""

import math

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.osm.models import Category
from apps.osm.queries import in_box, nearest

from .. import style
from ..charts import spec
from ..config import thresholds
from ..formatting import fmt
from ..maps import ParcelMap
from ..models import Rating
from ..providers import osm_provider, routing_provider
from .base import Module, ModuleOutput
from .imagery import radius_bounds

WALK_M_PER_S = 1.25  # 4.5 km/h, for the walk from the parcel to the nearest road
MINUTES = [5, 10, 15]
CANDIDATES = 5  # nearest services (straight line) routed to; the quickest is kept
SERVICES = [Category.SCHOOL, Category.HEALTH, Category.MARKET, Category.WATER_POINT]
MAIN_ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary"}
WALK_MAP_RADIUS_M = 1_400  # a 15-minute walk is about 1.1 km
DRIVE_MAP_RADIUS_M = (2_000, 10_000)  # fitted to the 15-minute drive area, within these bounds


def destination_labels():
    return {
        "paved_road": _("Paved road"),
        Category.SCHOOL: _("School"),
        Category.HEALTH: _("Health facility"),
        Category.MARKET: _("Market"),
        Category.WATER_POINT: _("Water point"),
    }


def _min(value):
    """Minutes for display: "<1" rather than "0"."""
    return "<1" if value < 1 else fmt(value, 0)


def _minutes(seconds):
    return None if seconds is None else round(seconds / 60, 1)


class AccessModule(Module):
    name = "access"
    title = gettext_lazy("Access and services")

    def run(self, parcel):
        t = thresholds()
        osm = osm_provider()
        if osm is None:
            raise RuntimeError("No OpenStreetMap import is loaded (manage.py load_osm)")
        geom = parcel.geometry
        centre = geom.centroid
        origin = (centre.x, centre.y)
        router = routing_provider()

        road = next(iter(nearest(osm, Category.ROAD, geom, t.road_red_m * 4, limit=1)), None)
        approach_s = road.distance_m / WALK_M_PER_S if road else 0.0
        paved = nearest(osm, Category.ROAD, geom, t.service_search_m, limit=1, paved=True)

        destinations = {"paved_road": paved}
        for category in SERVICES:
            destinations[category] = nearest(
                osm, category, geom, t.service_search_m, limit=CANDIDATES
            )
        services = {}
        for key, candidates in destinations.items():
            services[str(key)] = self._quickest(router, origin, candidates, approach_s)

        isochrones = {mode: router.isochrones(origin, mode, MINUTES) for mode in ("walk", "drive")}
        results = {
            "touches_road": bool(road and road.distance_m <= t.road_touch_m),
            "nearest_road_m": None if road is None else round(road.distance_m),
            "nearest_road_kind": None if road is None else road.kind,
            "nearest_road_name": None if road is None else road.name,
            "services": services,
            "isochrone_km2": {
                mode: {
                    str(m): round(
                        area.transform(3857, clone=True).area
                        / 1e6
                        * math.cos(math.radians(centre.y)) ** 2,
                        2,
                    )
                    for m, area in areas.items()
                }
                for mode, areas in isochrones.items()
            },
        }
        rating = self._rate(results, t)

        def draw(mode):
            if mode == "walk":
                radius = WALK_MAP_RADIUS_M
            else:
                radius = self._fit_radius(isochrones["drive"], origin)
            figure = ParcelMap(geom, extent=radius)
            for minutes in sorted(isochrones[mode], reverse=True):
                label = (
                    _("Within %(m)s min on foot")
                    if mode == "walk"
                    else _("Within %(m)s min by car")
                ) % {"m": minutes}
                figure.add(
                    isochrones[mode][minutes],
                    label=label,
                    facecolor=style.ISOCHRONE_COLOURS.get(minutes, "#D9F0D3"),
                    edgecolor="#1B7837",
                    linewidth=0.5,
                    alpha=0.85,
                    zorder=1,
                )
            bounds = radius_bounds(centre, radius)
            roads = in_box(osm, Category.ROAD, *bounds)
            first = True
            for feature in roads:
                if mode == "drive" and feature.kind not in MAIN_ROADS:
                    continue
                for line in _lines(feature.geom):
                    figure.add_line(
                        line,
                        label=_("Roads") if first else None,
                        color="#555555",
                        linewidth=1.0 if feature.kind in MAIN_ROADS else 0.5,
                    )
                    first = False
            labels = destination_labels()
            for category in SERVICES:
                colour, marker = style.SERVICE_STYLE[str(category)]
                points = [(f.geom.x, f.geom.y) for f in in_box(osm, category, *bounds)]
                figure.add_points(points, labels[category], colour, marker)
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Roads and services © OpenStreetMap contributors (ODbL), data of %(date)s. "
                    "Travel areas computed with Valhalla."
                )
                % {"date": osm.data_timestamp[:10]}
            )

        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "road_touch_m": t.road_touch_m,
                "road_red_m": t.road_red_m,
                "paved_road_amber_m": t.paved_road_amber_m,
                "health_drive_amber_min": t.health_drive_amber_min,
                "school_walk_amber_min": t.school_walk_amber_min,
                "service_search_m": t.service_search_m,
                "walk_speed_to_road_m_s": WALK_M_PER_S,
            },
            datasets={"osm-roads-services": osm.data_timestamp},
            maps={
                "walk": self.render_maps(lambda: draw("walk")),
                "drive": self.render_maps(lambda: draw("drive")),
            },
            charts={
                "times": self.per_language(lambda: self._times_chart(results, osm)),
                "services": {"table": self.per_language(lambda: self._table(results))},
            },
        )

    @staticmethod
    def _quickest(router, origin, candidates, approach_s):
        """The candidate reached fastest by car (on foot if no car route), with both times."""
        if not candidates:
            return None
        targets = [(c.lon, c.lat) for c in candidates]
        walk = router.times(origin, targets, "walk")
        drive = router.times(origin, targets, "drive")

        def total(leg):
            return None if leg.seconds is None else leg.seconds + approach_s

        def best(legs):
            times = [total(leg) for leg in legs]
            reachable = [x for x in times if x is not None]
            return min(reachable) if reachable else None

        order = sorted(
            range(len(candidates)),
            key=lambda i: (total(drive[i]) is None, total(drive[i]) or 0, candidates[i].distance_m),
        )
        chosen = candidates[order[0]]
        return {
            "name": chosen.name,
            "kind": chosen.kind,
            "distance_m": round(chosen.distance_m),
            "walk_min": _minutes(best(walk)),
            "drive_min": _minutes(best(drive)),
            "lon": round(chosen.lon, 6),
            "lat": round(chosen.lat, 6),
        }

    @staticmethod
    def _fit_radius(areas, origin):
        lo, hi = DRIVE_MAP_RADIUS_M
        if not areas:
            return lo
        west, south, east, north = areas[max(areas)].extent
        lat = origin[1]
        dx = (
            max(abs(east - origin[0]), abs(origin[0] - west))
            * 111_320
            * math.cos(math.radians(lat))
        )
        dy = max(abs(north - lat), abs(lat - south)) * 110_574
        return min(max(max(dx, dy) * 1.05, lo), hi)

    @staticmethod
    def _rate(r, t):
        services = r["services"]
        if r["nearest_road_m"] is None or r["nearest_road_m"] > t.road_red_m:
            return Rating.RED
        paved = services.get("paved_road")
        health = services.get(str(Category.HEALTH))
        school = services.get(str(Category.SCHOOL))
        if (
            not r["touches_road"]
            or paved is None
            or paved["distance_m"] > t.paved_road_amber_m
            or health is None
            or health["drive_min"] is None
            or health["drive_min"] > t.health_drive_amber_min
            or school is None
            or school["walk_min"] is None
            or school["walk_min"] > t.school_walk_amber_min
        ):
            return Rating.AMBER
        return Rating.GREEN

    def _times_chart(self, r, osm):
        labels = destination_labels()
        modes = {"walk": _("On foot"), "drive": _("By car")}
        rows = []
        for key, label in labels.items():
            service = r["services"].get(str(key))
            for mode, mode_label in modes.items():
                value = None if service is None else service[f"{mode}_min"]
                if value is not None:
                    rows.append({"to": str(label), "mode": mode_label, "minutes": value})
        health = r["services"].get(str(Category.HEALTH))
        if health and health["drive_min"] is not None:
            title = _("The nearest health facility is %(m)s min away by car") % {
                "m": _min(health["drive_min"])
            }
        else:
            title = _("No health facility found within %(km)s km") % {
                "km": fmt(thresholds().service_search_m / 1000, 0)
            }
        return spec(
            title=title,
            source=_(
                "Valhalla routes on OpenStreetMap (data of %(date)s), including the walk "
                "to the nearest road."
            )
            % {"date": osm.data_timestamp[:10]},
            height=180,
            data={"values": rows},
            mark={"type": "bar"},
            encoding={
                "y": {
                    "field": "to",
                    "type": "nominal",
                    "title": None,
                    "sort": [str(v) for v in labels.values()],
                },
                "yOffset": {"field": "mode"},
                "x": {"field": "minutes", "type": "quantitative", "title": _("Minutes")},
                "color": {
                    "field": "mode",
                    "type": "nominal",
                    "title": None,
                    "scale": {
                        "domain": list(modes.values()),
                        "range": [style.SERIES["walk"], style.SERIES["drive"]],
                    },
                },
            },
        )

    @staticmethod
    def _table(r):
        labels = destination_labels()
        rows = []
        for key, label in labels.items():
            service = r["services"].get(str(key))
            if service is None:
                rows.append([str(label), _("None found nearby"), "–", "–", "–"])
                continue
            rows.append(
                [
                    str(label),
                    service["name"] or _("(no name)"),
                    f"{fmt(service['distance_m'])} m",
                    "–" if service["walk_min"] is None else f"{_min(service['walk_min'])} min",
                    "–" if service["drive_min"] is None else f"{_min(service['drive_min'])} min",
                ]
            )
        return {
            "caption": _("Nearest services"),
            "columns": [_("Destination"), _("Name"), _("Distance"), _("On foot"), _("By car")],
            "rows": rows,
        }

    def finding_values(self, results):
        t = thresholds()
        services = results["services"]
        near = results["nearest_road_m"]
        if near is None:
            road = _("no road is mapped within %(d)s m") % {"d": fmt(t.road_red_m * 4)}
        elif results["touches_road"]:
            road = _("it touches a road")
        else:
            road = _("the nearest road is %(d)s m from the boundary") % {"d": fmt(near)}

        reasons = []
        if near is not None and not results["touches_road"]:
            reasons.append(road)
        if near is None or near > t.road_red_m:
            reasons = [road]
        paved = services.get("paved_road")
        if paved is None:
            reasons.append(
                _("no paved road within %(km)s km") % {"km": fmt(t.service_search_m / 1000, 0)}
            )
        elif paved["distance_m"] > t.paved_road_amber_m:
            reasons.append(
                _("the nearest paved road is %(d)s m away") % {"d": fmt(paved["distance_m"])}
            )
        health = services.get(str(Category.HEALTH))
        if health is None or health["drive_min"] is None:
            reasons.append(_("no health facility could be reached"))
        elif health["drive_min"] > t.health_drive_amber_min:
            reasons.append(
                _("the nearest health facility is %(m)s min away by car")
                % {"m": _min(health["drive_min"])}
            )
        school = services.get(str(Category.SCHOOL))
        if school is None or school["walk_min"] is None:
            reasons.append(_("no school could be reached on foot"))
        elif school["walk_min"] > t.school_walk_amber_min:
            reasons.append(
                _("the nearest school is %(m)s min away on foot") % {"m": _min(school["walk_min"])}
            )

        parts = []
        labels = destination_labels()
        for key in (Category.SCHOOL, Category.HEALTH, Category.MARKET, Category.WATER_POINT):
            service = services.get(str(key))
            if service and service["walk_min"] is not None and service["drive_min"] is not None:
                parts.append(
                    _("%(what)s %(walk)s min on foot or %(drive)s min by car")
                    % {
                        "what": str(labels[key]).lower(),
                        "walk": _min(service["walk_min"]),
                        "drive": _min(service["drive_min"]),
                    }
                )
        times = (
            _("Nearest services: %(list)s.") % {"list": _("; ").join(parts)}
            if parts
            else _("No services were found within reach.")
        )
        return {"road": road, "reasons": _("; ").join(dict.fromkeys(reasons)), "times": times}

    def key_figure(self, results):
        if results["nearest_road_m"] is None:
            return _("No road nearby")
        road = (
            _("On a road")
            if results["touches_road"]
            else _("Road %(d)s m away") % {"d": fmt(results["nearest_road_m"])}
        )
        health = results["services"].get(str(Category.HEALTH))
        if health and health["drive_min"] is not None:
            return _("%(road)s · clinic %(m)s min by car") % {
                "road": road,
                "m": _min(health["drive_min"]),
            }
        return road


def _lines(geom):
    return list(geom) if geom.geom_type == "MultiLineString" else [geom]
