from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
GRID_DIR = DATA_DIR / "grid"
FORECAST_DIR = DATA_DIR / "forecasts"

LOCATIONS = {
    "bratislava": {
        "name": "Bratislava",
        "lat": 48.162891146409,
        "lon": 17.136906864798476,
    },
    "pohoda": {
        "name": "Pohoda",
        "lat": 48.8654,
        "lon": 17.9997,
    },
    "uprising": {
        "name": "Uprising — Zlaté piesky",
        "lat": 48.186,
        "lon": 17.187,
    },
}

VARIABLES = {
    "TOT_PREC": {
        "grib_var": "tp",
        "is_accumulated": True,
        "step_minutes": 5,
        "unit": "mm/h",
        "thresholds": [0.1, 1.0, 5.0, 10.0],
    },
    "VMAX_10M": {
        "grib_var": "max_i10fg",  # eccodes shortName; cfVarName is "fg10"
        "is_accumulated": False,
        "step_minutes": 60,
        "unit": "m/s",
        "thresholds": [5.0, 10.0, 15.0, 20.0],
        "skip_first_step": True,  # Model reports 0 at t=0; drop it.
    },
    "T_2M": {
        "grib_var": "2t",  # eccodes shortName; cfVarName is "t2m"
        "is_accumulated": False,
        "step_minutes": 60,
        "unit": "°C",
        "offset": -273.15,  # GRIB values are Kelvin; shift to Celsius
        "thresholds": [0.0, 10.0, 20.0, 30.0],
    },
    # 10 m wind components — inputs to the derived WIND_10M (sustained wind
    # speed) only. `internal` variables are downloaded and extracted like any
    # other, but are never written to the forecast JSON: the vector components
    # alone carry no dashboard meaning.
    "U_10M": {
        "grib_var": "10u",  # eccodes shortName; 10 m U wind component
        "is_accumulated": False,
        "step_minutes": 60,
        "unit": "m/s",
        "thresholds": [],
        "internal": True,
    },
    "V_10M": {
        "grib_var": "10v",  # eccodes shortName; 10 m V wind component
        "is_accumulated": False,
        "step_minutes": 60,
        "unit": "m/s",
        "thresholds": [],
        "internal": True,
    },
}

# Derived variables computed from source VARIABLES per ensemble member BEFORE
# percentiles (so the ensemble's directional spread survives) — see
# run._magnitude_series. WIND_10M = |(U_10M, V_10M)| is the sustained 10 m
# wind speed, the counterpart to the VMAX_10M hourly-max gust (the model gust
# naturally sits above sustained wind, as observed gusts sit above observed
# sustained wind).
DERIVED_VARIABLES = {
    "WIND_10M": {
        "sources": ("U_10M", "V_10M"),
        "is_accumulated": False,
        "unit": "m/s",
        "thresholds": [3.0, 5.0, 8.0, 12.0],
    },
}

PERCENTILES = [10, 25, 50, 75, 90]

# Retain only the newest N forecast JSONs in data/forecasts/. Older files
# (and their GRIB inputs in data/raw/) are pruned after each run. This must
# stay >= the backfill window the workflow requests (main.py --runs N --backfill)
# and the cleanup --keep-last value, or backfilled runs get pruned and
# re-downloaded next run. It also bounds how many runs the dashboard shows.
FORECAST_RETAIN = 12

# DWD sources in priority order. discover.active_source() probes each run
# index at process start and uses the first that answers with runs, so an
# outage of the 20-member ensemble (as happened 2026-07-02 → 2026-07-04)
# degrades automatically to its deterministic sibling — same URL/file layout
# minus the e/{ensemble}/ segment — instead of breaking the pipeline. With
# one member, percentiles/probability_exceeds collapse to that member's value
# and the dashboard shows a SINGLE-MEMBER badge.
DWD_SOURCES = (
    {
        "name": "icon-d2-ruc-eps",
        "base": "https://opendata.dwd.de/weather/nwp/v1/m/icon-d2-ruc-eps/p",
        "has_ensemble": True,
    },
    {
        "name": "icon-d2-ruc",
        "base": "https://opendata.dwd.de/weather/nwp/v1/m/icon-d2-ruc/p",
        "has_ensemble": False,
    },
)
GRID_URL = "https://opendata.dwd.de/weather/lib/cdo/icon_grid_0047_R19B07_L.nc.bz2"
GRID_FILE = GRID_DIR / "icon_grid_0047_R19B07_L.nc"
KDTREE_CACHE = GRID_DIR / "kdtree.pkl"

MAX_CONCURRENT_DOWNLOADS = 20
DOWNLOAD_TIMEOUT_SECONDS = 120
HTTP_USER_AGENT = "icon-ruc/2.0"

# icon-d2-ruc-eps runs to a ~27 h horizon; treat a run as fully uploaded once
# DWD's index reaches this many lead-time minutes (conservative: slightly
# below the true max so we don't wait for the last handful of files).
EXPECTED_FORECAST_MINUTES = 800


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, GRID_DIR, FORECAST_DIR):
        d.mkdir(parents=True, exist_ok=True)
