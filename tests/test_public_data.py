"""Offline tests for the public dataset download and normalization tools."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from domestic_energy.dataset_hub import (
    SOURCES, fetch, number, opsd, uci, utc_local_time, watts, write_intervals,
)


class PublicDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def file(self, name, data):
        path = self.root / name
        path.write_text(data, encoding="utf-8")
        return path

    def test_source_catalog_publisher_urls(self):
        self.assertTrue({"lcl","uci","opsd-hourly","opsd-quarterhour","refit-house1","ideal","ukdale"}.issubset(SOURCES))
        self.assertTrue(SOURCES["opsd-hourly"]["url"].startswith("https://"))
        self.assertIsNone(SOURCES["ideal"]["url"])

    def test_reject_nonfinite_negative(self):
        for value in ("nan", "", "Null", "?"):
            self.assertIsNone(number(value))
        for value in ("-1", "Infinity", "3e999"):
            with self.assertRaises(ValueError):
                number(value)

    def test_dst_ambiguous_and_nonexistent(self):
        self.assertIsNone(utc_local_time(datetime(2016, 10, 30, 2, 30), "Europe/Paris"))
        self.assertIsNone(utc_local_time(datetime(2016, 3, 27, 2, 30), "Europe/Paris"))
        self.assertEqual(utc_local_time(datetime(2016, 1, 1, 12), "Europe/Paris").hour, 11)

    def test_opsd_interval_and_labels(self):
        path = self.file("opsd.csv", 
            "utc_timestamp,DE_KN_residential4_grid_import,DE_KN_residential4_heat_pump,DE_KN_residential4_ev,DE_KN_residential4_pv\n"
            "2020-01-01T00:00:00Z,1.5,0.5,0.25,0\n"
            "2020-01-01T01:00:00Z,2.2,0.3,0,1.2\n")
        rows = list(opsd(path, "residential4", 60, "interval"))
        self.assertEqual([x["consumption_kwh"] for x in rows], [1.5, 2.2])
        self.assertEqual(rows[0]["ev_kwh"], .25)
        self.assertEqual(rows[1]["pv_kwh"], 1.2)

    def test_opsd_counter_differences_and_no_negative_reset(self):
        path = self.file("counter.csv",
            "utc_timestamp,DE_KN_residential4_grid_import,DE_KN_residential4_ev\n"
            "2016-01-01T00:00:00Z,100,30\n"
            "2016-01-01T00:15:00Z,101,30.5\n"
            "2016-01-01T00:30:00Z,0,1\n"
            "2016-01-01T00:45:00Z,0.6,1.2\n")
        rows = list(opsd(path, "residential4", 15, "counter"))
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["consumption_kwh"], 1)
        self.assertAlmostEqual(rows[0]["ev_kwh"], .5)
        self.assertAlmostEqual(rows[1]["consumption_kwh"], .6)

    def test_opsd_counter_never_invents_gap(self):
        path = self.file("gap.csv", "utc_timestamp,DE_KN_residential4_grid_import\n"
            "2016-01-01T00:00:00Z,10\n"
            "2016-01-01T01:00:00Z,11\n"
            "2016-01-01T01:15:00Z,12\n")
        self.assertEqual(len(list(opsd(path, "residential4", 15, "counter"))), 1)

    def test_uci_requires_complete_bin(self):
        base = datetime(2006, 12, 16, 17, 0)
        txt = "Date;Time;Global_active_power\n"
        for n in range(30):
            dt = base + timedelta(minutes=n)
            txt += dt.strftime("%d/%m/%Y;%H:%M:%S;2.0\n")
        path = self.file("uci.txt", txt)
        rows = list(uci(path, 30))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["consumption_kwh"], 1.0)
        self.assertEqual(rows[0]["start_utc"], "2006-12-16T16:00:00+00:00")

    def test_uci_partial_bin_not_zero_filled(self):
        base = datetime(2006, 12, 16, 17, 0)
        txt = "Date;Time;Global_active_power\n"
        for n in range(29):
            dt = base + timedelta(minutes=n)
            txt += dt.strftime("%d/%m/%Y;%H:%M:%S;2.0\n")
        self.assertEqual(list(uci(self.file("partial.txt", txt), 30)), [])

    def test_refit_watts_integrated_time(self):
        source = self.file("watts.csv", "Unix,Aggregate\n"
            + "\n".join(f"{int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())+n*8},1000"
                        for n in range(226)) + "\n")
        rows = list(watts(source, 30, max_gap=16))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["consumption_kwh"], .5)

    def test_watts_large_gap_does_not_fill(self):
        path = self.file("gapwatts.csv", "Unix,Aggregate\n0,1000\n3600,1000\n")
        self.assertEqual(list(watts(path, 30)), [])

    def test_write_metadata_and_no_overlap(self):
        output = self.root / "converted.csv"
        meta = write_intervals([
            {"start_utc":"2020-01-01T00:00:00+00:00", "consumption_kwh":1.5, "duration_minutes":30},
            {"start_utc":"2020-01-01T00:30:00+00:00", "consumption_kwh":.2, "duration_minutes":30},
        ], output)
        self.assertEqual(meta["interval_count"], 2)
        self.assertAlmostEqual(meta["observed_kwh"], 1.7)
        self.assertEqual(len(list(csv.DictReader(output.open()))), 2)
        self.assertEqual(json.loads(Path(str(output)+".metadata.json").read_text())["interval_count"], 2)
        with self.assertRaises(FileExistsError):
            write_intervals([], output)

    def test_overlap_fails_atomically(self):
        dest = self.root / "bad.csv"
        with self.assertRaises(ValueError):
            write_intervals([
                {"start_utc":"2020-01-01T00:00:00+00:00","consumption_kwh":1,"duration_minutes":30},
                {"start_utc":"2020-01-01T00:15:00+00:00","consumption_kwh":1,"duration_minutes":30},
            ], dest)
        self.assertFalse(dest.exists())

    def test_fetch_size_cap_and_checksum(self):
        class Response:
            headers = {"Content-Length": "3"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def __init__(self): self.calls = 0
            def read(self, n):
                self.calls += 1
                return b"abc" if self.calls == 1 else b""
        path = self.root / "source.zip"
        with patch("domestic_energy.dataset_hub.urllib.request.urlopen", return_value=Response()):
            meta = fetch("uci", path)
        self.assertEqual(meta["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertTrue(path.exists())
        with self.assertRaises(FileExistsError):
            fetch("uci", path)

    def test_reject_large_unapproved_and_manual(self):
        with self.assertRaises(ValueError):
            fetch("refit-house1", self.root / "refit.csv")
        with self.assertRaises(ValueError):
            fetch("ideal", self.root / "ideal.zip")


if __name__ == "__main__":
    unittest.main()
