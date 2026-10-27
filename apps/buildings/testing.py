"""Helpers for tests: a small active building release."""

from .models import Building, BuildingRelease, ReleaseStatus


def make_release(footprints=(), confidence=0.9, status=ReleaseStatus.ACTIVE):
    """footprints: GEOS polygons (SRID 4326), or (polygon, confidence) pairs."""
    release = BuildingRelease.objects.create(version="v3", source_url="test", status=status)
    rows = [f if isinstance(f, tuple) else (f, confidence) for f in footprints]
    rows = [(g[0] if g.geom_type == "MultiPolygon" else g, score) for g, score in rows]
    Building.objects.bulk_create(
        Building(release=release, geom=geom, area_m2=0, confidence=score) for geom, score in rows
    )
    release.count = len(rows)
    release.save(update_fields=["count"])
    return release
