"""Area signals: reported land issues near the parcel (TRD §5.4, FR-32..FR-34).

The news search widens from the parcel's quartier up to its region (apps.incidents.
area_search), reusing saved searches for the same places. The report lists only incidents an
analyst approved: point and quartier incidents within the radius, and area incidents
(commune, department, region) for the places searched. It is not a rating: the tile is
"for information", since these are area-level public reports, not findings about the parcel.
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core import llm
from apps.incidents import area_search
from apps.incidents.config import signals_settings
from apps.incidents.models import Incident, IncidentType, LocationPrecision, ReviewStatus
from apps.parcels.geometry import utm_srid_for

from .. import charts
from ..formatting import fmt
from ..layers import vector_layer
from ..maps import ParcelMap
from ..models import Rating
from .base import Module, ModuleOutput

NEARBY = "nearby"
LEVEL_ORDER = [NEARBY, "commune", "department", "region"]
PLACE_TYPE_LEVEL = {
    "quartier": NEARBY,
    "village": NEARBY,
    "lieu_dit": NEARBY,
    "commune": "commune",
    "arrondissement": "commune",
    "department": "department",
    "region": "region",
}
TYPE_COLOURS = {
    "title_cancellation": "#0072B2",
    "expropriation": "#D55E00",
    "demolition": "#E69F00",
    "double_sale": "#CC79A7",
    "boundary_dispute": "#009E73",
    "customary_conflict": "#56B4E9",
    "public_land": "#F0E442",
    "other": "#999999",
}


def level_labels():
    return {
        NEARBY: _("Nearby"),
        "commune": _("In the commune"),
        "department": _("In the department"),
        "region": _("In the region"),
    }


def precision_labels():
    return dict(LocationPrecision.choices)


def type_label(key):
    return str(dict(IncidentType.choices).get(key, key))


def statement():
    """FR-34: always shown with the section, in the reader's language."""
    return _(
        "These are public reports about the area, not findings about this parcel or its "
        "owners. Finding no report does not mean that the area is free of land disputes."
    )


class SignalsModule(Module):
    name = "signals"
    title = gettext_lazy("Land issues reported nearby")

    def run(self, parcel):
        settings = signals_settings()
        geom = parcel.geometry
        centre = geom.centroid
        levels = area_search.widen(centre, settings)
        searched_ids = {level["place"].pk: level for level in levels}
        reached = {PLACE_TYPE_LEVEL[level["place"].place_type] for level in levels}
        srid = utm_srid_for(centre)
        parcel_m = geom.transform(srid, clone=True)
        since = date.today() - timedelta(days=365 * settings.years)

        incidents = []
        approved = (
            Incident.objects.filter(review_status=ReviewStatus.APPROVED, geometry__isnull=False)
            .exclude(event_date__lt=since)
            .select_related("place")
            .prefetch_related("sources")
        )
        # everything that can qualify lies in the widest place searched (or near the parcel)
        widest = levels[-1]["place"].geometry if levels else geom.buffer(0.05)
        for incident in approved.filter(geometry__intersects=widest.union(geom.buffer(0.05))):
            entry = self._entry(incident, parcel_m, srid, settings, searched_ids, reached)
            if entry:
                incidents.append(entry)
        # FR-33: official acts first, then newest first
        incidents.sort(key=lambda e: (not e["official"], -(e["date_ordinal"] or 0)))

        item_ids = set().union(*(lv["item_ids"] for lv in levels)) if levels else set()
        pending = (
            Incident.objects.filter(review_status=ReviewStatus.UNREVIEWED, sources__pk__in=item_ids)
            .distinct()
            .count()
        )
        unextracted = sorted(self._unextracted(item_ids))
        if unextracted and llm.available():
            from apps.incidents.tasks import extract_items

            transaction.on_commit(lambda: extract_items.delay(unextracted))

        results = {
            "incidents": incidents,
            "count": len(incidents),
            "official_count": sum(e["official"] for e in incidents),
            "nearby_count": sum(e["level"] == NEARBY for e in incidents),
            "radius_km": settings.radius_km,
            "years": settings.years,
            "levels": [
                {
                    "place": lv["place"].name,
                    "type": lv["place"].place_type,
                    "items": len(lv["item_ids"]),
                    "reused": lv["reused"],
                    "searched_at": max(
                        (s.searched_at.isoformat() for s in lv["searches"] if s.searched_at),
                        default="",
                    ),
                }
                for lv in levels
            ],
            "items_found": len(item_ids),
            "pending_review": pending,
            "awaiting_extraction": len(unextracted),
        }
        searched_on = max((lv["searched_at"][:10] for lv in results["levels"]), default="")

        def draw():
            figure = ParcelMap(geom, extent="area")
            ring = parcel_m.buffer(settings.radius_km * 1000).transform(4326, clone=True)
            figure.add(
                ring,
                label=_("%(km)s km search radius") % {"km": fmt(settings.radius_km)},
                facecolor="none",
                edgecolor="#555555",
                linestyle="--",
                linewidth=1,
            )
            nearby = [e for e in incidents if e["level"] == NEARBY]
            for kind, colour in TYPE_COLOURS.items():
                points = [tuple(e["point"]) for e in nearby if e["type"] == kind]
                if points:
                    figure.add_points(points, type_label(kind), colour, marker="D", size=44)
            figure.add_parcel(geom, _("Parcel boundary"))
            if settings.gdelt_enabled:
                source = _(
                    "Approved incidents from public news reports (GDELT and Cameroonian "
                    "outlets), searched on %(date)s."
                )
            else:
                source = _(
                    "Approved incidents from public news reports (Cameroonian outlets), "
                    "searched on %(date)s."
                )
            return figure.to_svg(source % {"date": searched_on or "–"})

        charts_ = {"incidents": self._table_or_reason(results)}
        if incidents:
            charts_["timeline"] = self.per_language(lambda: self._timeline(results, searched_on))
        return ModuleOutput(
            rating=Rating.INFO,
            results=results,
            parameters={
                "radius_km": settings.radius_km,
                "years": settings.years,
                "max_age_days": settings.max_age_days,
                "min_items": settings.min_items,
            },
            datasets={"news-outlets": searched_on}
            | ({"gdelt": searched_on} if settings.gdelt_enabled else {}),
            maps={"incidents": self.render_maps(draw)},
            charts=charts_,
            layers=self._layers(incidents, ring_m=parcel_m.buffer(settings.radius_km * 1000)),
        )

    @staticmethod
    def _unextracted(item_ids):
        from apps.incidents.models import SourceItem

        return set(
            SourceItem.objects.filter(pk__in=item_ids, extracted_at__isnull=True).values_list(
                "pk", flat=True
            )
        )

    @staticmethod
    def _entry(incident, parcel_m, srid, settings, searched_ids, reached):
        shape_m = incident.geometry.transform(srid, clone=True)
        if incident.precision in (LocationPrecision.POINT, LocationPrecision.QUARTIER):
            distance = parcel_m.distance(shape_m)
            if distance > settings.radius_km * 1000:
                return None
            level, distance_m = NEARBY, round(distance)
        else:
            level = incident.precision
            if level not in reached:
                return None
            if incident.place_id not in searched_ids and not shape_m.intersects(parcel_m):
                return None
            distance_m = None
        point = incident.geometry.point_on_surface
        return {
            "id": incident.pk,
            "type": incident.incident_type,
            "date": incident.event_date.isoformat() if incident.event_date else "",
            "date_ordinal": incident.event_date.toordinal() if incident.event_date else None,
            "precision": incident.precision,
            "level": level,
            "place": incident.place.name if incident.place else ", ".join(incident.place_names[:2]),
            "distance_m": distance_m,
            "official": incident.is_official_act,
            "summary": {"fr": incident.summary_fr or "", "en": incident.summary_en or ""},
            "sources": [{"url": s.url, "outlet": s.outlet} for s in incident.sources.all()],
            "point": [round(point.x, 6), round(point.y, 6)],
        }

    def _table_or_reason(self, results):
        if results["incidents"]:
            return {"table": self.per_language(lambda: self._table(results))}
        return {"reason": self.per_language(lambda: self._none_found(results))}

    def _table(self, results):
        from django.utils import translation

        language = translation.get_language() or "fr"
        precisions = precision_labels()
        rows = []
        for e in results["incidents"]:
            where = e["place"] or "–"
            if e["distance_m"] is not None:
                where = _("%(place)s, %(d)s m away") % {"place": where, "d": fmt(e["distance_m"])}
            what = type_label(e["type"])
            if e["official"]:
                what = _("Official act: %(type)s") % {"type": what}
            rows.append(
                [
                    e["date"] or "–",
                    what,
                    f"{where} ({precisions.get(e['precision'], e['precision'])})",
                    e["summary"].get(language) or e["summary"].get("fr", ""),
                    [{"text": s["outlet"] or s["url"], "href": s["url"]} for s in e["sources"]]
                    or "–",
                ]
            )
        return {
            "caption": _("Reported land issues, official acts first, newest first"),
            "columns": [_("Date"), _("Type"), _("Where"), _("Summary"), _("Source")],
            "rows": rows,
        }

    def _none_found(self, results):
        place = results["levels"][-1]["place"] if results["levels"] else ""
        return _(
            "No approved report of a land issue was found within %(km)s km of the parcel or "
            "in %(place)s over the last %(years)s years."
        ) % {"km": fmt(results["radius_km"]), "place": place or "–", "years": results["years"]}

    def _timeline(self, results, searched_on):
        labels = level_labels()
        end = date.fromisoformat(searched_on) if searched_on else date.today()
        values = [
            {
                "date": e["date"],
                "type": type_label(e["type"]),
                "where": str(labels[e["level"]]),
                "place": e["place"],
            }
            for e in results["incidents"]
            if e["date"]
        ]
        return charts.spec(
            title=_("%(n)s reported land issue(s) in the area, by year and type")
            % {"n": results["count"]},
            source=_("Approved incidents from public news reports, searched on %(date)s")
            % {"date": searched_on or "–"},
            height=max(80, 26 * len({v["type"] for v in values})),
            data={"values": values},
            mark={"type": "point", "filled": True, "size": 90},
            encoding={
                "x": {  # the whole look-back window, in years, even for a single incident
                    "field": "date",
                    "type": "temporal",
                    "title": _("Date of the event"),
                    "scale": {"domain": [f"{end.year - results['years']}-01-01", end.isoformat()]},
                    "axis": {"format": "%Y", "tickCount": "year"},
                },
                "y": {
                    "field": "type",
                    "type": "nominal",
                    "title": None,
                    "axis": {"labelLimit": 300},  # French type names are long
                },
                "color": {
                    "field": "where",
                    "type": "nominal",
                    "title": _("Where"),
                    "scale": {
                        "domain": [str(labels[k]) for k in LEVEL_ORDER],
                        "range": ["#D55E00", "#E69F00", "#0072B2", "#999999"],
                    },
                },
                "shape": {"field": "where", "type": "nominal", "legend": None},
                "tooltip": [
                    {"field": "date", "type": "temporal", "title": _("Date")},
                    {"field": "type", "title": _("Type")},
                    {"field": "place", "title": _("Place")},
                ],
            },
        )

    @staticmethod
    def _layers(incidents, ring_m):
        nearby = [
            (
                _point(e["point"]),
                {
                    "type": type_label(e["type"]),
                    "date": e["date"] or "–",
                    "place": e["place"],
                    "color": TYPE_COLOURS.get(e["type"], "#999999"),
                },
            )
            for e in incidents
            if e["level"] == NEARBY
        ]
        layers = [
            vector_layer(
                "search-radius",
                lambda: _("Search radius"),
                [(ring_m.transform(4326, clone=True), {})],
                kind="line",
                color="#555555",
                width=1.2,
                dash=True,
            )
        ]
        if nearby:
            layers.append(
                vector_layer(
                    "incidents",
                    lambda: _("Reported land issues"),
                    nearby,
                    kind="circle",
                    color="#D55E00",
                    hover=[
                        ("type", lambda: _("Type")),
                        ("date", lambda: _("Date")),
                        ("place", lambda: _("Place")),
                    ],
                )
            )
        return layers

    def finding_values(self, results):
        labels = level_labels()
        if not results["count"]:
            summary = self._none_found(results)
        else:
            by_level = {}
            for e in results["incidents"]:
                by_level[e["level"]] = by_level.get(e["level"], 0) + 1
            parts = [
                f"{n} {str(labels[level]).lower()}"
                for level in LEVEL_ORDER
                if (n := by_level.get(level))
            ]
            summary = _(
                "%(n)s reported land issue(s) found in public news over the last %(years)s "
                "years: %(parts)s."
            ) % {"n": results["count"], "years": results["years"], "parts": ", ".join(parts)}
            if results["official_count"]:
                summary += " " + _("%(n)s of them involve an official act (listed first).") % {
                    "n": results["official_count"]
                }
        return {"summary": summary, "statement": statement()}

    def key_figure(self, results):
        if not results["count"]:
            return _("No report found")
        return _("%(n)s report(s) in the area") % {"n": results["count"]}


def _point(coords):
    from django.contrib.gis.geos import Point

    return Point(coords[0], coords[1], srid=4326)
