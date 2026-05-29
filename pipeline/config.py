from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
GRID_DIR = DATA_DIR / "grid"
FORECAST_DIR = DATA_DIR / "forecasts"

LOCATION = {"name": "Bratislava", "lat": 48.162891146409, "lon": 17.136906864798476}

VARIABLES = {
    "TOT_PREC": {
        "grib_var": "tp",
        "is_accumulated": True,
        "step_minutes": 15,
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
        "grib_var": "2t",         # eccodes shortName; cfVarName is "t2m"
        "is_accumulated": False,
        "step_minutes": 60,
        "unit": "°C",
        "offset": -273.15,         # GRIB values are Kelvin; shift to Celsius
        "thresholds": [0.0, 10.0, 20.0, 30.0],
    },
}

PERCENTILES = [10, 25, 50, 75, 90]

# Retain only the newest N forecast JSONs in data/forecasts/. Older files
# (and their GRIB inputs in data/raw/) are pruned after each run. This must
# stay >= the backfill window the workflow requests (main.py --runs N --backfill)
# and the cleanup --keep-last value, or backfilled runs get pruned and
# re-downloaded next run. It also bounds how many runs the dashboard shows.
FORECAST_RETAIN = 12

DWD_BASE = "https://opendata.dwd.de/weather/nwp/v1/m/icon-d2-ruc-eps/p"
GRID_URL = "https://opendata.dwd.de/weather/lib/cdo/icon_grid_0047_R19B07_L.nc.bz2"
GRID_FILE = GRID_DIR / "icon_grid_0047_R19B07_L.nc"
KDTREE_CACHE = GRID_DIR / "kdtree.pkl"

MAX_CONCURRENT_DOWNLOADS = 20
DOWNLOAD_TIMEOUT_SECONDS = 120
HTTP_USER_AGENT = "icon-ruc/2.0"


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, GRID_DIR, FORECAST_DIR):
        d.mkdir(parents=True, exist_ok=True)
