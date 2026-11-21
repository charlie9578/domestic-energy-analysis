"""Download pinned ERA5 windows for the London and Konstanz-area studies."""
import argparse
from datetime import date, timedelta
from pathlib import Path

from domestic_energy.data import fetch_open_meteo_hourly, write_csv

WINDOWS = {
    "london_era5.csv": (51.5074, -0.1278, date(2012, 10, 11), date(2012, 11, 24)),
    "konstanz_era5.csv": (47.6603, 9.1758, date(2015, 12, 31), date(2017, 1, 1)),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    for filename, (latitude, longitude, start, end) in WINDOWS.items():
        rows = []
        while start <= end:
            chunk_end = min(start + timedelta(days=30), end)
            rows.extend(fetch_open_meteo_hourly(latitude, longitude, str(start), str(chunk_end)))
            start = chunk_end + timedelta(days=1)
        write_csv(args.out_dir / filename, rows, list(rows[0]))
        print(f"{filename}: {len(rows)} UTC hours")


if __name__ == "__main__":
    main()
