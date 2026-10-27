import json
import math
from datetime import date

import numpy as np
import pytest
from django.contrib.gis.geos import Point, Polygon
from django.core import mail
from django.urls import reverse
from django.utils import timezone, translation
from rasterio.transform import from_origin

from apps.analysis import providers
from apps.analysis.models import AnalysisRun, ModuleResult, ModuleStatus, RunStatus
from apps.orders.models import OrderStatus
from apps.orders.testing import make_order
from apps.parcels.testing import DOUALA, square_m
from apps.payments.models import Payment
from apps.reports.models import Report

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("cameroon"),
    pytest.mark.run_analysis,
]

RES = 0.0003  # ≈ 33 m cells, like Copernicus GLO-30


@pytest.fixture(autouse=True)
def english():
    """Pages and URLs in English, whatever an earlier test left active."""
    with translation.override("en"):
        yield


class FakeDEM:
    """A tilted plane rising eastwards at `slope_deg`."""

    def __init__(self, slope_deg):
        self.slope_deg = slope_deg

    def read(self, west, south, east, north):
        cols, rows = math.ceil((east - west) / RES), math.ceil((north - south) / RES)
        metres_east = np.arange(cols) * RES * 111_320 * math.cos(math.radians(DOUALA[1]))
        heights = np.tile(20 + metres_east * math.tan(math.radians(self.slope_deg)), (rows, 1))
        return providers.Elevation(
            heights.astype("float32"),
            from_origin(west, north, RES, RES),
            "copernicus-dem-glo30",
            "test",
        )


class FakeBuildings:
    def __init__(self, footprints):
        self.footprints = footprints

    def fetch(self, west, south, east, north):
        return providers.Buildings(
            self.footprints, "google-open-buildings", "v3", [0.9] * len(self.footprints)
        )


VEGETATION = {"blue": 0.03, "green": 0.05, "red": 0.03, "nir": 0.40, "swir16": 0.15}
BUILT_UP = {"blue": 0.13, "green": 0.14, "red": 0.15, "nir": 0.18, "swir16": 0.25}


class FakeImagery:
    """Synthetic Sentinel-2 composites: vegetation everywhere; inside the parcel, built-up from
    `built_from` (dry-season year) onwards, and in the current composite if `built_now`."""

    def __init__(self, built_from=None, built_now=False, cloudy=False):
        self.built_from, self.built_now, self.cloudy = built_from, built_now, cloudy

    def composite(self, west, south, east, north, start, end):
        from apps.analysis.providers import Composite, _utm_grid

        transform, width, height = _utm_grid(west, south, east, north, 32632, 10)
        # The test parcel is a north-aligned square: mark its UTM bounding box as "inside"
        # (no rasterising here: this runs in worker threads).
        x0, y0, x1, y1 = square_m(*DOUALA, 40).transform(32632, clone=True).extent
        left = transform.c + np.arange(width) * 10
        top = transform.f - np.arange(height) * 10
        # pixels the parcel touches, like the module's all_touched mask
        inside = np.outer((top > y0) & (top - 10 < y1), (left + 10 > x0) & (left < x1))
        current = (end - start).days > 200
        built = (
            self.built_now
            if current
            else (self.built_from is not None and end.year >= self.built_from)
        )
        bands = {}
        for band in VEGETATION:
            values = np.full((height, width), VEGETATION[band], dtype="float32")
            if built:
                values[inside] = BUILT_UP[band]
            if self.cloudy:
                values[:] = np.nan
            bands[band] = values
        return Composite(bands, transform, 32632, [start.isoformat(), end.isoformat()])


class FakeWater:
    """Surface-water occurrence and flood depth grids (~30 m): dry everywhere except, inside
    the parcel's bounding box, `occurrence` per cent and `flood_m` metres."""

    def __init__(self, occurrence=0, flood_m=0, flood_east_m=0):
        self.occurrence_pct, self.flood_m, self.flood_east_m = occurrence, flood_m, flood_east_m

    gsw_dataset, gsw_version = "jrc-gsw", "test"
    flood_dataset, flood_version = "jrc-flood-hazard", "test"

    def _grid(self, west, south, east, north, value, east_m=0):
        res = RES / 1.2
        cols, rows = math.ceil((east - west) / res), math.ceil((north - south) / res)
        transform = from_origin(west, north, res, res)
        values = np.zeros((rows, cols), dtype="float32")
        x0, y0, x1, y1 = square_m(*DOUALA, 40).extent
        shift = east_m / (111_320 * math.cos(math.radians(DOUALA[1])))
        x0, x1 = x0 + shift, x1 + shift
        lons = west + (np.arange(cols) + 0.5) * res
        lats = north - (np.arange(rows) + 0.5) * res
        values[np.outer((lats > y0) & (lats < y1), (lons > x0) & (lons < x1))] = value
        return providers.Grid(values, transform)

    def occurrence(self, west, south, east, north):
        return self._grid(west, south, east, north, self.occurrence_pct)

    def flood_depth(self, west, south, east, north, return_period=100):
        return self._grid(west, south, east, north, self.flood_m, self.flood_east_m)


class FakeWaterFeatures:
    def __init__(self, lines=(), wetlands=()):
        self.lines, self.wetlands = list(lines), list(wetlands)

    def fetch(self, west, south, east, north):
        return providers.WaterFeatures(self.lines, [], self.wetlands, "osm-water", "test")


def stream(lon_offset_m):
    """A north–south stream `lon_offset_m` metres east (+) or west (-) of the parcel centre."""
    from django.contrib.gis.geos import LineString

    lon = DOUALA[0] + lon_offset_m / (111_320 * math.cos(math.radians(DOUALA[1])))
    return LineString([(lon, DOUALA[1] - 0.01), (lon, DOUALA[1] + 0.01)], srid=4326)


class FakeRouter:
    """Travel times from straight-line distance (x1.3 for the road network); isochrones are
    circles. `reachable=False` simulates a parcel the router cannot connect."""

    SPEED = {"walk": 1.25, "drive": 8.0}

    def __init__(self, reachable=True):
        self.reachable = reachable

    def times(self, origin, targets, mode):
        from apps.analysis.providers import Leg

        legs = []
        for lon, lat in targets:
            dx = (lon - origin[0]) * 111_320 * math.cos(math.radians(origin[1]))
            dy = (lat - origin[1]) * 110_574
            metres = math.hypot(dx, dy) * 1.3
            seconds = metres / self.SPEED[mode] + (60 if mode == "drive" else 0)
            legs.append(Leg(seconds, metres) if self.reachable else Leg(None, None))
        return legs

    def isochrones(self, origin, mode, minutes):
        from django.contrib.gis.geos import Point

        if not self.reachable:
            return {}
        centre = Point(*origin, srid=4326).transform(32632, clone=True)
        return {
            m: centre.buffer(self.SPEED[mode] * m * 60 / 1.3).transform(4326, clone=True)
            for m in minutes
        }


# A young population: share of each raster band (ages 0, 1–4, 5–9 ... 90+), per sex.
AGE_SHARES = [
    0.036,
    0.13,
    0.14,
    0.12,
    0.11,
    0.1,
    0.09,
    0.07,
    0.055,
    0.045,
    0.035,
    0.025,
    0.02,
    0.015,
    0.01,
    0.008,
    0.005,
    0.003,
    0.002,
    0.002,
]


class FakePopulation:
    """Constant density (people/km² in 2020) growing `growth` % a year; fixed age structure."""

    release, dataset = "R2025A", "worldpop-r2025a"
    history_release, history_dataset = "Global1", "worldpop-global1"

    def __init__(self, density=4000, growth=3.0, years=(2020, 2025, 2030), history=()):
        self.density_2020, self.growth, self._years = density, growth, list(years)
        self._history = list(history)
        self.calls = self.history_calls = 0

    def years(self):
        return self._years

    def history_years(self):
        return self._history

    def history_total(self, geom, year):
        """Global1 differs from R2025A (another method); in cities it counts fewer people."""
        from apps.parcels.geometry import utm_srid_for

        self.history_calls += 1
        km2 = geom.transform(utm_srid_for(geom.centroid), clone=True).area / 1e6
        return self._density(year) * km2 * 0.5

    def _density(self, year):
        return self.density_2020 * (1 + self.growth / 100) ** (year - 2020)

    def age_sex(self, geom, year):
        from apps.analysis.population import AgeSex
        from apps.parcels.geometry import utm_srid_for

        self.calls += 1
        km2 = geom.transform(utm_srid_for(geom.centroid), clone=True).area / 1e6
        people = self._density(year) * km2
        total_share = sum(AGE_SHARES)
        half = [people / 2 * share / total_share for share in AGE_SHARES]
        return AgeSex(list(half), list(half))

    def density(self, west, south, east, north, year):
        res = 0.000833
        cols, rows = math.ceil((east - west) / res), math.ceil((north - south) / res)
        values = np.full((rows, cols), self._density(year), dtype="float32")
        return providers.Grid(values, from_origin(west, north, res, res))


class FakeGhslPopulation:
    """GHS-POP: the same density as FakePopulation in 2020, growing `growth` % a year."""

    dataset, version = "ghsl-pop", "R2023A"
    EPOCHS = (2000, 2005, 2010, 2015, 2020, 2025, 2030)
    PROJECTED_FROM = 2025

    def __init__(self, growth=2.5, fail=False):
        self.growth, self.fail, self.calls = growth, fail, 0

    def total(self, geom, epoch):
        from apps.parcels.geometry import utm_srid_for

        if self.fail:
            raise OSError("tiles unreachable")
        self.calls += 1
        km2 = geom.transform(utm_srid_for(geom.centroid), clone=True).area / 1e6
        return 4000 * (1 + self.growth / 100) ** (epoch - 2020) * km2


class FakeGhsl:
    """Built-up land spreading outwards from the parcel, epoch by epoch."""

    dataset, version = "ghsl-built-s", "R2023A"
    EPOCHS = (1975, 1990, 2000, 2010, 2020)

    def built(self, west, south, east, north, epoch):
        res = 0.000833
        cols, rows = math.ceil((east - west) / res), math.ceil((north - south) / res)
        lons = west + (np.arange(cols) + 0.5) * res
        lats = north - (np.arange(rows) + 0.5) * res
        dx = (lons[None, :] - DOUALA[0]) * 111_320
        dy = (lats[:, None] - DOUALA[1]) * 110_574
        reach_m = 400 * (self.EPOCHS.index(epoch) + 1)
        values = np.where(np.hypot(dx, dy) < reach_m, 4000.0, 0.0).astype("float32")
        return providers.Grid(values, from_origin(west, north, res, res))


def osm_around_parcel(**overrides):
    """A road along the parcel's south edge, a paved road 300 m north, one of each service."""
    from apps.osm.models import Category
    from apps.osm.testing import make_import, place, road

    features = {
        "road": road(*DOUALA, -23, name="Rue des Palmiers"),
        "paved": road(*DOUALA, 300, kind="primary", paved=True, name="Boulevard"),
        "school": place(Category.SCHOOL, *DOUALA, 500, 0, name="École Les Lauriers"),
        "health": place(Category.HEALTH, *DOUALA, -1500, 0, name="Centre de santé", kind="clinic"),
        "market": place(Category.MARKET, *DOUALA, 0, -800, name="Marché Bonas"),
        "water": place(Category.WATER_POINT, *DOUALA, 0, 200, kind="water_well"),
    }
    features.update(overrides)
    return make_import([f for f in features.values() if f is not None])


def box(lon, lat, half_deg=0.00005):
    polygon = Polygon.from_bbox((lon - half_deg, lat - half_deg, lon + half_deg, lat + half_deg))
    polygon.srid = 4326
    return polygon


@pytest.fixture
def data(monkeypatch):
    """Default: gentle 2° slope, one building on the parcel, one just outside."""
    state = {
        "dem": FakeDEM(2),
        "imagery": FakeImagery(),
        "buildings": FakeBuildings([box(*DOUALA), box(DOUALA[0] + 0.00030, DOUALA[1])]),
        "water": FakeWater(),
        "water_features": FakeWaterFeatures(),
        "router": FakeRouter(),
        "population": FakePopulation(),
        "ghsl_population": FakeGhslPopulation(),
        "ghsl": FakeGhsl(),
        "osm": None,  # built on first use, so tests can replace it first
        "area_levels": [],  # what the widening news search returns (see signals tests)
    }
    monkeypatch.setattr(providers, "elevation_provider", lambda: state["dem"])
    monkeypatch.setattr(providers, "buildings_provider", lambda: state["buildings"])
    monkeypatch.setattr("apps.analysis.modules.terrain.elevation_provider", lambda: state["dem"])
    monkeypatch.setattr(
        "apps.analysis.modules.buildings.buildings_provider", lambda: state["buildings"]
    )
    monkeypatch.setattr("apps.analysis.modules.imagery.imagery_provider", lambda: state["imagery"])
    monkeypatch.setattr("apps.analysis.modules.change.imagery_provider", lambda: state["imagery"])
    monkeypatch.setattr("apps.analysis.modules.flood.water_provider", lambda: state["water"])
    monkeypatch.setattr(
        "apps.analysis.modules.flood.water_features_provider", lambda: state["water_features"]
    )

    def osm():
        if state["osm"] is None:
            state["osm"] = osm_around_parcel()
        return state["osm"]

    monkeypatch.setattr("apps.analysis.modules.access.osm_provider", osm)
    monkeypatch.setattr("apps.analysis.modules.access.routing_provider", lambda: state["router"])
    monkeypatch.setattr(
        "apps.analysis.modules.demographics.population_provider", lambda: state["population"]
    )
    monkeypatch.setattr("apps.analysis.modules.demographics.ghsl_provider", lambda: state["ghsl"])
    monkeypatch.setattr(
        "apps.analysis.modules.demographics.ghsl_population_provider",
        lambda: state["ghsl_population"],
    )
    monkeypatch.setattr(
        "apps.analysis.modules.signals.area_search.widen",
        lambda point, settings=None, http=None: state["area_levels"],
    )
    return state


@pytest.fixture
def paid_order(client, customer, django_capture_on_commit_callbacks):
    """A 40 m × 40 m parcel in Douala, paid through the demo checkout (runs the pipeline)."""
    customer.language = "en"
    customer.save()
    order = make_order(customer)
    parcel = order.parcels.get()
    parcel.stated_area_m2 = 1700  # 6 % above the computed 1 600 m²
    parcel.save()
    client.force_login(customer)

    def pay():
        client.post(reverse("payments:pay", args=[order.public_id]), {"method": "card"})
        payment = Payment.objects.get(order=order)
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("payments:demo", args=[payment.public_id]), {"decision": "approve"})
        order.refresh_from_db()
        return order

    return pay


def findings(order):
    return {f["module"]: f for f in Report.objects.get(order=order).draft["findings"]}


def test_payment_runs_all_modules_and_sends_the_order_to_review(data, paid_order):
    order = paid_order()

    run = AnalysisRun.objects.get()
    assert run.status == RunStatus.COMPLETED
    assert set(run.module_results.values_list("module", flat=True)) == {
        "location",
        "imagery",
        "buildings",
        "change",
        "flood",
        "terrain",
        "access",
        "demographics",
        "red_flags",
        "signals",
    }
    assert order.status == OrderStatus.IN_REVIEW

    f = findings(order)
    assert f["location"]["rating"] == "green"
    assert "1,600 m²" in f["location"]["text"]["en"] and "Douala V" in f["location"]["text"]["en"]
    assert "1 600 m²" in f["location"]["text"]["fr"].replace(" ", " ").replace("\xa0", " ")
    assert f["terrain"]["rating"] == "green"
    assert f["buildings"]["rating"] == "red"
    assert f["buildings"]["results"]["inside_count"] == 1
    assert f["buildings"]["results"]["near_count"] == 1
    assert set(f["terrain"]["maps"]["main"]) == {"fr", "en"}


@pytest.mark.parametrize("slope, rating", [(2, "green"), (7, "amber"), (20, "red")])
def test_terrain_rating_follows_the_slope_thresholds(data, paid_order, slope, rating):
    data["dem"] = FakeDEM(slope)
    order = paid_order()
    terrain = findings(order)["terrain"]
    assert terrain["rating"] == rating
    assert terrain["results"]["slope_mean_deg"] == pytest.approx(slope, abs=0.3)
    assert terrain["results"]["erosion_flag"] is (slope > 15)


def test_empty_surroundings_rate_buildings_green(data, paid_order):
    data["buildings"] = FakeBuildings([])
    assert findings(paid_order())["buildings"]["rating"] == "green"


def test_a_failing_module_is_unavailable_and_blocks_nothing(data, paid_order):
    class Broken:
        def read(self, *args):
            raise ConnectionError("DEM server unreachable")

    data["dem"] = Broken()
    order = paid_order()

    assert order.status == OrderStatus.IN_REVIEW
    terrain = ModuleResult.objects.get(module="terrain")
    assert terrain.status == ModuleStatus.FAILED
    assert "DEM server unreachable" in terrain.error
    f = findings(order)
    assert f["terrain"]["unavailable"] and f["terrain"]["rating"] == "grey"
    assert "unavailable" in f["terrain"]["text"]["en"]
    assert f["buildings"]["rating"] == "red"  # others still ran


def test_static_maps_have_the_required_furniture(data, paid_order):
    from django.core.files.storage import default_storage

    key = findings(paid_order())["buildings"]["maps"]["main"]["fr"]
    svg = default_storage.open(key).read().decode()
    assert ">N<" in svg  # north arrow
    assert " m<" in svg  # scale bar label, e.g. "20 m"
    assert "Sur la parcelle" in svg  # translated legend
    assert "Google Open Buildings v3" in svg  # source line


# --- Review, approval and the PDF ----------------------------------------------------------


@pytest.fixture
def analyst_client(client, make_user):
    analyst = make_user("analyst@example.com", role="analyst", is_staff=True)
    analyst_client = client.__class__()
    analyst_client.force_login(analyst)
    return analyst_client


def review_url(order):
    return reverse("admin:reports_report_review", args=[Report.objects.get(order=order).pk])


def form_index(order, module):
    """Position of a module's finding in the draft, as the review form numbers its fields."""
    return [f["module"] for f in Report.objects.get(order=order).draft["findings"]].index(module)


def review_form(order, **changes):
    data = {}
    for i, f in enumerate(Report.objects.get(order=order).draft["findings"]):
        data.update(
            {
                f"rating_{i}": f["rating"],
                f"text_fr_{i}": f["text"]["fr"],
                f"text_en_{i}": f["text"]["en"],
            }
        )
    data.update({"note_fr": "", "note_en": ""}, **changes)
    return data


def test_rating_override_needs_a_reason(data, paid_order, analyst_client):
    order = paid_order()
    i = form_index(order, "location")
    response = analyst_client.post(
        review_url(order), review_form(order, **{f"rating_{i}": "red"}, action="save"), follow=True
    )
    assert "Give a reason" in response.content.decode()
    assert findings(order)["location"]["rating"] == "green"

    analyst_client.post(
        review_url(order),
        review_form(
            order,
            **{f"rating_{i}": "amber", f"override_reason_{i}": "Seller's plan disagrees"},
            action="save",
        ),
    )
    location = findings(order)["location"]
    assert (location["rating"], location["computed_rating"]) == ("amber", "green")


def test_review_screen_is_for_analysts_only(data, paid_order, client, make_user):
    order = paid_order()
    staff = make_user("helper@example.com", is_staff=True)
    other = client.__class__()
    other.force_login(staff)
    assert other.get(review_url(order)).status_code == 403


def test_approval_issues_verifiable_pdfs_in_both_languages(
    data, paid_order, analyst_client, client, django_capture_on_commit_callbacks
):
    order = paid_order()
    with django_capture_on_commit_callbacks(execute=True):
        analyst_client.post(
            review_url(order),
            review_form(
                order,
                text_en_2="Edited by the analyst.",
                note_en="Visit before paying.",
                action="approve",
            ),
        )
    order.refresh_from_db()
    assert order.status == OrderStatus.DELIVERED
    report = Report.objects.get(order=order)
    versions = {v.language: v for v in report.versions.all()}
    assert set(versions) == {"fr", "en"} and versions["en"].number == 1
    pdf = versions["en"].pdf.read()
    assert pdf.startswith(b"%PDF")
    assert versions["en"].content["findings"][2]["text"]["en"] == "Edited by the analyst."
    assert "is ready" in mail.outbox[-1].subject  # "Your report for order … is ready"

    # The customer sees the summary and downloads the PDF; nobody else can.
    with translation.override("en"):
        page = client.get(reverse("portal:order", args=[order.public_id])).content.decode()
    assert "Edited by the analyst." in page
    download = reverse("reports:download", args=[order.public_id, 1, "en"])
    assert client.get(download).status_code == 302
    assert analyst_client.get(download).status_code == 404

    # The verification page confirms the genuine file and rejects a modified one.
    verify = reverse("reports:verify", args=[report.reference])
    from django.core.files.uploadedfile import SimpleUploadedFile

    genuine = client.post(verify, {"pdf": SimpleUploadedFile("r.pdf", pdf)}).content.decode()
    altered = client.post(
        verify, {"pdf": SimpleUploadedFile("r.pdf", pdf + b"%tampered")}
    ).content.decode()
    assert "Genuine and unaltered" in genuine
    assert "Not a match" in altered


def test_changes_after_delivery_create_a_new_version(data, paid_order, analyst_client):
    order = paid_order()
    analyst_client.post(review_url(order), review_form(order, action="approve"))
    analyst_client.post(review_url(order), {"action": "reopen"})
    order.refresh_from_db()
    assert order.status == OrderStatus.IN_REVIEW
    analyst_client.post(review_url(order), review_form(order, action="approve"))
    report = Report.objects.get(order=order)
    assert sorted(set(report.versions.values_list("number", flat=True))) == [1, 2]


def test_pin_orders_are_rated_grey_for_area(
    data, client, customer, django_capture_on_commit_callbacks
):
    from apps.parcels.validation import buffer_pin

    customer.language = "en"
    customer.save()
    order = make_order(customer)
    parcel = order.parcels.get()
    parcel.geometry = buffer_pin(square_m(*DOUALA, 1).centroid, 30)
    parcel.is_approximate = True
    parcel.stated_area_m2 = 500
    parcel.save()
    client.force_login(customer)
    client.post(reverse("payments:pay", args=[order.public_id]), {"method": "card"})
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            reverse("payments:demo", args=[Payment.objects.get().public_id]),
            {"decision": "approve"},
        )
    with translation.override("en"):
        location = findings(order)["location"]
    assert location["rating"] == "grey"
    assert Report.objects.get(order=order).draft["approximate"] is True


# --- 3a: charts, key figures and report structure -----------------------------------------


def test_area_and_profile_charts_are_vega_lite_specs_in_both_languages(data, paid_order):
    data["dem"] = FakeDEM(7)
    f = findings(paid_order())

    area = f["location"]["charts"]["area"]
    assert set(area) == {"fr", "en"}
    assert area["en"]["$schema"].startswith("https://vega.github.io/schema/vega-lite/")
    assert area["en"]["title"]["text"] == "The seller's area is 6.3 % larger than the boundary"
    assert area["en"]["title"]["subtitle"]  # every chart names its source

    profile = f["terrain"]["charts"]["profile"]
    assert profile["fr"]["title"]["text"].startswith("L'altitude varie de")
    rows = profile["en"]["layer"][2]["encoding"]
    assert rows["y"]["title"] == "Elevation (m)"
    elevations = [r["elevation"] for r in profile["en"]["data"]["values"]]
    assert elevations == sorted(elevations)  # the fake slope rises eastwards along the axis


def test_key_figures_feed_the_summary_tiles(data, paid_order):
    f = findings(paid_order())
    assert f["location"]["key"]["en"] == "1,600 m² (6 %)"
    assert (
        f["terrain"]["key"]["fr"].replace(" ", " ").replace("\xa0", " ") == "2,0° de pente moyenne"
    )
    assert f["buildings"]["key"]["en"] == "1 on the parcel · 1 nearby"


def test_pin_orders_explain_the_missing_area_chart(
    data, client, customer, django_capture_on_commit_callbacks
):
    from apps.parcels.validation import buffer_pin

    customer.language = "en"
    customer.save()
    order = make_order(customer)
    parcel = order.parcels.get()
    parcel.geometry = buffer_pin(square_m(*DOUALA, 1).centroid, 30)
    parcel.is_approximate = True
    parcel.save()
    client.force_login(customer)
    client.post(reverse("payments:pay", args=[order.public_id]), {"method": "card"})
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            reverse("payments:demo", args=[Payment.objects.get().public_id]),
            {"decision": "approve"},
        )
    reason = findings(order)["location"]["charts"]["area"]["reason"]
    assert "only a pin was given" in reason["en"]


def test_pdf_follows_the_report_structure(data, paid_order):
    from apps.reports.pdf import render_pdf

    order = paid_order()
    report = Report.objects.get(order=order)
    captured = {}

    def capture(html_string, **kwargs):
        captured["html"] = html_string
        raise StopIteration  # stop before WeasyPrint; we only inspect the HTML

    import weasyprint

    original = weasyprint.HTML
    weasyprint.HTML = lambda string, **kwargs: capture(string)
    try:
        with pytest.raises(StopIteration):
            render_pdf(report, report.draft, "en", 1)
    finally:
        weasyprint.HTML = original
    html = captured["html"]
    headings = [
        "Prepared for",
        "1. Location and boundary check",
        "2. Demographics and area growth",
        "3. Access and services",
        "4. Flood, water and terrain",
        "5. Regulatory red flags",
        "6. Current imagery and occupation",
        "8. Area signals",
    ]
    order_of = [html.index(heading) for heading in headings]
    assert order_of == sorted(order_of)
    assert "Field verification findings" not in html  # desk tier
    assert "not included in this version" not in html  # every section has its module now
    assert html.count('class="tile"') == 10
    assert html.count('class="map-pair"') == 3  # demographics, access and flood maps
    assert html.count("data:image/svg+xml") >= 20  # 12 maps + 8 charts + QR code
    assert "Population in 2025 (WorldPop R2025A)" in html  # the demographics table
    assert "Nearest services" in html and "École Les Lauriers" in html  # the services table


# --- 3b: current imagery and change over time ------------------------------------------------


def test_vegetated_parcel_rates_land_cover_green(data, paid_order):
    imagery = findings(paid_order())["imagery"]
    assert imagery["rating"] == "green"
    assert imagery["results"]["vegetation"] == 100.0
    assert "mostly vegetated" in imagery["text"]["en"]
    assert imagery["key"]["en"] == "100 % vegetated"
    assert set(imagery["maps"]["main"]) == {"fr", "en"}
    title = imagery["charts"]["cover"]["en"]["title"]["text"]
    assert title == "About 100 % of the parcel is vegetated"


def test_unvegetated_parcel_is_amber_never_red(data, paid_order):
    data["imagery"] = FakeImagery(built_now=True)
    imagery = findings(paid_order())["imagery"]
    assert imagery["rating"] == "amber"  # pixels cannot prove buildings: at most amber
    assert imagery["results"]["open"] == 100.0
    assert "cannot tell buildings from cleared soil" in imagery["text"]["en"]


def test_cloudy_imagery_is_reported_as_unknown(data, paid_order):
    data["imagery"] = FakeImagery(cloudy=True)
    f = findings(paid_order())
    assert f["imagery"]["rating"] == "grey"
    assert f["change"]["rating"] == "grey"
    assert "too much cloud" in f["imagery"]["text"]["en"]


def test_recent_clearing_is_flagged_with_its_year(data, paid_order):
    data["imagery"] = FakeImagery(built_from=2023)
    change = findings(paid_order())["change"]
    results = change["results"]
    assert change["rating"] == "amber"
    assert (results["first_year"], results["last_year"], results["reference_year"]) == (
        2017,
        2026,
        2021,
    )
    assert results["vegetation_loss_recent_pts"] == 100.0
    assert results["cleared_years"] == [2023]
    assert [row["year"] for row in results["series"]] == list(range(2017, 2027))
    assert "from 100 % in 2021 to 0 % in 2026" in change["text"]["en"]
    assert change["key"]["en"] == "-100 pts vegetation since 2021"
    assert set(change["maps"]) == {"strip", "clearing"}
    trend = change["charts"]["trend"]["en"]
    assert trend["title"]["text"] == "Vegetation went from 100 % in 2017 to 0 % in 2026"


def test_stable_parcel_rates_change_green(data, paid_order):
    change = findings(paid_order())["change"]
    assert change["rating"] == "green"
    assert change["results"]["cleared_years"] == []
    assert "No recent clearing" in change["text"]["en"]
    assert change["key"]["en"] == "0 pts vegetation since 2021"  # never "+-0"
    assert set(change["maps"]) == {"strip"}  # no empty clearing map...
    reason = change["charts"]["clearing"]["reason"]["en"]  # ...but a labelled placeholder
    assert reason == "No part of the parcel was cleared between 2017 and 2026."


def test_image_strip_has_one_frame_per_year(data, paid_order):
    from django.core.files.storage import default_storage

    key = findings(paid_order())["change"]["maps"]["strip"]["en"]
    svg = default_storage.open(key).read().decode()
    for year in range(2017, 2027):
        assert f">{year}<" in svg
    assert "Copernicus Sentinel" in svg


def test_overpass_retries_then_falls_back_to_the_next_server():
    import httpx

    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "first" in str(request.url):
            return httpx.Response(502)
        return httpx.Response(
            200, json={"elements": [], "osm3s": {"timestamp_osm_base": "2026-10-25"}}
        )

    provider = providers.OverpassWater(
        urls=["https://first.test/api", "https://second.test/api"],
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff_s=0,
    )
    result = provider.fetch(9.7, 4.0, 9.71, 4.01)
    assert result.lines == [] and result.version == "2026-10-25"
    assert calls == ["https://first.test/api", "https://first.test/api", "https://second.test/api"]


def test_overpass_gives_up_after_all_servers_fail():
    import httpx

    provider = providers.OverpassWater(
        urls=["https://only.test/api"],
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(504))),
        backoff_s=0,
    )
    with pytest.raises(httpx.HTTPStatusError):
        provider.fetch(9.7, 4.0, 9.71, 4.01)


def test_sentinel_offset_is_not_applied_twice():
    from types import SimpleNamespace

    from apps.analysis.providers import reflectance_params

    def item(applied, offset):
        band = SimpleNamespace(extra_fields={"raster:bands": [{"scale": 0.0001, "offset": offset}]})
        return SimpleNamespace(
            properties={"earthsearch:boa_offset_applied": applied}, assets={"red": band}
        )

    assert reflectance_params(item(True, -0.1), "red") == (0.0001, 0.0)  # values already fixed
    assert reflectance_params(item(False, -0.1), "red") == (0.0001, -0.1)
    assert reflectance_params(item(None, 0), "red") == (0.0001, 0)  # before 2022


# --- 3c: flood and water ---------------------------------------------------------------------


def test_dry_parcel_far_from_water_rates_flood_green(data, paid_order):
    flood = findings(paid_order())["flood"]
    assert flood["rating"] == "green"
    assert flood["results"]["nearest_water_m"] is None
    assert flood["key"]["en"] == "No 100-year flood zone within 1 km"
    assert "No river or water body is mapped within 1 km." in flood["text"]["en"]
    assert "large rivers only" in flood["text"]["en"]  # the model's limits are always stated
    assert "grands cours d'eau" in flood["text"]["fr"]
    assert list(flood["maps"]) == ["flood", "water"]  # the flood map comes first in the PDF
    assert set(flood["datasets"]) == {"jrc-gsw", "jrc-flood-hazard", "osm-water"}
    assert "height_above_water_mean_m" not in flood["results"]


def test_a_nearby_stream_is_named_but_does_not_change_the_rating(data, paid_order):
    data["water_features"] = FakeWaterFeatures(lines=[stream(-70)])
    flood = findings(paid_order())["flood"]
    assert flood["rating"] == "green"
    assert 20 <= flood["results"]["nearest_water_m"] <= 80
    assert "The nearest river or water body is" in flood["text"]["en"]
    assert "None" not in flood["text"]["en"] + flood["text"]["fr"]
    layers = [layer["id"] for layer in flood["layers"]]
    assert "waterways" in layers and "flood" not in layers  # no flood zone in the window


def test_long_rivers_and_estuaries_are_cut_to_the_analysis_window(data, paid_order):
    """The local OSM copy returns whole features: a 50 km river must not zoom the map out."""
    from django.contrib.gis.geos import LineString

    lon, lat = DOUALA
    river = LineString([(lon - 0.003, lat - 0.25), (lon - 0.003, lat + 0.25)], srid=4326)
    estuary = box(lon + 0.2, lat, half_deg=0.195)  # reaches 0.005° (~550 m) east of the parcel
    data["water_features"] = FakeWaterFeatures(lines=[river], wetlands=[estuary])
    flood = findings(paid_order())["flood"]
    for layer_id in ("waterways", "wetlands"):
        layer = next(layer for layer in flood["layers"] if layer["id"] == layer_id)
        assert len(layer["data"]["features"]) == 1
        coords = json.dumps(layer["data"]["features"][0]["geometry"]["coordinates"])
        values = [float(v) for v in coords.replace("[", " ").replace("]", " ").split(",")]
        lons, lats = values[0::2], values[1::2]
        assert max(lons) - lon < 0.02 and abs(min(lats) - lat) < 0.02 and max(lats) - lat < 0.02
    assert flood["results"]["wetland_on_parcel"] is False


@pytest.mark.parametrize(
    ("share", "depth", "rating"),
    [
        (5, 0.3, "amber"),  # a shallow edge of the flood zone
        (5, 1.2, "red"),  # a small part, but 1 m deep or more
        (12, 0.2, "red"),  # 10 % of the parcel or more
    ],
)
def test_flood_zone_share_and_depth_set_the_rating(share, depth, rating):
    from apps.analysis.config import Thresholds
    from apps.analysis.modules.flood import FloodModule

    results = {"flood_share_pct": share, "flood_max_depth_m": depth, "flood_zone_distance_m": 0,
               "water_seen_share_pct": 0, "wetland_on_parcel": False}  # fmt: skip
    assert FloodModule._rate(results, Thresholds()) == rating
    from django.utils import translation

    with translation.override("en"):
        key = FloodModule().key_figure(results)
    assert key == f"{share} % in the 100-year flood zone · up to {depth:.1f} m"


def test_parcel_in_the_100_year_flood_is_red(data, paid_order):
    data["water"] = FakeWater(flood_m=1.4)
    flood = findings(paid_order())["flood"]
    assert flood["rating"] == "red"
    assert flood["results"]["flood_max_depth_m"] == 1.4
    # ~33 m cells: a 40 m parcel only partly fills the cells it touches, so the share is < 100
    assert flood["results"]["flood_share_pct"] >= 10
    assert "1-in-100-year river flood reaches" in flood["text"]["en"]
    assert "up to 1.4 m deep" in flood["text"]["en"]
    assert "Do not buy" in flood["text"]["en"]


def test_water_seen_on_the_parcel_is_red(data, paid_order):
    data["water"] = FakeWater(occurrence=30)
    flood = findings(paid_order())["flood"]
    assert flood["rating"] == "red"
    assert flood["results"]["water_seen_share_pct"] >= 10
    assert "of the parcel since 1984" in flood["text"]["en"]


def test_wetland_on_the_parcel_is_red_in_both_languages(data, paid_order):
    data["water_features"] = FakeWaterFeatures(wetlands=[square_m(*DOUALA, 200)])
    flood = findings(paid_order())["flood"]
    assert flood["rating"] == "red"
    assert flood["results"]["wetland_on_parcel"] is True
    assert "a wetland is mapped on the parcel" in flood["text"]["en"]
    assert "zone humide" in flood["text"]["fr"]


def test_flood_tile_names_follow_the_jrc_grid():
    from apps.analysis.providers import _tiles

    # Douala sits in the tile whose top-left corner is 0°E 10°N.
    assert _tiles(9.6, 4.0, 9.8, 4.1) == [(0, 10)]
    # A box across the equator and 10°E touches four tiles.
    assert sorted(_tiles(9.9, -0.1, 10.1, 0.1)) == [(0, 0), (0, 10), (10, 0), (10, 10)]


def test_large_water_relations_are_assembled_from_open_ways():
    """The Wouri estuary is a multipolygon relation made of many open ways, with islands."""
    from apps.analysis.providers import _osm_polygon

    def way(*points):
        return [{"lon": x, "lat": y} for x, y in points]

    element = {
        "type": "relation",
        "members": [
            {"role": "outer", "geometry": way((0, 0), (4, 0), (4, 4))},
            {"role": "outer", "geometry": way((0, 4), (4, 4))},  # reversed direction
            {"role": "outer", "geometry": way((0, 4), (0, 0))},
            {"role": "inner", "geometry": way((1, 1), (2, 1), (2, 2), (1, 2), (1, 1))},
            {"role": "outer", "geometry": way((9, 9), (9, 10))},  # cannot be closed: dropped
        ],
    }
    polygon = _osm_polygon(element)
    assert polygon.geom_type == "MultiPolygon"
    assert polygon.area == pytest.approx(16 - 1)  # 4 × 4 square minus the 1 × 1 island


def test_nearby_flood_zone_is_amber(data, paid_order):
    data["water"] = FakeWater(flood_m=2, flood_east_m=150)
    flood = findings(paid_order())["flood"]
    assert flood["rating"] == "amber"
    assert flood["results"]["flood_share_pct"] == 0
    assert 60 <= flood["results"]["flood_zone_distance_m"] < 200
    assert "the 1-in-100-year flood zone is" in flood["text"]["en"]
    assert flood["key"]["en"].startswith("100-year flood zone")
    assert flood["layers"][0]["id"] == "flood"  # the flood depth is the first layer


def test_drains_and_ditches_are_not_counted_as_water():
    from apps.analysis.providers import OverpassWater

    sent = {}

    class Client:
        def post(self, url, data, headers):
            sent["query"] = data["data"]
            import httpx

            return httpx.Response(200, json={"elements": []}, request=httpx.Request("POST", url))

    OverpassWater(urls=["https://overpass.test"], client=Client()).fetch(9.7, 4.0, 9.8, 4.1)
    assert "river|stream|canal" in sent["query"]
    assert "drain" not in sent["query"] and "ditch" not in sent["query"]


class FlakyBuildings(FakeBuildings):
    """Times out `failures` times, then answers."""

    def __init__(self, footprints, failures):
        super().__init__(footprints)
        self.failures = failures

    def fetch(self, west, south, east, north):
        import httpx

        if self.failures:
            self.failures -= 1
            raise httpx.ReadTimeout("The read operation timed out")
        return super().fetch(west, south, east, north)


def rerun(result, provider_state, buildings):
    provider_state["buildings"] = buildings
    ModuleResult.objects.filter(pk=result.pk).update(status=ModuleStatus.PENDING)


def test_network_errors_ask_for_a_retry_while_retries_remain(data, paid_order):
    from apps.analysis.pipeline import RetryLater, execute_module

    paid_order()
    result = ModuleResult.objects.get(module="buildings")
    rerun(result, data, FlakyBuildings([box(*DOUALA)], failures=1))
    with pytest.raises(RetryLater):
        execute_module(result.pk, can_retry=True)
    result.refresh_from_db()
    assert result.status == ModuleStatus.PENDING  # nothing recorded yet
    execute_module(result.pk, can_retry=True)  # the server answers this time
    result.refresh_from_db()
    assert result.status == ModuleStatus.OK and result.rating == "red"


def test_last_attempt_and_other_errors_are_recorded_as_unavailable(data, paid_order):
    from apps.analysis.pipeline import execute_module

    paid_order()
    result = ModuleResult.objects.get(module="buildings")
    rerun(result, data, FlakyBuildings([], failures=1))
    execute_module(result.pk, can_retry=False)  # retries used up
    result.refresh_from_db()
    assert result.status == ModuleStatus.FAILED and "ReadTimeout" in result.error

    class Broken:
        def fetch(self, *bounds):
            raise ValueError("bad geometry")

    rerun(result, data, Broken())
    execute_module(result.pk, can_retry=True)  # not a network error: no retry
    result.refresh_from_db()
    assert result.status == ModuleStatus.FAILED and "ValueError" in result.error


def test_run_module_retries_with_increasing_delays(monkeypatch):
    from apps.analysis import pipeline, tasks

    calls = {}

    def fail(result_id, can_retry):
        calls["can_retry"] = can_retry
        raise pipeline.RetryLater

    def retry(exc, countdown):
        calls["countdown"] = countdown
        return RuntimeError("retry scheduled")

    monkeypatch.setattr(pipeline, "execute_module", fail)
    monkeypatch.setattr(tasks.run_module, "retry", retry)
    with pytest.raises(RuntimeError, match="retry scheduled"):
        tasks.run_module.run(1)
    assert calls == {"can_retry": True, "countdown": 60}
    assert tasks.run_module.max_retries == 2


# --- 3d: access and services -----------------------------------------------------------------


def test_parcel_on_a_road_near_services_rates_access_green(data, paid_order):
    access = findings(paid_order())["access"]
    assert access["rating"] == "green"
    r = access["results"]
    assert r["touches_road"] is True and r["nearest_road_name"] == "Rue des Palmiers"
    assert r["services"]["paved_road"]["distance_m"] == pytest.approx(280, abs=5)
    school = r["services"]["school"]
    assert school["name"] == "École Les Lauriers" and 6 <= school["walk_min"] <= 10
    assert set(access["maps"]) == {"walk", "drive"}
    assert "well served: it touches a road" in access["text"]["en"]
    assert "school" in access["text"]["en"] and "min on foot" in access["text"]["en"]
    assert "elle touche une route" in access["text"]["fr"] and " ; " in access["text"]["fr"]
    assert access["key"]["en"].startswith("On a road · clinic")
    table = access["charts"]["services"]["table"]["en"]
    assert table["columns"][0] == "Destination" and len(table["rows"]) == 5
    assert table["rows"][1][1] == "École Les Lauriers"
    chart = access["charts"]["times"]["en"]
    assert {row["mode"] for row in chart["data"]["values"]} == {"On foot", "By car"}


def test_parcel_without_a_road_nearby_is_red(data, paid_order):
    from apps.osm.testing import road

    data["osm"] = osm_around_parcel(road=road(*DOUALA, -900), paved=None)
    access = findings(paid_order())["access"]
    assert access["rating"] == "red"
    assert access["results"]["touches_road"] is False
    assert "no road access" in access["text"]["en"]
    assert "the nearest road is" in access["text"]["en"]


def test_road_a_little_away_and_far_clinic_are_amber(data, paid_order):
    from apps.osm.models import Category
    from apps.osm.testing import place, road

    data["osm"] = osm_around_parcel(
        road=road(*DOUALA, -120),
        health=place(Category.HEALTH, *DOUALA, -15_000, 0, name="Hôpital"),
    )
    access = findings(paid_order())["access"]
    assert access["rating"] == "amber"
    text = access["text"]["en"]
    assert "the nearest road is 100 m from the boundary" in text
    assert "Access needs checking" in text


def test_services_beyond_the_search_radius_are_reported_as_none(data, paid_order):
    data["osm"] = osm_around_parcel(health=None, market=None)
    access = findings(paid_order())["access"]
    assert access["rating"] == "amber"
    assert access["results"]["services"]["health"] is None
    assert "no health facility could be reached" in access["text"]["en"]
    rows = access["charts"]["services"]["table"]["en"]["rows"]
    assert ["Health facility", "None found nearby", "–", "–", "–"] in rows


def test_unroutable_parcel_is_amber_not_failed(data, paid_order):
    data["router"] = FakeRouter(reachable=False)
    access = findings(paid_order())["access"]
    assert access["rating"] == "amber"
    assert access["results"]["services"]["school"]["walk_min"] is None
    assert "no school could be reached on foot" in access["text"]["en"]


def test_access_is_unavailable_until_osm_is_imported(data, paid_order, monkeypatch):
    monkeypatch.setattr("apps.analysis.modules.access.osm_provider", lambda: None)
    order = paid_order()
    result = ModuleResult.objects.get(module="access")
    assert result.status == ModuleStatus.FAILED and "load_osm" in result.error
    assert order.status == OrderStatus.IN_REVIEW


def test_water_uses_the_local_osm_copy_once_imported(db):
    from apps.analysis.providers import LocalOsmWater, OverpassWater, water_features_provider
    from apps.osm.models import Category
    from apps.osm.testing import make_import

    assert isinstance(water_features_provider(), OverpassWater)  # nothing imported yet
    make_import([(Category.WATERWAY, "stream", "", None, stream(-50))])
    assert isinstance(water_features_provider(), LocalOsmWater)


def test_buildings_come_only_from_the_local_google_copy(db):
    from apps.analysis.providers import GoogleOpenBuildings, buildings_provider
    from apps.buildings.testing import make_release

    with pytest.raises(RuntimeError, match="load_buildings"):  # never a fallback to OSM
        buildings_provider()
    lon, lat = DOUALA
    weak = box(lon + 0.0003, lat)
    make_release([(square_m(*DOUALA, 10), 0.9), (weak, 0.66), (square_m(10.5, 5.5, 10), 0.9)])
    provider = buildings_provider()
    assert isinstance(provider, GoogleOpenBuildings) and provider.min_confidence == 0.7
    west, south, east, north = square_m(*DOUALA, 200).extent
    found = provider.fetch(west, south, east, north)
    assert len(found.footprints) == 1  # the weak detection and the far one are left out
    assert found.confidences == [0.9] and found.version == "v3"


def test_buildings_finding_credits_google_and_shows_confidence(data, paid_order):
    buildings = findings(paid_order())["buildings"]
    assert buildings["datasets"] == {"google-open-buildings": "v3"}
    hover = buildings["layers"][0]["hover"]
    assert hover[1]["property"] == "confidence"
    assert hover[1]["label"] == {"fr": "Confiance de la détection", "en": "Detection confidence"}


def test_very_short_trips_read_less_than_a_minute():
    from apps.analysis.modules.access import _min

    assert _min(0.2) == "<1" and _min(4.6) == "5"


# --- 3e: demographics and area growth --------------------------------------------------------


def test_growing_area_rates_demographics_green(data, paid_order):
    demo = findings(paid_order())["demographics"]
    assert demo["rating"] == "green"
    r = demo["results"]
    assert set(r["areas"]) == {"1km", "5km", "commune"} and r["commune"] == "Douala V"
    five = r["areas"]["5km"]
    assert five["area_km2"] == pytest.approx(78.5, abs=0.5)
    assert five["growth_pct"] == pytest.approx(3.0, abs=0.01)
    assert five["density"]["2020"] == pytest.approx(4000, abs=5)
    pyramid = five["pyramid"]
    assert sum(pyramid["female"]) + sum(pyramid["male"]) == pytest.approx(100, abs=0.1)
    assert len(pyramid["female"]) == 17  # 0–4 ... 75–79, 80+
    assert five["groups"]["under_15"] == pytest.approx(41.7, abs=0.1)  # sum of 4 shares
    built = r["built_km2"]
    assert built["1975"] < built["2020"]
    text = demo["text"]["en"]
    assert text.startswith("The area is growing. About")
    assert "people live within 5 km" in text and "+3.0 % a year" in text
    assert "from 2020 to 2025" in text and "to 2030" in text  # never "2,020"
    assert "modelled estimates (WorldPop R2025A), not census counts" in text
    assert "Built-up land within 5 km grew from" in text
    assert "La zone est en croissance" in demo["text"]["fr"]
    assert demo["key"]["en"].endswith("people within 5 km · +3.0 %/yr")
    assert set(demo["maps"]) == {"density", "expansion"}
    density_en = ModuleResult.objects.get(module="demographics").maps["density"]["en"]
    from django.core.files.storage import default_storage

    with default_storage.open(density_en) as svg:
        drawn = svg.read().decode()
    assert "Within 5 km" in drawn and "À moins de 5 km" not in drawn
    table = demo["charts"]["areas"]["table"]["en"]
    assert [row[0] for row in table["rows"]] == [
        "Within 1 km",
        "Within 5 km",
        "Commune of Douala V",
    ]
    growth = demo["charts"]["growth"]["en"]
    kinds = {row["kind"] for row in growth["data"]["values"]}
    assert kinds == {"Estimate", "Projection"}  # projected years drawn dashed


@pytest.mark.parametrize(
    ("growth", "rating", "lead"),
    [
        (1.0, "amber", "The area is growing slowly."),
        (-1.0, "red", "The area's population is falling."),
    ],
)
def test_slow_or_falling_growth(data, paid_order, growth, rating, lead):
    data["population"] = FakePopulation(growth=growth)
    demo = findings(paid_order())["demographics"]
    assert demo["rating"] == rating and demo["text"]["en"].startswith(lead)


def test_population_figures_are_cached_per_area_and_year(data, paid_order):
    paid_order()
    calls = data["population"].calls
    assert calls == 9  # 3 areas x 3 years
    from apps.analysis.models import PopulationStat
    from apps.analysis.modules import MODULES

    run = AnalysisRun.objects.get()
    MODULES["demographics"].run(run.parcel)
    assert data["population"].calls == calls  # all from the cache
    assert PopulationStat.objects.count() == 9 + 21  # and GHSL: 3 areas x 7 epochs


def test_growth_since_2000_is_compared_as_rates_never_as_counts(data, paid_order):
    data["population"] = FakePopulation(years=(2015, 2020, 2025, 2030), history=(2000, 2005, 2010))
    demo = findings(paid_order())["demographics"]
    r = demo["results"]
    assert r["history_release"] == "Global1" and r["ghsl_pop_version"] == "R2023A"
    five = r["areas"]["5km"]
    assert five["growth_pct"] == pytest.approx(3.0, abs=0.01)  # the rating: R2025A only
    worldpop, ghsl = five["trends"]["worldpop"], five["trends"]["ghsl"]
    assert list(worldpop) == ["2000–2005", "2005–2010", "2015–2020", "2020–2025", "2025–2030"]
    assert "2010–2015" not in worldpop  # never across the two releases
    assert len(ghsl) == 6 and ghsl["2010–2015"] == pytest.approx(2.5, abs=0.01)
    assert five["history_growth_pct"] == pytest.approx(3.0, abs=0.01)
    assert {"worldpop-global1", "ghsl-pop"} <= set(demo["datasets"])

    growth = demo["charts"]["growth"]["en"]["data"]["values"]
    assert min(row["year"] for row in growth) == 2015  # counts: R2025A only

    trends = demo["charts"]["trends"]["en"]
    assert trends["title"]["text"] == (
        "Within 5 km, +3.0 % a year (WorldPop) and +2.5 % a year (GHSL) from 2020 to 2025"
    )
    rows = trends["data"]["values"]
    assert {row["source"] for row in rows} == {"WorldPop", "GHSL"}
    projected = {(row["source"], row["period"]) for row in rows if row["kind"] == "Projection"}
    assert projected == {("WorldPop", "2025–2030"), ("GHSL", "2020–2025"), ("GHSL", "2025–2030")}
    subtitle = " ".join(trends["title"]["subtitle"])
    assert "No rate is given across the two releases" in subtitle
    assert "GHS-POP R2023A" in subtitle
    assert "de 2020 à 2025" in demo["charts"]["trends"]["fr"]["title"]["text"]

    table = demo["charts"]["areas"]["table"]["en"]
    assert table["columns"][-1] == "Growth a year, 2000–2010 (Global1)"
    assert table["rows"][1][-1] == "+3.0 %"
    assert not any("2000 (" in column for column in table["columns"])  # no 2000 count

    from apps.analysis.models import AnalysisRun as Run
    from apps.analysis.modules import MODULES

    calls = data["population"].history_calls, data["ghsl_population"].calls
    assert calls == (9, 21)
    MODULES["demographics"].run(Run.objects.get().parcel)
    assert (data["population"].history_calls, data["ghsl_population"].calls) == calls  # cached


def test_demographics_stand_without_ghsl_population(data, paid_order):
    data["ghsl_population"] = FakeGhslPopulation(fail=True)
    demo = findings(paid_order())["demographics"]
    assert demo["rating"] == "green" and demo["results"]["ghsl_pop_version"] is None
    assert "ghsl-pop" not in demo["datasets"]
    sources = {row["source"] for row in demo["charts"]["trends"]["en"]["data"]["values"]}
    assert sources == {"WorldPop"}


def test_demographics_unavailable_without_worldpop(data, paid_order):
    data["population"] = FakePopulation(years=())
    paid_order()
    result = ModuleResult.objects.get(module="demographics")
    assert result.status == ModuleStatus.FAILED and "load_worldpop" in result.error


def test_age_sex_bands_add_up_to_the_total():
    from apps.analysis.population import AgeSex

    stats = AgeSex([10.0] * 20, [12.0] * 20)
    assert stats.total == 440
    pyramid = stats.pyramid()
    assert sum(pyramid["female"]) + sum(pyramid["male"]) == pytest.approx(100, abs=0.05)
    groups = stats.groups()
    assert groups["under_5"] + groups["5_14"] + groups["15_64"] + groups["65_plus"] == (
        pytest.approx(100, abs=0.2)
    )


def test_worldpop_and_ghsl_file_names():
    from apps.analysis import worldpop
    from apps.analysis.providers import GhslBuiltSurface

    assert worldpop.url("f", "05", 2025).endswith(
        "/R2025A/2025/CMR/v1/100m/constrained/cmr_f_05_2025_CN_100m_R2025A_v1.tif"
    )
    assert len(worldpop.band_names()) == 40
    assert worldpop.history_url(2005).endswith("/Global_2000_2020/2005/CMR/cmr_ppp_2005.tif")
    assert worldpop.history_path(2005).name == "cmr_ppp_2005_Global1_cog.tif"
    from apps.analysis.providers import GhslPopulation

    tile = GhslPopulation().tile_url(2000, 9, 19)
    assert tile.endswith(
        "/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2000_GLOBE_R2023A_4326_3ss/V1-0/tiles/"
        "GHS_POP_E2000_GLOBE_R2023A_4326_3ss_V1_0_R9_C19.zip"
    )
    ghsl = GhslBuiltSurface()
    assert ghsl.tiles(9.6, 4.0, 9.8, 4.1) == [(9, 19)]  # Douala
    assert ghsl.tiles(*ghsl.CAMEROON) == [(8, 19), (8, 20), (9, 19), (9, 20)]


# --- 3f: regulatory red flags ----------------------------------------------------------------


def stream_line(north_m, name="Ruisseau Mbopi"):
    from django.contrib.gis.geos import LineString

    from apps.osm.models import Category
    from apps.osm.testing import offset

    west, east = offset(*DOUALA, -500, north_m), offset(*DOUALA, 500, north_m)
    return (Category.WATERWAY, "stream", name, None, LineString([west, east], srid=4326))


def test_parcel_clear_of_constraints_rates_red_flags_green(data, paid_order):
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "green"
    assert flags["results"]["constraints"] == []
    assert flags["results"]["buildable_pct"] == 100
    assert "No protected area" in flags["text"]["en"]
    assert (
        "No regulatory constraint was found within 200 m"
        in (flags["charts"]["constraints"]["reason"]["en"])
    )
    assert set(flags["maps"]) == {"constraints"}
    assert flags["key"]["en"] == "No constraint found"


def test_river_public_domain_over_the_parcel_is_red(data, paid_order):
    data["osm"] = osm_around_parcel(water=stream_line(10))
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "red"
    setback = flags["results"]["constraints"][0]
    assert setback["key"] == "watercourse" and setback["confirmed"] is False
    assert setback["overlap_pct"] == pytest.approx(87.5, abs=3)  # 25 m strip, 10 m north
    text = flags["text"]["en"]
    assert "River public domain (25 m from watercourses) covers" in text
    assert "* Indicative width, to be confirmed" in text
    assert "Domaine public fluvial" in flags["text"]["fr"]
    table = flags["charts"]["constraints"]["table"]["en"]
    assert table["rows"][0][0].endswith("*") and "Ordinance No. 74-2" in table["rows"][0][3]


def test_road_right_of_way_clipping_a_corner_is_amber(data, paid_order):
    from apps.osm.testing import road

    data["osm"] = osm_around_parcel(paved=road(*DOUALA, -38, kind="primary", paved=True))
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "amber"
    assert flags["results"]["setback_overlap_pct"] == pytest.approx(5, abs=1.5)
    assert "Main road right of way" in flags["text"]["en"]


def test_uploaded_protected_area_over_the_parcel_is_red(data, paid_order):
    from apps.gazetteer.models import ReferenceLayer, ReferenceLayerKind

    ReferenceLayer.objects.create(
        kind=ReferenceLayerKind.PROTECTED_AREA,
        name="Réserve de Douala-Edéa",
        geometry=square_m(DOUALA[0] + 0.0002, DOUALA[1], 40),
        source="MINFOF",
    )
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "red"
    protected = flags["results"]["constraints"][0]
    assert protected["type"] == "protected" and protected["overlap_pct"] > 30
    assert "the protected area « Réserve de Douala-Edéa » covers" in flags["text"]["en"]


def atlas_area(kind, name, proposed=False, advisory=False):
    from apps.gazetteer.forest_atlas import SOURCE_PREFIX
    from apps.gazetteer.models import ReferenceLayer

    return ReferenceLayer.objects.create(
        kind=kind,
        name=name,
        geometry=square_m(DOUALA[0] + 0.0002, DOUALA[1], 40),
        properties={"proposed": proposed, "advisory": advisory},
        source=f"{SOURCE_PREFIX} (test)",
    )


def test_forest_reserve_over_the_parcel_is_red_and_cites_the_forest_atlas(data, paid_order):
    from apps.gazetteer.models import ReferenceLayerKind

    atlas_area(ReferenceLayerKind.FOREST_ESTATE, "Mangombe (Forêt de protection)")
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "red"
    assert (
        "the permanent forest estate « Mangombe (Forêt de protection) » covers"
        in (flags["text"]["en"])
    )
    assert "forest-atlas" in flags["datasets"]


def test_proposed_park_or_plantation_concession_over_the_parcel_is_amber(data, paid_order):
    from apps.gazetteer.models import ReferenceLayerKind

    atlas_area(ReferenceLayerKind.PROTECTED_AREA, "Mefou (Parc national)", proposed=True)
    atlas_area(ReferenceLayerKind.CONCESSION, "SOCAPALM (Plantation à grand echelle)")
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "amber"
    text = flags["text"]["en"]
    assert "« Mefou (Parc national) » (proposed, not yet gazetted) covers" in text
    assert "the concession « SOCAPALM (Plantation à grand echelle) » covers" in text


def test_ramsar_wetland_over_the_parcel_is_amber(data, paid_order):
    from apps.gazetteer.models import ReferenceLayerKind

    ebogo = "Zone Humide d'Ebogo (Site Ramsar)"
    atlas_area(ReferenceLayerKind.PROTECTED_AREA, ebogo, advisory=True)
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "amber"
    assert "the protected area « Zone Humide d'Ebogo (Site Ramsar) » covers" in flags["text"]["en"]


def test_osm_protected_areas_give_way_to_official_ones(data, paid_order):
    from apps.gazetteer.models import ReferenceLayer, ReferenceLayerKind
    from apps.osm.models import Category

    osm_park = (Category.PROTECTED, "national_park", "OSM park", None, square_m(*DOUALA, 60))
    data["osm"] = osm_around_parcel(park=osm_park)  # covers the parcel
    ReferenceLayer.objects.create(
        kind=ReferenceLayerKind.PROTECTED_AREA,
        name="Far away park",
        geometry=square_m(DOUALA[0] + 1, DOUALA[1], 40),
        source="MINFOF",
    )
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "green"
    assert flags["results"]["constraints"] == []


def test_public_utility_zone_nearby_is_amber(data, paid_order):
    from apps.gazetteer.models import ReferenceLayer, ReferenceLayerKind
    from apps.osm.testing import offset

    ReferenceLayer.objects.create(
        kind=ReferenceLayerKind.DUP_CORRIDOR,
        name="Pénétrante Est",
        geometry=square_m(*offset(*DOUALA, 120, 0), 40),
        source="Décret 2020/123",
    )
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "amber"
    dup = flags["results"]["constraints"][0]
    assert dup["type"] == "dup" and dup["overlap_m2"] == 0
    assert dup["distance_m"] == pytest.approx(80, abs=3)
    assert "public-utility (DUP) zone « Pénétrante Est » is 80 m away" in flags["text"]["en"]


def test_setback_rules_are_editable_in_the_admin(data, paid_order):
    from apps.analysis.config import DEFAULT_SETBACK_RULES
    from apps.core.models import SiteSetting

    rules = [dict(r) for r in DEFAULT_SETBACK_RULES]
    rules[0] = {**rules[0], "distance_m": 5, "confirmed": True}  # watercourses: 5 m
    SiteSetting.objects.update_or_create(key="setback_rules", defaults={"value": rules})
    data["osm"] = osm_around_parcel(water=stream_line(30))
    flags = findings(paid_order())["red_flags"]
    assert flags["rating"] == "green"  # the stream is 10 m from the parcel, beyond 5 m


# --- 3g: interactive layers for the portal ---------------------------------------------------


def test_modules_store_interactive_layers_for_the_portal(data, paid_order):
    from django.core.files.storage import default_storage

    order = paid_order()
    layers = {r.module: r.layers for r in ModuleResult.objects.all()}
    ids = {module: [layer["id"] for layer in found] for module, found in layers.items()}
    assert ids["terrain"] == ["slope"]
    assert ids["buildings"] == ["buildings", "ring"]
    assert "imagery" in ids["imagery"] and "landcover" in ids["imagery"]
    assert {"walk-areas", "drive-areas", "services"} <= set(ids["access"])
    assert {"density", "built", "rings"} <= set(ids["demographics"])
    slope = layers["terrain"][0]
    assert "png" not in slope and default_storage.exists(slope["image"])  # stored as a PNG
    assert slope["title"] == {"fr": "Pente", "en": "Slope"}
    assert len(slope["coordinates"]) == 4 and slope["hover"]["unit"]["en"] == "°"
    years = [layer for layer in layers["change"] if layer.get("group") == "years"]
    assert len(years) >= 3 and years[-1]["visible"] and not years[0]["visible"]
    buildings = layers["buildings"][0]["data"]["features"]
    assert buildings and buildings[0]["properties"]["status"]["en"] in {
        "On the parcel",
        "Within 20 m of the boundary",
        "Other buildings",
    }
    draft = Report.objects.get(order=order).draft
    assert any(f["layers"] for f in draft["findings"])


# --- Phase 4: single-module re-runs, boundary changes, review maps ---------------------------


def test_rerunning_one_module_keeps_edits_to_the_others(
    data, paid_order, analyst_client, django_capture_on_commit_callbacks
):
    data["population"] = FakePopulation(years=())  # WorldPop missing: the module fails
    order = paid_order()
    assert findings(order)["demographics"]["unavailable"]
    analyst_client.post(
        review_url(order),
        review_form(
            order,
            **{f"text_en_{form_index(order, 'location')}": "Checked by the analyst."},
            action="save",
        ),
    )
    data["population"] = FakePopulation()  # the data is back

    with django_capture_on_commit_callbacks(execute=True):
        response = analyst_client.post(review_url(order), {"action": "rerun:demographics"})
    assert response.status_code == 302
    order.refresh_from_db()
    assert order.status == OrderStatus.IN_REVIEW
    after = findings(order)
    assert not after["demographics"]["unavailable"]  # rebuilt
    assert after["demographics"]["rating"] == "green"
    assert after["location"]["text"]["en"] == "Checked by the analyst."  # kept
    assert AnalysisRun.objects.count() == 1
    assert AnalysisRun.objects.get().status == RunStatus.COMPLETED


def test_an_older_run_never_overwrites_the_draft_of_a_newer_one(data, paid_order):
    from apps.analysis import pipeline

    order = paid_order()
    parcel = order.parcels.get()
    old = AnalysisRun.objects.get()
    newer = AnalysisRun.objects.create(parcel=parcel, status=RunStatus.RUNNING)
    report = Report.objects.get(order=order)
    report.run = newer
    report.save()
    old.status = RunStatus.RUNNING
    old.save()
    assert pipeline.finish_run_if_complete(old.pk) is False
    report.refresh_from_db()
    assert report.run_id == newer.pk


def test_review_screen_shows_interactive_maps(data, paid_order, analyst_client):
    order = paid_order()
    html = analyst_client.get(review_url(order)).content.decode()
    assert 'data-report-map="map-terrain-config"' in html
    assert 'value="rerun:terrain"' in html
    assert reverse("admin:parcels_parcel_geometry", args=[order.parcels.get().pk]) in html


# --- Phase 5: area signals ----------------------------------------------------------------


def area_levels(*places):
    from apps.incidents.models import AreaSearch, SearchProvider

    levels = []
    for place in places:
        search = AreaSearch.objects.create(
            place=place, provider=SearchProvider.OUTLETS, ok=True, searched_at=timezone.now()
        )
        levels.append({"place": place, "searches": [search], "item_ids": set(), "reused": False})
    return levels


def approved_incident(place, geometry, precision, **extra):
    from apps.incidents.models import Incident, ReviewStatus

    return Incident.objects.create(
        incident_type=extra.pop("incident_type", "demolition"),
        event_date=extra.pop("event_date", date(2025, 3, 14)),
        summary_fr="Des maisons ont été démolies, selon la commune.",
        summary_en="Houses were demolished, according to the council.",
        place=place,
        geometry=geometry,
        precision=precision,
        review_status=ReviewStatus.APPROVED,
        **extra,
    )


@pytest.fixture
def douala_places(db):
    from apps.gazetteer.models import GazetteerPlace, PlaceType

    region = GazetteerPlace.objects.create(
        name="Littoral", place_type=PlaceType.REGION, geometry=square_m(*DOUALA, 80_000)
    )
    commune = GazetteerPlace.objects.create(
        name="Douala V", place_type=PlaceType.COMMUNE, geometry=square_m(*DOUALA, 10_000)
    )
    quartier = GazetteerPlace.objects.create(
        name="Bonamoussadi",
        place_type=PlaceType.QUARTIER,
        geometry=Point(DOUALA[0] + 0.005, DOUALA[1], srid=4326),
    )
    far = GazetteerPlace.objects.create(
        name="Japoma", place_type=PlaceType.QUARTIER, geometry=Point(9.80, 4.0, srid=4326)
    )
    return {"region": region, "commune": commune, "quartier": quartier, "far": far}


def test_signals_list_approved_incidents_nearby_and_in_searched_areas(
    data, paid_order, douala_places
):
    from apps.incidents.models import LocationPrecision, ReviewStatus

    p = douala_places
    data["area_levels"] = area_levels(p["commune"])  # enough found at commune level
    approved_incident(p["quartier"], p["quartier"].geometry, LocationPrecision.QUARTIER)
    approved_incident(
        p["commune"], p["commune"].geometry, LocationPrecision.COMMUNE,
        incident_type="expropriation", is_official_act=True, event_date=date(2020, 1, 1),
    )  # fmt: skip
    approved_incident(p["far"], p["far"].geometry, LocationPrecision.QUARTIER)  # 12 km away
    approved_incident(p["region"], p["region"].geometry, LocationPrecision.REGION)  # not reached
    approved_incident(
        p["quartier"], p["quartier"].geometry, LocationPrecision.QUARTIER,
        event_date=date(2010, 1, 1),
    )  # fmt: skip  # older than 10 years
    unreviewed = approved_incident(p["quartier"], p["quartier"].geometry, "quartier")
    unreviewed.review_status = ReviewStatus.UNREVIEWED
    unreviewed.save()

    order = paid_order()
    signals = findings(order)["signals"]
    results = ModuleResult.objects.get(module="signals").results
    assert signals["rating"] == "info"
    assert [(i["type"], i["level"]) for i in results["incidents"]] == [
        ("expropriation", "commune"),  # official acts first (FR-33)
        ("demolition", "nearby"),
    ]
    assert results["incidents"][1]["distance_m"] == pytest.approx(530, abs=40)
    assert "2 reported land issue(s)" in signals["text"]["en"]
    assert "1 of them involve an official act" in signals["text"]["en"]


def test_signals_section_always_carries_the_area_statement(data, paid_order):
    import weasyprint

    from apps.reports.pdf import render_pdf

    order = paid_order()
    signals = findings(order)["signals"]
    assert signals["rating"] == "info"
    assert "No approved report" in signals["text"]["en"]
    captured = {}

    def capture(string, **kwargs):
        captured["html"] = string
        raise StopIteration

    original, weasyprint.HTML = weasyprint.HTML, capture
    try:
        with pytest.raises(StopIteration):
            render_pdf(
                Report.objects.get(order=order), Report.objects.get(order=order).draft, "en", 1
            )
    finally:
        weasyprint.HTML = original
    html = captured["html"]
    assert "not findings about this parcel or its owners" in html  # FR-34
    assert "For information" in html  # the neutral tile


def test_signals_queue_extraction_for_new_items_when_a_key_is_set(
    data, paid_order, douala_places, settings, monkeypatch
):
    from apps.incidents.models import SourceItem

    settings.ANTHROPIC_API_KEY = "test-key"
    queued = []
    monkeypatch.setattr("apps.incidents.tasks.extract_items.delay", queued.append)
    item = SourceItem.objects.create(url="https://a.cm/1", title="Casse", content_hash="h1")
    data["area_levels"] = area_levels(douala_places["commune"])
    data["area_levels"][0]["item_ids"] = {item.pk}
    paid_order()
    assert queued == [[item.pk]]
    assert ModuleResult.objects.get(module="signals").results["awaiting_extraction"] == 1
