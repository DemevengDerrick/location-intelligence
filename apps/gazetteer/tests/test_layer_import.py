import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.gazetteer.models import ReferenceLayer

pytestmark = pytest.mark.django_db


def geojson(*names):
    features = [
        {
            "type": "Feature",
            "properties": {"NOM": name, "DECRET": "2020/123"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [9.70 + i / 100, 4.05],
                        [9.71 + i / 100, 4.05],
                        [9.71 + i / 100, 4.06],
                        [9.70 + i / 100, 4.05],
                    ]
                ],
            },
        }
        for i, name in enumerate(names)
    ]
    data = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    return SimpleUploadedFile("dup.geojson", data, content_type="application/geo+json")


def post(client, upload, **extra):
    return client.post(
        reverse("admin:gazetteer_referencelayer_import"),
        {"kind": "dup_corridor", "file": upload, "name_field": "NOM", "source": "MINHDU", **extra},
    )


def test_admin_imports_a_layer_with_names_and_attributes(admin_client):
    response = post(admin_client, geojson("Pénétrante Est", "Boulevard de la Liberté"))
    assert response.status_code == 302
    names = sorted(ReferenceLayer.objects.values_list("name", flat=True))
    assert names == ["Boulevard de la Liberté", "Pénétrante Est"]
    layer = ReferenceLayer.objects.get(name="Pénétrante Est")
    assert layer.kind == "dup_corridor" and layer.properties["DECRET"] == "2020/123"
    assert layer.source == "MINHDU"


def test_replace_swaps_the_previous_import_from_the_same_source(admin_client):
    post(admin_client, geojson("A", "B"))
    post(admin_client, geojson("C"), replace="on")
    assert list(ReferenceLayer.objects.values_list("name", flat=True)) == ["C"]


def test_unreadable_files_are_reported_on_the_form(admin_client):
    upload = SimpleUploadedFile("layer.txt", b"hello")
    response = post(admin_client, upload)
    assert response.status_code == 200
    assert "GeoJSON, KML or a zipped shapefile" in response.content.decode()
    assert not ReferenceLayer.objects.exists()
