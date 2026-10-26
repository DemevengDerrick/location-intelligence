"""Admin-editable intake thresholds (SiteSetting "parcel_intake"), with code defaults."""

from dataclasses import dataclass, fields

from apps.core.site_settings import get_setting

SETTING_KEY = "parcel_intake"


@dataclass(frozen=True)
class IntakeConfig:
    min_area_m2: float = 50  # FR-8: warn below
    max_area_m2: float = 5_000_000  # FR-8: warn above (500 ha)
    pin_buffer_m: float = 30  # FR-9
    area_difference_pct: float = 10  # FR-11: highlight above


def intake_config() -> IntakeConfig:
    stored = get_setting(SETTING_KEY, {}) or {}
    known = {f.name for f in fields(IntakeConfig)}
    return IntakeConfig(**{k: float(v) for k, v in stored.items() if k in known})
