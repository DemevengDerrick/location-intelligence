"""WorldPop rasters for Cameroon (CC BY 4.0), downloaded once.

R2025A age-sex structures: per year (2015, 2020, 2025, 2030; 2030 is a projection) there are
20 female and 20 male bands at 100 m: ages 0, 1–4, 5–9, ... 85–89 and 90+. Each file is
converted to a COG and the 40 are stacked in one VRT per year, so a zonal read touches one
dataset. Population totals are the sum of the bands, so age-sex figures always add up to the
total.

R2025A starts in 2015. Earlier years (2000, 2005, 2010) come from the older Global1 release:
totals only, one unconstrained 100 m raster per year. Global1 spreads people over all land,
not only built-up cells, so its figures are history for context and are not compared with
R2025A figures in growth rates.
"""

import logging
import subprocess
from pathlib import Path

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

RELEASE = "R2025A"
YEARS = (2015, 2020, 2025, 2030)
PROJECTED_FROM = 2026  # years from here on are projections in R2025A
AGES = ("00", "01", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60",
        "65", "70", "75", "80", "85", "90")  # fmt: skip
SEXES = ("f", "m")
BASE = "https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A"
HISTORY_RELEASE = "Global1"
HISTORY_YEARS = (2000, 2005, 2010)
HISTORY_BASE = "https://data.worldpop.org/GIS/Population/Global_2000_2020"


def band_names():
    """Band order in each year's VRT: f_00 ... f_90, then m_00 ... m_90."""
    return [f"{sex}_{age}" for sex in SEXES for age in AGES]


def file_name(sex, age, year):
    return f"cmr_{sex}_{age}_{year}_CN_100m_{RELEASE}_v1.tif"


def url(sex, age, year):
    return f"{BASE}/{year}/CMR/v1/100m/constrained/{file_name(sex, age, year)}"


def history_url(year):
    return f"{HISTORY_BASE}/{year}/CMR/cmr_ppp_{year}.tif"


def data_dir():
    return Path(settings.WORLDPOP_DATA_DIR)


def vrt_path(year):
    return data_dir() / f"cmr_agesex_{year}_{RELEASE}.vrt"


def history_path(year):
    return data_dir() / "global1" / f"cmr_ppp_{year}_{HISTORY_RELEASE}_cog.tif"


def available_years():
    return [year for year in YEARS if vrt_path(year).exists()]


def available_history_years():
    return [year for year in HISTORY_YEARS if history_path(year).exists()]


def _download(source, target, client):
    partial = target.with_suffix(".part")
    with client.stream("GET", source) as response:
        response.raise_for_status()
        with partial.open("wb") as out:
            for chunk in response.iter_bytes():
                out.write(chunk)
    partial.replace(target)


def _fetch_cog(source, cog, client):
    """Download `source` and convert it to `cog`, unless that was done before."""
    if cog.exists():
        return False
    raw = cog.with_name(cog.name.replace("_cog.tif", ".tif"))
    for attempt in range(3):
        try:
            _download(source, raw, client)
            break
        except httpx.TransportError:
            if attempt == 2:
                raise
    partial = cog.with_suffix(".part.tif")
    subprocess.run(
        ["gdal_translate", "-q", "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=YES",
         "-co", "OVERVIEWS=NONE", str(raw), str(partial)],
        check=True,
    )  # fmt: skip
    partial.replace(cog)
    raw.unlink()
    return True


def _prepare(year, sex, age, client, log):
    cog = data_dir() / str(year) / file_name(sex, age, year).replace(".tif", "_cog.tif")
    if _fetch_cog(url(sex, age, year), cog, client):
        log(f"{year} {sex} {age}: ready")
    return cog


def _client():
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=180))


def load_history(years=HISTORY_YEARS, client=None, log=logger.info):
    """Download the Global1 totals for the years before 2015 (one file per year)."""
    client = client or _client()
    (data_dir() / "global1").mkdir(parents=True, exist_ok=True)
    for year in years:
        if _fetch_cog(history_url(year), history_path(year), client):
            log(f"{year} ({HISTORY_RELEASE} totals): ready")


def load(years=YEARS, client=None, log=logger.info, workers=4):
    """Download, convert to COG (no overviews: reads are full-resolution windows) and stack.
    Files already converted are skipped, so an interrupted load can simply be re-run."""
    from concurrent.futures import ThreadPoolExecutor

    client = client or _client()
    for year in years:
        (data_dir() / str(year)).mkdir(parents=True, exist_ok=True)
        jobs = [(year, sex, age) for sex in SEXES for age in AGES]
        with ThreadPoolExecutor(workers) as pool:
            cogs = list(pool.map(lambda job: _prepare(*job, client, log), jobs))
        subprocess.run(
            ["gdalbuildvrt", "-q", "-separate", "-overwrite", str(vrt_path(year)),
             *[str(c) for c in cogs]],
            check=True,
        )  # fmt: skip
        log(f"{year}: stacked in {vrt_path(year).name}")
