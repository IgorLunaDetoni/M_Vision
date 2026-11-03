import asyncio
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from app import create_server
from mvision.ais import collect, normalize, parse_boxes, vessel_type
from mvision.demo import demo_vessels
from mvision.store import VesselStore


def position(**fields):
    return {"MessageType": "PositionReport", "MetaData": {"MMSI": 123456789, "ShipName": "TEST SHIP@@"},
            "Message": {"PositionReport": {"Latitude": -23.5, "Longitude": -43.1, "Sog": 12.3,
                                          "Cog": 123.4, "TrueHeading": 124, "Valid": True, **fields}}}


def static(**fields):
    return {"MessageType": "ShipStaticData", "MetaData": {"MMSI": 123456789},
            "Message": {"ShipStaticData": {"Name": "NEW NAME@@", "Type": 80, "ImoNumber": 9876543,
                                          "Destination": "SANTOS@@", "Dimension": {"A": 200, "B": 80, "C": 20, "D": 20}, **fields}}}


class NormalizationTests(unittest.TestCase):
    def test_position_coordinates_and_identifiers(self):
        item = normalize(position())
        self.assertEqual(item["mmsi"], "123456789")
        self.assertEqual(item["name"], "TEST SHIP")
        self.assertEqual(item["speed"], 12.3)
        self.assertEqual(item["longitude"], -43.1)

    def test_ais_unavailable_values(self):
        item = normalize(position(Sog=102.3, Cog=360, TrueHeading=511))
        self.assertIsNone(item["speed"])
        self.assertIsNone(item["course"])
        self.assertIsNone(item["heading"])
        for invalid in ({"Latitude": 91}, {"Longitude": 181}, {"Latitude": float("nan")}, {"Longitude": True}, {"Valid": False}):
            self.assertIsNone(normalize(position(**invalid)))

    def test_zero_coordinates_and_zero_speed_are_valid(self):
        item = normalize(position(Latitude=0, Longitude=0, Sog=0, Cog=0, TrueHeading=0))
        self.assertEqual((item["latitude"], item["longitude"], item["speed"]), (0, 0, 0))

    def test_static_data_does_not_fabricate_position(self):
        item = normalize(static())
        self.assertEqual(item["length"], 280)
        self.assertEqual(item["width"], 40)
        self.assertEqual(item["type"], "tanker")
        self.assertEqual(item["destination"], "SANTOS")
        self.assertNotIn("latitude", item)
        self.assertNotIn("updated_at", item)

    def test_class_b_reports(self):
        for kind in ("StandardClassBPositionReport", "ExtendedClassBPositionReport"):
            message = position()
            message["Message"][kind] = message["Message"].pop("PositionReport")
            message["MessageType"] = kind
            self.assertEqual(normalize(message)["speed"], 12.3)

    def test_type_mapping_does_not_guess_subtypes(self):
        self.assertEqual(vessel_type(89), "tanker")
        self.assertEqual(vessel_type(70), "cargo")
        self.assertEqual(vessel_type(79), "cargo")
        self.assertEqual(vessel_type(0), "unknown")

    def test_malformed_and_control_packets(self):
        for message in (None, [], {}, {"error": "denied"}, {"MessageType": "SubscriptionConfirmation"},
                        {"MessageType": "PositionReport", "Message": []}):
            self.assertIsNone(normalize(message))
        message = position()
        message["MetaData"]["MMSI"] = 0
        self.assertIsNone(normalize(message))

    def test_boxes_validation(self):
        self.assertEqual(parse_boxes('[[[-90,-180],[90,180]]]'), [[[-90, -180], [90, 180]]])
        for raw in ('[]', '{}', '[[[91,0],[0,0]]]', '[[[0,0]]]', '[[[true,0],[0,0]]]'):
            with self.assertRaises(ValueError):
                parse_boxes(raw)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "vessels.sqlite3"
        self.store = VesselStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_static_and_position_merge_in_both_orders(self):
        for updates in ((normalize(static()), normalize(position())), (normalize(position()), normalize(static()))):
            for update in updates:
                self.store.upsert(update)
            rows, count = self.store.snapshot()
            self.assertEqual(count, 1)
            self.assertEqual(rows[0]["length"], 280)
            self.assertEqual(rows[0]["latitude"], -23.5)

    def test_persistence_after_restart(self):
        self.store.upsert(normalize(position()))
        self.store.close()
        self.store = VesselStore(self.path)
        self.assertEqual(self.store.snapshot()[1], 1)

    def test_static_packets_do_not_rejuvenate_old_positions(self):
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        self.store.upsert(normalize(position(), old))
        self.store.upsert(normalize(static()))
        self.assertEqual(self.store.snapshot()[1], 0)

    def test_static_only_not_plotted_and_truncation_is_reported(self):
        self.store.upsert(normalize(static()))
        self.assertEqual(self.store.snapshot()[1], 0)
        self.store.upsert(normalize(position()))
        other = normalize(position())
        other["mmsi"] = "987654321"
        other["object_id"] = "987654321"
        self.store.upsert(other)
        rows, total = self.store.snapshot(limit=1)
        self.assertEqual((len(rows), total), (1, 2))


class HTTPTests(unittest.TestCase):
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

    def test_demo_api_and_static_assets(self):
        with urlopen(self.base + "/api/vessels") as response:
            payload = json.load(response)
        self.assertEqual(payload["source"], "demo")
        self.assertEqual(len(payload["vessels"]), 36)
        self.assertTrue(all(v["mmsi"].startswith("DEMO-") for v in payload["vessels"]))
        for asset in ("/", "/styles.css", "/app.js"):
            with urlopen(self.base + asset) as response:
                self.assertEqual(response.status, 200)
                self.assertNotIn("AISSTREAM_API_KEY", response.read().decode())

    def test_server_files_cannot_be_read(self):
        for path in ("/app.py", "/.env", "/../app.py", "/%2e%2e/app.py", "/%2e%2e%5capp.py", "/data/vessels.sqlite3"):
            with self.assertRaises(HTTPError) as ctx:
                urlopen(self.base + path)
            self.assertEqual(ctx.exception.code, 404)


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscription_and_ingestion_without_exposing_key(self):
        class Store:
            connection = "connecting"
            updates = []
            def set_connection(self, value):
                self.connection = value
            def ingest(self, source, packet, updates, received_at):
                self.updates.extend(updates)

        class Socket:
            sent = None
            def __init__(self):
                self.frames = iter([b'{"MessageType":"SubscriptionConfirmation"}', b'bad json', json.dumps(position()).encode()])
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                return False
            async def send(self, value):
                self.sent = json.loads(value)
            def __aiter__(self):
                return self
            async def __anext__(self):
                try:
                    return next(self.frames)
                except StopIteration:
                    raise asyncio.CancelledError

        store, socket = Store(), Socket()
        def connect(url, **options):
            self.assertEqual(url, "wss://stream.aisstream.io/v0/stream")
            self.assertEqual(options["compression"], "deflate")
            return socket
        with self.assertRaises(asyncio.CancelledError):
            await collect(store, "test-secret", [[[-90, -180], [90, 180]]], connect)
        self.assertEqual(socket.sent["APIKey"], "test-secret")
        self.assertEqual(store.connection, "connected")
        self.assertEqual(len(store.updates), 1)
        self.assertNotIn("test-secret", json.dumps(store.updates))


if __name__ == "__main__":
    unittest.main()
