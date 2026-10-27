"""Admin-editable area-signals settings (SiteSetting "area_signals"), with code defaults."""

from dataclasses import dataclass, field, fields

from apps.core.site_settings import get_setting

SETTING_KEY = "area_signals"

# FR-22: land-issue keywords, French and English. An item is kept if its title or
# description contains a strong keyword, or if its title contains a weak one, or its
# description two different weak ones: words like "foncier" also turn up in passing in
# investment or politics stories.
DEFAULT_KEYWORDS = [
    "litige foncier", "litiges fonciers", "conflit foncier", "conflits fonciers",
    "double vente", "titre foncier", "titres fonciers", "retrait de titre",
    "annulation de titre", "démolition", "démolitions", "démoli", "démolis", "démolies",
    "déguerpissement", "déguerpissements", "déguerpir", "déguerpi", "déguerpis",
    "déguerpies", "expropriation", "expropriations", "exproprié", "expropriés",
    "utilité publique", "spoliation", "land dispute", "land disputes", "land conflict",
    "land grabbing", "land grab", "land title", "land titles", "eviction", "evictions",
    "evicted", "demolition", "demolitions", "demolished", "public utility", "encroachment",
]  # fmt: skip
DEFAULT_WEAK_KEYWORDS = [
    "foncier", "foncière", "fonciers", "foncières", "casse", "casses", "accaparement",
    "lotissement", "lotissements", "domaine public", "domaine national", "chefferie",
    "chefferies", "land", "landowner", "landowners",
]  # fmt: skip


@dataclass(frozen=True)
class SignalsSettings:
    radius_km: float = 2.0  # FR-32: point and quartier incidents within this distance
    years: int = 10  # FR-32: incidents older than this are not listed
    max_age_days: int = 30  # a place's saved search is reused for this long
    min_items: int = 5  # widen the search to the next admin level below this many items
    gdelt_timespan: str = "3months"  # the GDELT DOC API looks back at most three months
    gdelt_max_records: int = 75
    # Words added to the place name on outlet search feeds (one request each)
    outlet_search_words: list = field(
        default_factory=lambda: ["foncier", "déguerpissement", "expropriation"]
    )
    # The same for English-language outlets (Cameroon News Agency, The Post...)
    outlet_search_words_en: list = field(default_factory=lambda: ["land", "eviction", "demolition"])
    keywords: list = field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    weak_keywords: list = field(default_factory=lambda: list(DEFAULT_WEAK_KEYWORDS))
    # Off since October 2026: the free GDELT DOC API refused about half our requests and
    # returned no articles. Set "gdelt_enabled": true in the setting to try it again.
    gdelt_enabled: bool = False
    # GDELT rejects long queries, so it gets a shorter list
    gdelt_keywords: list = field(
        default_factory=lambda: [
            "foncier",
            "fonciers",
            "déguerpissement",
            "expropriation",
            "casse",
            "démolition",
            "double vente",
            "titre foncier",
            "land dispute",
            "eviction",
            "demolition",
            "land grabbing",
        ]  # fmt: skip
    )


def signals_settings() -> SignalsSettings:
    stored = get_setting(SETTING_KEY, {}) or {}
    types = {f.name: f.type for f in fields(SignalsSettings)}
    values = {}
    for key, value in stored.items():
        if key not in types:
            continue
        kind = types[key]
        if kind in ("float", float):
            value = float(value)
        elif kind in ("int", int):
            value = int(value)
        elif kind in ("bool", bool) and not isinstance(value, bool):
            value = str(value).strip().lower() in {"1", "true", "yes", "on"}
        values[key] = value
    return SignalsSettings(**values)
