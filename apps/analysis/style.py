"""Shared visual style for every map and chart (FR-64, FR-67).

Okabe-Ito colours: distinguishable with colour-vision deficiency, and the sequential ramps
stay readable in greyscale. Ratings are always shown with colour *and* an icon and a word.
"""

from django.utils.translation import gettext_lazy

RATING_COLOURS = {"green": "#009E73", "amber": "#E69F00", "red": "#D55E00", "grey": "#999999"}
RATING_ICONS = {"green": "✓", "amber": "!", "red": "✕", "grey": "?"}
# The word shown with every rating badge, in reports and in the portal.
RATING_WORDS = {
    "green": gettext_lazy("Good"),
    "amber": gettext_lazy("Check"),
    "red": gettext_lazy("Warning"),
    "grey": gettext_lazy("Unknown"),
}

PARCEL = {"edgecolor": "#000000", "facecolor": "none", "linewidth": 2.2, "zorder": 10}
PARCEL_HALO = {"edgecolor": "#FFFFFF", "facecolor": "none", "linewidth": 4.5, "zorder": 9}
BUFFER = {
    "edgecolor": "#555555",
    "facecolor": "none",
    "linewidth": 1,
    "linestyle": "--",
    "zorder": 8,
}

BUILDING_INSIDE = "#D55E00"
BUILDING_NEAR = "#E69F00"
BUILDING_OTHER = "#BBBBBB"

# Slope classes, light to dark (works in greyscale).
SLOPE_CLASSES = ["#F7F4D8", "#C9DD9C", "#7FB77E", "#2D6A4F"]

FONT = "DejaVu Sans"
MAP_SIZE_IN = (6.2, 4.6)  # fits an A4 text column; vector output

# Categorical colours for charts (Okabe-Ito order), and named series used across charts.
CHART_CATEGORY = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442"]
SERIES = {
    "computed": "#0072B2",
    "stated": "#E69F00",
    "built": "#D55E00",
    "vegetation": "#009E73",
    "bare": "#E6D3A3",
    "open": "#B39B72",  # built-up or bare ground
    "water": "#56B4E9",
    "male": "#0072B2",
    "female": "#CC79A7",
    "comparison": "#777777",
    "walk": "#009E73",
    "drive": "#0072B2",
}

# Access and services: one colour and marker per kind of destination (maps and table).
SERVICE_STYLE = {
    "school": ("#0072B2", "^"),
    "health": ("#D55E00", "P"),
    "market": ("#CC79A7", "s"),
    "water_point": ("#56B4E9", "o"),
}
ISOCHRONE_COLOURS = {5: "#1B7837", 10: "#7FBF7B", 15: "#D9F0D3"}  # darker = closer
