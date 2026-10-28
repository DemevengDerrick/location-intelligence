"""Admin-editable analysis thresholds (SiteSetting "analysis_thresholds"), with code defaults.
Thresholds never live in module code (TRD §4, "Rules for every module")."""

from dataclasses import dataclass, fields

from apps.core.site_settings import get_setting

SETTING_KEY = "analysis_thresholds"


@dataclass(frozen=True)
class Thresholds:
    area_amber_pct: float = 10  # stated vs computed area difference
    area_red_pct: float = 25
    slope_amber_deg: float = 5  # mean slope
    slope_red_deg: float = 10
    erosion_slope_deg: float = 15  # share of the parcel steeper than this is reported
    building_buffer_m: float = 20  # "near the boundary" for buildings
    building_min_confidence: float = 0.7  # Google Open Buildings detections below this are ignored
    # Occupation (current imagery): share of the parcel not vegetated (built-up or bare)
    open_amber_pct: float = 50
    # Change over time: vegetation lost in the last 5 years, in percentage points
    clearing_amber_pts: float = 20
    # Sentinel-2 composites
    imagery_max_scene_cloud: float = 70  # scenes cloudier than this are skipped
    imagery_max_scenes: float = 6  # scenes combined per composite
    change_first_year: float = 2017
    # A year is left out of the change series when too little of the area around the parcel was
    # seen clearly, or when its vegetation index is far below the other years' median: old
    # scenes (2016-2017) have no usable cloud mask, and dry-season haze then looks like bare soil
    change_min_window_pct: float = 70
    change_haze_ndvi_drop: float = 0.06
    # Flood and water
    gsw_water_pct: float = 50  # surface-water occurrence counted as "water" (% of time)
    water_seen_red_pct: float = 10  # share of the parcel where water was ever seen
    flood_share_red_pct: float = 10  # share of the parcel in the 1-in-100-year flood
    flood_depth_red_m: float = 1  # any part of the parcel flooded this deep: red
    flood_zone_amber_m: float = 200  # distance to the modelled 1-in-100-year flood zone
    # Access and services
    road_touch_m: float = 10  # a road this close to the boundary counts as touching it
    road_red_m: float = 500  # no road at all within this distance: red
    paved_road_amber_m: float = 2000
    health_drive_amber_min: float = 30
    school_walk_amber_min: float = 30
    service_search_m: float = 20000  # services further than this are reported as none found
    # Demographics (annual population growth within 5 km, %)
    growth_green_pct: float = 2.0
    growth_red_pct: float = 0.0  # below this (a falling population): red
    ghsl_built_share: float = 0.1  # GHSL cell counted as built-up from this share of its area
    # Regulatory red flags
    setback_red_pct: float = 10  # setback strips covering this share of the parcel: red
    constraint_near_m: float = 200  # protected areas, DUP zones, corridors this close: amber
    # Land-cover classification (spectral indices)
    ndvi_vegetation: float = 0.35
    mndwi_water: float = 0.2


def thresholds() -> Thresholds:
    stored = get_setting(SETTING_KEY, {}) or {}
    known = {f.name for f in fields(Thresholds)}
    return Thresholds(**{k: float(v) for k, v in stored.items() if k in known})


SETBACK_KEY = "setback_rules"
ROAD_MAIN = ["motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"]
ROAD_SECONDARY = ["secondary", "tertiary", "secondary_link", "tertiary_link"]
PUBLIC_DOMAIN = {
    "fr": "Ordonnance n° 74-2 du 6 juillet 1974 fixant le régime domanial, art. 3",
    "en": "Ordinance No. 74-2 of 6 July 1974 on the State domain, art. 3",
}
INDICATIVE = {
    "fr": "Valeur indicative, à confirmer par un juriste",
    "en": "Indicative value, to be confirmed by a lawyer",
}

# Setback rules (SiteSetting "setback_rules", editable in the admin): a strip of `distance_m`
# around each OSM feature of `category` (and `kinds`, if given). "confirmed" stays false until
# a Cameroonian lawyer has checked the value; unconfirmed rules are flagged in the report.
DEFAULT_SETBACK_RULES = [
    {"key": "watercourse", "category": "waterway", "kinds": [], "distance_m": 25,
     "label": {"fr": "Domaine public fluvial (25 m des cours d'eau)",
               "en": "River public domain (25 m from watercourses)"},
     "basis": PUBLIC_DOMAIN, "confirmed": False},
    {"key": "water_body", "category": "water", "kinds": [], "distance_m": 25,
     "label": {"fr": "Domaine public fluvial et lacustre (25 m des berges)",
               "en": "Lake and river public domain (25 m from the banks)"},
     "basis": PUBLIC_DOMAIN, "confirmed": False},
    {"key": "shore", "category": "coastline", "kinds": [], "distance_m": 50,
     "label": {"fr": "Domaine public maritime (50 m du rivage)",
               "en": "Sea-shore public domain (50 m from the shore)"},
     "basis": PUBLIC_DOMAIN, "confirmed": False},
    {"key": "main_road", "category": "road", "kinds": ROAD_MAIN, "distance_m": 20,
     "label": {"fr": "Emprise des routes principales (20 m de l'axe)",
               "en": "Main road right of way (20 m from the centreline)"},
     "basis": INDICATIVE, "confirmed": False},
    {"key": "secondary_road", "category": "road", "kinds": ROAD_SECONDARY, "distance_m": 12,
     "label": {"fr": "Emprise des routes secondaires (12 m de l'axe)",
               "en": "Secondary road right of way (12 m from the centreline)"},
     "basis": INDICATIVE, "confirmed": False},
    {"key": "railway", "category": "railway", "kinds": [], "distance_m": 15,
     "label": {"fr": "Emprise ferroviaire (15 m de la voie)",
               "en": "Railway right of way (15 m from the track)"},
     "basis": INDICATIVE, "confirmed": False},
    {"key": "power_line", "category": "power_line", "kinds": [], "distance_m": 15,
     "label": {"fr": "Servitude de ligne haute tension (15 m de la ligne)",
               "en": "High-voltage line easement (15 m from the line)"},
     "basis": INDICATIVE, "confirmed": False},
]  # fmt: skip


def setback_rules():
    return get_setting(SETBACK_KEY, None) or DEFAULT_SETBACK_RULES
