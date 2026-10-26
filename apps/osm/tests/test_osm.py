import httpx
import pytest
from django.contrib.gis.geos import GEOSGeometry

from apps.osm import loader
from apps.osm.models import Category, ImportStatus, OsmFeature, OsmImport
from apps.osm.queries import nearest
from apps.osm.testing import make_import, place, road
from apps.parcels.testing import DOUALA, square_m


@pytest.mark.parametrize(
    ("tags", "shape", "expected"),
    [
        ({"building": "yes"}, "area", [("building", "yes", None)]),
        ({"building": "no"}, "area", []),
        ({"waterway": "river"}, "line", [("waterway", "river", None)]),
        ({"waterway": "drain"}, "line", []),  # drains line Douala's streets: left out
        ({"natural": "wetland"}, "area", [("wetland", "wetland", None)]),
        ({"highway": "primary"}, "line", [("road", "primary", True)]),  # main roads: paved
        ({"highway": "residential"}, "line", [("road", "residential", None)]),  # unknown
        ({"highway": "residential", "surface": "asphalt"}, "line", [("road", "residential", True)]),
        ({"highway": "primary", "surface": "dirt"}, "line", [("road", "primary", False)]),
        ({"highway": "footway"}, "line", []),  # no vehicle access
        ({"amenity": "school"}, "point", [("school", "school", None)]),
        ({"healthcare": "centre"}, "point", [("health", "centre", None)]),
        ({"amenity": "marketplace"}, "point", [("market", "marketplace", None)]),
        ({"man_made": "water_well"}, "point", [("water_point", "water_well", None)]),
        (
            {"boundary": "protected_area", "protection_title": "Réserve forestière"},
            "area",
            [("protected", "Réserve forestière", None)],
        ),
        ({"leisure": "nature_reserve"}, "area", [("protected", "nature_reserve", None)]),
        ({"power": "line", "voltage": "225000"}, "line", [("power_line", "225000", None)]),
        ({"power": "minor_line"}, "line", []),
        ({"railway": "rail"}, "line", [("railway", "rail", None)]),
        ({"natural": "coastline"}, "line", [("coastline", "coastline", None)]),
        (
            {"building": "school", "amenity": "school"},
            "area",
            [("building", "school", None), ("school", "school", None)],
        ),
    ],
)
def test_classify_keeps_what_the_analysis_needs(tags, shape, expected):
    assert [(str(c), k, p) for c, k, p in loader.classify(tags, shape)] == expected


def test_ewkb_adds_the_srid():
    point = GEOSGeometry("POINT (9.7 4.05)")
    geom = GEOSGeometry(memoryview(bytes.fromhex(loader.ewkb(bytes(point.wkb).hex()))))
    assert geom.srid == 4326 and geom.coords == (9.7, 4.05)


OSM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="4.0500" lon="9.7000" version="1"/>
  <node id="2" lat="4.0500" lon="9.7010" version="1"/>
  <node id="3" lat="4.0510" lon="9.7010" version="1"/>
  <node id="4" lat="4.0510" lon="9.7000" version="1"/>
  <node id="5" lat="4.0520" lon="9.6990" version="1"/>
  <node id="6" lat="4.0520" lon="9.7030" version="1"/>
  <node id="7" lat="4.0530" lon="9.7005" version="1">
    <tag k="amenity" v="school"/><tag k="name" v="École publique de Bonamoussadi"/>
  </node>
  <node id="8" lat="4.0490" lon="9.6990" version="1"/>
  <node id="9" lat="4.0490" lon="9.7030" version="1"/>
  <way id="10" version="1">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
    <tag k="building" v="house"/>
  </way>
  <way id="11" version="1">
    <nd ref="5"/><nd ref="6"/><tag k="highway" v="primary"/><tag k="name" v="Rue 1"/>
  </way>
  <way id="12" version="1">
    <nd ref="8"/><nd ref="9"/><tag k="waterway" v="drain"/>
  </way>
</osm>
"""


@pytest.mark.django_db(transaction=True)
def test_loader_reads_an_extract_and_replaces_the_active_import(tmp_path):
    old = make_import([road(*DOUALA, 50)])
    path = tmp_path / "test.osm"
    path.write_text(OSM_XML, encoding="utf-8")

    new = loader.load(path)

    assert new.status == ImportStatus.ACTIVE and OsmImport.active() == new
    assert new.counts == {"building": 1, "road": 1, "school": 1}  # the drain is left out
    old.refresh_from_db()
    assert old.status == ImportStatus.RETIRED
    assert not OsmFeature.objects.filter(osm_import=old).exists()  # old features dropped
    school = OsmFeature.objects.get(category=Category.SCHOOL)
    assert school.name == "École publique de Bonamoussadi" and school.geom.geom_type == "Point"
    building = OsmFeature.objects.get(category=Category.BUILDING)
    assert building.geom.geom_type == "MultiPolygon" and building.osm_ref == "w10"


@pytest.mark.django_db
def test_nearest_orders_by_distance_and_filters_paved_roads():
    osm = make_import(
        [
            road(*DOUALA, 300, kind="residential"),
            road(*DOUALA, -800, kind="primary", paved=True, name="Route principale"),
            place(Category.SCHOOL, *DOUALA, 900, 0, name="Far"),
            place(Category.SCHOOL, *DOUALA, 200, 0, name="Near"),
        ]
    )
    parcel = square_m(*DOUALA, 40)
    roads = nearest(osm, Category.ROAD, parcel, 2000)
    assert [r.kind for r in roads] == ["residential", "primary"]
    assert roads[0].distance_m == pytest.approx(280, abs=3)  # from the boundary, not the centre
    paved = nearest(osm, Category.ROAD, parcel, 2000, paved=True)
    assert [r.name for r in paved] == ["Route principale"]
    schools = nearest(osm, Category.SCHOOL, parcel, 500)
    assert [s.name for s in schools] == ["Near"]  # "Far" is outside the radius


def test_download_resumes_after_a_stalled_transfer(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.time, "sleep", lambda s: None)
    calls = []

    class Stalls(httpx.SyncByteStream):
        def __iter__(self):
            yield b"PBF-"
            raise httpx.ReadTimeout("stalled")

    def handler(request):
        calls.append(request.headers.get("range"))
        if len(calls) == 1:
            return httpx.Response(200, stream=Stalls())
        return httpx.Response(206, content=b"DATA")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    path = loader.download("https://example.test/x.pbf", tmp_path / "x.pbf", client=client)
    assert path.read_bytes() == b"PBF-DATA"
    assert calls == [None, "bytes=4-"]
