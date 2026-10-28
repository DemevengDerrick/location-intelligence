"""Basemap settings shared by every map the browser draws."""

import json

from django.conf import settings
from django.contrib.gis import admin as gis_admin
from django.contrib.gis.forms import OSMWidget


def basemap_url():
    url = settings.BASEMAP_TILE_URL
    return f"{url}?token={settings.ESRI_API_KEY}" if settings.ESRI_API_KEY else url


def preview_config(geometry=None, pin=None):
    """Config for static/js/parcel-preview.js: a boundary outline and/or a pin."""
    return {
        "basemapUrl": basemap_url(),
        "attribution": settings.BASEMAP_ATTRIBUTION,
        "geometry": json.loads(geometry.geojson) if geometry is not None else None,
        "pin": json.loads(pin.geojson) if pin is not None else None,
    }


class BasemapWidget(OSMWidget):
    """Django's admin map on our basemap: the OSM tile servers refuse its requests."""

    template_name = "gis/basemap-widget.html"
    default_lon = 12.35  # Cameroon
    default_lat = 5.7
    default_zoom = 6

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["basemap_url"] = basemap_url()
        context["basemap_attribution"] = settings.BASEMAP_ATTRIBUTION
        return context


class GISModelAdmin(gis_admin.GISModelAdmin):
    gis_widget = BasemapWidget
