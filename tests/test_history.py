import csv
import gzip
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

from app import create_server
from mvision.aircraft import OpenSkyClient, collect_aircraft, normalize_state
from mvision.ais import normalize
from mvision.exports import export_data
from mvision.store import VesselStore, stamp
from test_core import position, static


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "index.sqlite3"
        self.store = VesselStore(self.path)
        self.now = datetime.now(timezone.utc) - timedelta(seconds=2)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ingest(self, packet, when):
        return self.store.ingest("aisstream", packet, [normalize(packet, stamp(when))], when)

    def test_raw_processed_link_and_restart(self):
        packet = position()
        raw_id = self.ingest(packet, self.now)
        self.store.flush()
        raw_file = next((self.root / "brutos").rglob("*.jsonl"))
        raw = json.loads(raw_file.read_text(encoding="utf-8"))
        self.assertEqual(raw["payload"], packet)
        self.assertEqual(raw["raw_id"], raw_id)
        processed_file = next((self.root / "tratados").rglob("*.csv"))
        with processed_file.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(rows[0]["raw_id"], raw_id)
        self.assertEqual(rows[0]["object_type"], "vessel")
        self.store.close()
        self.store = VesselStore(self.path)
        self.assertEqual(self.store.snapshot()[1], 1)
        self.assertEqual(self.store.snapshot()[0][0]["position_collected_at"], stamp(self.now))

    def test_static_update_keeps_position_provenance_for_raw_snapshot(self):
        position_id = self.ingest(position(), self.now - timedelta(minutes=1))
        static_id = self.ingest(static(), self.now)
        records = self.store.snapshot()[0]
        self.assertEqual(records[0]["position_raw_id"], position_id)
        self.assertEqual(records[0]["raw_id"], static_id)
        self.assertEqual({row["raw_id"] for row in self.store.raw_for_records(records, include_positions=True)}, {position_id, static_id})

    def test_archive_keeps_recent_static_metadata_until_first_position(self):
        self.ingest(static(), self.now - timedelta(minutes=1))
        self.store.archive()
        self.ingest(position(), self.now)
        self.assertEqual(self.store.snapshot()[0][0]["length"], 280)

    def test_history_has_no_future_positions_or_future_metadata(self):
        first = self.now - timedelta(hours=2)
        self.ingest(position(Latitude=-24), first)
        self.ingest(static(Name="FUTURE NAME"), first + timedelta(minutes=20))
        self.ingest(position(Latitude=-25), first + timedelta(hours=1))
        early = self.store.snapshot(at=first + timedelta(minutes=10))[0][0]
        middle = self.store.snapshot(at=first + timedelta(minutes=30))[0][0]
        self.assertEqual(early["latitude"], -24)
        self.assertEqual(early["name"], "TEST SHIP")
        self.assertEqual(middle["name"], "FUTURE NAME")
        self.assertEqual(middle["updated_at"], stamp(first))
        self.assertEqual(self.store.snapshot()[0][0]["latitude"], -25)

    def test_late_position_does_not_replace_newer_coordinates(self):
        self.ingest(position(Latitude=-24), self.now - timedelta(minutes=1))
        packet = position(Latitude=-25)
        update = normalize(packet, stamp(self.now - timedelta(minutes=5)))
        self.store.ingest("aisstream", packet, [update], self.now)
        self.assertEqual(self.store.snapshot()[0][0]["latitude"], -24)

    def test_archival_preserves_original_bytes_and_removes_query_index(self):
        old = self.now - timedelta(days=32)
        self.ingest(position(), old)
        self.ingest(position(Latitude=-26), self.now)
        self.store.flush()
        old_path = self.root / "brutos" / "aisstream" / (stamp(old)[:10] + ".jsonl")
        original = old_path.read_bytes()
        self.assertEqual(self.store.archive(), 2)
        compressed = self.root / "historico" / "brutos" / "aisstream" / (old_path.name + ".gz")
        self.assertEqual(gzip.decompress(compressed.read_bytes()), original)
        self.assertFalse(old_path.exists())
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM packets").fetchone()[0], 1)
        self.assertEqual(self.store.snapshot()[0][0]["latitude"], -26)
        self.assertEqual(self.store.archive(), 0)

    def test_archival_failure_keeps_active_files_and_database(self):
        self.ingest(position(), self.now - timedelta(days=32))
        self.store.flush()
        with patch("mvision.store.gzip.open", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.archive()
        self.assertTrue(list((self.root / "brutos").rglob("*.jsonl")))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM packets").fetchone()[0], 1)

    def test_missing_journal_does_not_delete_the_only_remaining_copy(self):
        self.ingest(position(), self.now - timedelta(days=32))
        self.store.flush()
        old_file = next((self.root / "brutos").rglob("*.jsonl"))
        # Simulate external removal without actually deleting the fixture.
        old_file.rename(old_file.with_suffix(".missing"))
        with self.assertRaises(OSError):
            self.store.archive()
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM packets").fetchone()[0], 1)

    def test_interrupted_append_is_recovered_without_duplicate_records(self):
        self.ingest(position(), self.now)
        with patch("mvision.store.os.fsync", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.store.flush()
        self.store.flush()
        raw = next((self.root / "brutos").rglob("*.jsonl")).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw), 1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)

    def test_filtered_history_and_antimeridian(self):
        self.ingest(position(Longitude=179), self.now - timedelta(minutes=5))
        self.ingest(position(Longitude=-179), self.now)
        filters = {"bounds": [-30, 170, -20, -170], "source": "aisstream", "object_type": "vessel"}
        rows = self.store.history(self.now - timedelta(hours=1), self.now, filters)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.store.history(self.now - timedelta(hours=1), self.now, {"q": "absent"})), 0)
        packets = self.store.history(self.now - timedelta(hours=1), self.now, filters, raw=True)
        self.assertEqual(packets[0]["matched_object_ids"], ["123456789"])

    def test_source_ids_cannot_escape_storage_root(self):
        with self.assertRaises(ValueError):
            self.store.ingest("../../public", {}, [], self.now)

    def test_legacy_database_is_imported_once_without_fabricating_raw_data(self):
        self.store.close()
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE vessels (mmsi TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO vessels VALUES (?, ?)", ("123456789", json.dumps(normalize(position()))))
        db.commit()
        db.close()
        self.store = VesselStore(self.path)
        count = self.store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        self.assertEqual(self.store.snapshot()[1], 1)
        raw = json.loads(self.store.db.execute("SELECT payload FROM packets LIMIT 1").fetchone()[0])
        self.assertTrue(raw["payload"]["normalized_only"])
        self.store.close()
        self.store = VesselStore(self.path)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], count)


class AircraftAndExportTests(unittest.TestCase):
    def test_oauth_tokens_are_cached_and_never_ingested_as_telemetry(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            packet = {"access_token": "fake-token", "expires_in": 1800} if request.data else {"time": 1, "states": []}
            return io.BytesIO(json.dumps(packet).encode())
        client = OpenSkyClient("fake-client", "fake-secret", opener)
        self.assertEqual(client.fetch(), {"time": 1, "states": []})
        self.assertEqual(client.fetch(), {"time": 1, "states": []})
        self.assertEqual(len([request for request in calls if request.data]), 1)
        self.assertEqual(calls[1].headers["Authorization"], "Bearer fake-token")
        class Stop:
            def __init__(self):
                self.stopped = False
            def is_set(self):
                return self.stopped
            def wait(self, interval):
                self.stopped = True
        class Store:
            def __init__(self):
                self.packets = []
            def set_connection(self, *_args):
                pass
            def ingest(self, source, packet, updates, received_at):
                self.packets.append(packet)
        store = Store()
        collect_aircraft(store, client, Stop())
        self.assertEqual(store.packets, [{"time": 1, "states": []}])
        self.assertNotIn("fake-secret", json.dumps(store.packets))
        self.assertNotIn("fake-token", json.dumps(store.packets))

    def test_aircraft_units_and_source_position_time(self):
        now = datetime.now(timezone.utc)
        row = ["abc123", "TEST123 ", "Brazil", now.timestamp()-30, now.timestamp(), -43.1, -23.5, 10000,
               False, 100, 90, 0, None, 10020, "1200", False, 0]
        item = normalize_state(row, now)
        self.assertAlmostEqual(item["speed"], 194.384449244)
        self.assertEqual(item["name"], "TEST123")
        self.assertEqual(item["object_type"], "aircraft")
        self.assertEqual(item["updated_at"], stamp(datetime.fromtimestamp(row[3], timezone.utc)))
        row[3] = None
        self.assertIsNone(normalize_state(row, now))

    def test_csv_and_xlsx_are_readable_and_text_stays_text(self):
        rows = [{"object_id": "123456789", "name": "=HYPERLINK(\"bad\")", "latitude": -23.5, "longitude": 0}]
        body, _ = export_data(rows)
        csv_rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig")), delimiter=";"))
        self.assertTrue(csv_rows[0]["name"].startswith("'="))
        body, _ = export_data(rows, "xlsx")
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            for name in archive.namelist():
                ElementTree.fromstring(archive.read(name))
            sheet = archive.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn('t="inlineStr"', sheet)
            self.assertNotIn("<f>", sheet)
            self.assertIn("-23.5", sheet)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def get(self, path, **params):
        return urlopen(self.base + path + "?" + urlencode(params))

    def test_combined_map_and_layer_filters(self):
        with self.get("/api/objects") as response:
            data = json.load(response)
        self.assertEqual(data["total"], 42)
        self.assertEqual(data["refresh_seconds"], 300)
        with self.get("/api/objects", object_type="aircraft") as response:
            data = json.load(response)
        self.assertEqual(data["total"], 6)
        with self.get("/api/objects", bounds="-30,-50,-20,-40", object_type="vessel") as response:
            data = json.load(response)
        self.assertTrue(data["objects"])
        self.assertTrue(all(-30 <= item["latitude"] <= -20 for item in data["objects"]))

    def test_exports_apply_filters_and_create_local_files(self):
        with self.get("/api/export", format="csv", object_type="aircraft", q="DEMO AIR 01") as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig")), delimiter=";"))
            name = response.headers["Content-Disposition"].split('"')[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object_type"], "aircraft")
        self.assertTrue((self.server.data_root / "exportacoes" / name).exists())
        with self.get("/api/export", format="xlsx", dataset="raw", q="DEMO AIR 01") as response:
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                self.assertIn("xl/workbook.xml", archive.namelist())
        with self.get("/api/export", dataset="raw", object_type="aircraft", q="DEMO AIR 01") as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig")), delimiter=";"))
        packet = json.loads(rows[0]["payload"])
        self.assertEqual(packet["vessels"], [])
        self.assertEqual(len(packet["aircraft"]), 1)

    def test_period_export_and_trajectory_have_collected_records(self):
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=10)
        with self.get("/api/export", start=stamp(start), end=stamp(end), object_type="aircraft") as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(rows), 6)
        with self.get("/api/trajectory", object_id="DEMO-AIR-001", source="demo") as response:
            self.assertEqual(len(json.load(response)["points"]), 1)

    def test_favorites_filter_is_qualified_by_source(self):
        with self.get("/api/objects", keys="demo:DEMO-AIR-001") as response:
            self.assertEqual(json.load(response)["total"], 1)
        with self.get("/api/export", keys="opensky:DEMO-AIR-001") as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(rows, [])

    def test_invalid_dates_bounds_formats_and_trajectory_are_rejected(self):
        for path, params in [("/api/objects", {"at": "2020-01-01T00:00:00Z"}),
                             ("/api/objects", {"at": "2026-10-07T12:00:00"}),
                             ("/api/objects", {"bounds": "nan,0,1,2"}),
                             ("/api/export", {"format": "../bad"}),
                             ("/api/export", {"start": "2020-01-01T00:00:00Z"}),
                             ("/api/trajectory", {"object_id": "x", "hours": "-1"})]:
            with self.assertRaises(HTTPError) as ctx:
                self.get(path, **params)
            self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
