"""Population around the parcel from WorldPop age-sex rasters (TRD §4.1).

`PopulationProvider` is the interface; `WorldPopRasters` reads the downloaded R2025A stack
and the older Global1 totals (apps.analysis.worldpop). Results are cached by geometry,
release and year (FR-56), so a commune is computed once and reused across orders.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from . import worldpop

# Raster bands: ages 0, 1–4, 5–9 ... 85–89, 90+. Report bands: 0–4, 5–9 ... 75–79, 80+.
RASTER_AGES = [int(a) for a in worldpop.AGES]
BANDS = [f"{a}–{a + 4}" for a in range(0, 80, 5)] + ["80+"]


@dataclass
class AgeSex:
    female: list  # 20 raster bands, people
    male: list

    @property
    def total(self):
        return float(sum(self.female) + sum(self.male))

    def _five_year(self, values):
        bands = [values[0] + values[1]]  # 0 and 1–4
        bands += values[2:17]  # 5–9 ... 75–79
        bands.append(sum(values[17:]))  # 80+
        return bands

    def pyramid(self):
        """Share of the total (%) per 5-year band: {"female": [...], "male": [...]}."""
        total = self.total or 1
        return {
            "female": [round(v / total * 100, 2) for v in self._five_year(self.female)],
            "male": [round(v / total * 100, 2) for v in self._five_year(self.male)],
        }

    def _sum(self, low, high):
        """People aged low..high (inclusive, raster band starts)."""
        idx = [i for i, age in enumerate(RASTER_AGES) if low <= age <= high]
        return sum(self.female[i] + self.male[i] for i in idx)

    def groups(self):
        """Age-group shares (%) and the dependency ratio (dependants per 100 aged 15–64)."""
        total = self.total or 1
        under5 = self._sum(0, 4)
        school = self._sum(5, 14)
        working = self._sum(15, 64)
        older = self._sum(65, 200)
        return {
            "under_5": round(under5 / total * 100, 1),
            "5_14": round(school / total * 100, 1),
            "15_64": round(working / total * 100, 1),
            "65_plus": round(older / total * 100, 1),
            "under_15": round((under5 + school) / total * 100, 1),
            "dependency_ratio": round((under5 + school + older) / (working or 1) * 100, 1),
        }

    def as_json(self):
        return {"female": self.female, "male": self.male}

    @classmethod
    def from_json(cls, data):
        return cls(data["female"], data["male"])


class PopulationProvider(Protocol):
    release: str
    dataset: str

    def years(self) -> list[int]: ...

    def age_sex(self, geom, year) -> AgeSex: ...

    def density(self, west, south, east, north, year): ...

    # Totals before the main release starts, from an older release with another method.
    history_release: str
    history_dataset: str

    def history_years(self) -> list[int]: ...

    def history_total(self, geom, year) -> float: ...


class WorldPopRasters:
    """The downloaded WorldPop R2025A stack and Global1 totals (manage.py load_worldpop)."""

    release = worldpop.RELEASE
    dataset = "worldpop-r2025a"
    history_release = worldpop.HISTORY_RELEASE
    history_dataset = "worldpop-global1"

    def years(self):
        return worldpop.available_years()

    def history_years(self):
        return worldpop.available_history_years()

    def _window(self, west, south, east, north, path):
        import rasterio
        from rasterio.windows import from_bounds

        with rasterio.open(path) as src:
            window = from_bounds(west, south, east, north, src.transform).round_offsets()
            window = window.round_lengths()
            data = src.read(window=window, masked=True, boundless=True, fill_value=src.nodata)
            transform = src.window_transform(window)
        values = np.ma.filled(data.astype("float64"), 0.0)
        values[values < 0] = 0.0
        return values, transform

    def _sums(self, geom, path):
        """Per-band sums of the cells whose centre falls inside the geometry."""
        from rasterio.features import geometry_mask

        values, transform = self._window(*geom.extent, path)
        inside = geometry_mask(
            [json.loads(geom.json)], out_shape=values.shape[1:], transform=transform, invert=True
        )
        return values[:, inside].sum(axis=1).tolist()

    def age_sex(self, geom, year):
        sums = self._sums(geom, worldpop.vrt_path(year))
        half = len(worldpop.AGES)
        return AgeSex(sums[:half], sums[half:])

    def history_total(self, geom, year):
        return float(self._sums(geom, worldpop.history_path(year))[0])

    def density(self, west, south, east, north, year):
        """People per km² on the 100 m grid, for maps."""
        from .providers import Grid

        values, transform = self._window(west, south, east, north, worldpop.vrt_path(year))
        lat = (south + north) / 2
        cell_km2 = (abs(transform.a) * 111.32 * np.cos(np.radians(lat))) * (
            abs(transform.e) * 110.574
        )
        return Grid((values.sum(axis=0) / cell_km2).astype("float32"), transform)


def population_provider() -> PopulationProvider:
    return WorldPopRasters()


def geometry_key(geom, dataset, release, year):
    digest = hashlib.sha1(bytes(geom.ewkb)).hexdigest()
    return f"{dataset}:{release}:{year}:{digest}"


def cached_age_sex(provider, geom, year):
    """AgeSex for a geometry and year, from the cache when it was computed before."""
    from .models import PopulationStat

    key = geometry_key(geom, provider.dataset, provider.release, year)
    cached = PopulationStat.objects.filter(key=key).first()
    if cached:
        return AgeSex.from_json(cached.values)
    stats = provider.age_sex(geom, year)
    PopulationStat.objects.update_or_create(
        key=key,
        defaults={"release": provider.release, "year": year, "values": stats.as_json()},
    )
    return stats


def cached_total(dataset, release, geom, year, compute):
    """A population total for a geometry and year, from the cache when computed before."""
    from .models import PopulationStat

    key = geometry_key(geom, dataset, release, year)
    cached = PopulationStat.objects.filter(key=key).first()
    if cached:
        return cached.values["total"]
    total = compute()
    PopulationStat.objects.update_or_create(
        key=key, defaults={"release": release, "year": year, "values": {"total": total}}
    )
    return total
