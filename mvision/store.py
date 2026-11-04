"""Local telemetry journals, a query index and verified archival; no cloud storage."""
import csv
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from mvision.registry import VesselRegistry

UTC = timezone.utc
FIELDS = ["record_id", "raw_id", "object_id", "object_type", "source", "name", "mmsi", "icao24",
          "imo", "callsign", "type", "latitude", "longitude", "speed", "course", "heading",
          "altitude", "length", "width", "status", "destination", "event_at", "collected_at",
          "updated_at", "position_collected_at", "timestamp_basis"]


def instant(value=None):
    if value is None:
        return datetime.now(UTC)
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Informe data e hora com fuso horário.")
    return result.astimezone(UTC)


def stamp(value=None):
    return instant(value).isoformat(timespec="microseconds")


def csv_text(rows, fields=FIELDS, header=False):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    if header:
        writer.writerow(fields)
    for row in rows:
        writer.writerow([row.get(field, "") if row.get(field) is not None else "" for field in fields])
    return buffer.getvalue()


class VesselStore:
    """Common store for vessels and aircraft; name retained for existing integrations.

    SQLite is a local index and durable outbox. Files are appended with committed
    offsets, so an interrupted append is rolled back before it is retried.
    """

    def __init__(self, database, data_root=None, retention_days=30):
        self.lock = threading.RLock()
        database = Path(database)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(data_root or database.parent).resolve()
        self.retention_days = retention_days
        for folder in ("brutos", "tratados", "historico", "exportacoes"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS packets (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, collected_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, raw_id TEXT NOT NULL,
                source TEXT NOT NULL, object_id TEXT NOT NULL, collected_at TEXT NOT NULL,
                position_at TEXT, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS observation_time ON observations(collected_at);
            CREATE INDEX IF NOT EXISTS observation_object ON observations(source, object_id, collected_at DESC, seq DESC);
            CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS file_offsets (path TEXT PRIMARY KEY, size INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS latest_state (
                source TEXT NOT NULL, object_id TEXT NOT NULL, collected_at TEXT NOT NULL,
                position_at TEXT, payload TEXT NOT NULL, PRIMARY KEY(source, object_id));
        """)
        self.db.execute("""INSERT OR IGNORE INTO latest_state
            SELECT source, object_id, collected_at, position_at, payload FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY source, object_id ORDER BY collected_at DESC, seq DESC) AS n
                FROM observations) WHERE n=1""")
        self.db.commit()
        self.connection = "connecting"
        self.connections = {}
        self.storage_error = False
        self.pending = []
        self.vessels = {}
        for row in self.db.execute("SELECT payload FROM latest_state"):
            item = json.loads(row[0])
            self.vessels[(item["source"], item["object_id"])] = item
        self.registry = VesselRegistry(self.db, self.lock)
        with self.db:
            for item in self.vessels.values():
                self.registry.sync(item)
        self._materialize()
        # Import the previous last-position database without inventing raw API responses.
        has_legacy = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vessels'").fetchone()
        migrated = self.db.execute("SELECT 1 FROM settings WHERE key='legacy_imported'").fetchone()
        if has_legacy and not migrated:
            for row in self.db.execute("SELECT payload FROM vessels").fetchall():
                self.upsert(json.loads(row[0]))
            self.flush()
            self.db.execute("INSERT INTO settings VALUES ('legacy_imported', '1')")
            self.db.commit()

    def set_connection(self, value, source="aisstream"):
        with self.lock:
            self.connection = value
            self.connections[source] = value

    def ingest(self, source, packet, updates, received_at=None):
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", source):
            raise ValueError("Identificador de fonte inválido.")
        collected_at = stamp(received_at)
        raw_id = uuid.uuid4().hex
        raw = {"raw_id": raw_id, "source": source, "collected_at": collected_at, "payload": packet}
        raw_body = json.dumps(raw, ensure_ascii=False, allow_nan=False)
        with self.lock:
            records = []
            for update in updates:
                object_id = str(update.get("object_id") or update.get("mmsi") or update.get("icao24") or "")
                if not object_id:
                    continue
                identity = (source, object_id)
                existing = dict(self.vessels.get(identity, {"name": object_id, "type": "unknown", "status": "Não informado"}))
                incoming = dict(update)
                if incoming.get("updated_at"):
                    incoming["updated_at"] = stamp(incoming["updated_at"])
                    if incoming["updated_at"] < existing.get("updated_at", ""):
                        for field in ("latitude", "longitude", "speed", "course", "heading", "altitude", "updated_at", "event_at", "timestamp_basis"):
                            incoming.pop(field, None)
                    else:
                        incoming["position_collected_at"] = collected_at
                        incoming["position_raw_id"] = raw_id
                existing.update(incoming)
                existing.update(object_id=object_id, object_type=update.get("object_type", "vessel"), source=source,
                                collected_at=collected_at, raw_id=raw_id, record_id=uuid.uuid4().hex)
                json.dumps(existing, allow_nan=False)
                self.vessels[identity] = existing
                records.append(existing)
            self.pending.append((raw, raw_body, records))
            if len(self.pending) >= 1000:
                self.flush()
        return raw_id

    def upsert(self, update):
        return self.ingest(update.get("source", "aisstream"),
                           {"normalized_only": True, "update": update}, [update])

    def flush(self):
        with self.lock:
            try:
                with self.db:
                    for raw, raw_body, records in self.pending:
                        day = raw["collected_at"][:10]
                        source = raw["source"]
                        self.db.execute("INSERT INTO packets VALUES (?, ?, ?, ?)",
                                        (raw["raw_id"], source, raw["collected_at"], raw_body))
                        self.db.execute("INSERT INTO outbox(path, body) VALUES (?, ?)",
                                        (f"brutos/{source}/{day}.jsonl", raw_body + "\n"))
                        for record in records:
                            self.registry.sync(record)
                            payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
                            self.db.execute("""INSERT INTO observations
                                (id, raw_id, source, object_id, collected_at, position_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                (record["record_id"], raw["raw_id"], source, record["object_id"], record["collected_at"], record.get("updated_at"), payload))
                            self.db.execute("""INSERT INTO latest_state VALUES (?, ?, ?, ?, ?)
                                ON CONFLICT(source, object_id) DO UPDATE SET collected_at=excluded.collected_at,
                                position_at=excluded.position_at, payload=excluded.payload
                                WHERE excluded.collected_at>=latest_state.collected_at""",
                                (source, record["object_id"], record["collected_at"], record.get("updated_at"), payload))
                        if records:
                            self.db.execute("INSERT INTO outbox(path, body) VALUES (?, ?)",
                                            (f"tratados/{source}/{day}.csv", csv_text(records)))
                self.pending.clear()
                self._materialize()
                self.storage_error = False
            except (OSError, sqlite3.Error):
                self.storage_error = True
                raise

    def _materialize(self):
        writes = self.db.execute("SELECT seq, path, body FROM outbox ORDER BY seq").fetchall()
        grouped = {}
        for row in writes:
            grouped.setdefault(row["path"], []).append(row["body"])
        with self.db:
            for relative, parts in grouped.items():
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                committed = self.db.execute("SELECT size FROM file_offsets WHERE path=?", (relative,)).fetchone()
                offset = committed[0] if committed else 0
                if offset and (not path.exists() or path.stat().st_size < offset):
                    raise OSError("Arquivo de dados menor que o último tamanho confirmado.")
                with path.open("r+b" if path.exists() else "w+b") as stream:
                    stream.seek(offset)
                    stream.truncate()
                    if offset == 0 and path.suffix == ".csv":
                        stream.write(("\ufeff" + csv_text([], header=True)).encode("utf-8"))
                    for part in parts:
                        stream.write(part.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                    size = stream.tell()
                self.db.execute("INSERT OR REPLACE INTO file_offsets VALUES (?, ?)", (relative, size))
            if writes:
                self.db.execute("DELETE FROM outbox WHERE seq<=?", (writes[-1]["seq"],))

    def snapshot(self, limit=5000, at=None, filters=None):
        reference = instant(at)
        cutoff = datetime.now(UTC) - timedelta(days=self.retention_days)
        if at and (reference < cutoff or reference > datetime.now(UTC) + timedelta(seconds=5)):
            raise ValueError("Escolha um horário dentro dos últimos 30 dias.")
        with self.lock:
            self.flush()
            if at is None:
                rows = self.db.execute("""SELECT payload FROM latest_state
                    WHERE position_at>=? AND position_at<=? AND collected_at<=? ORDER BY position_at DESC""",
                    (stamp(cutoff), stamp(reference), stamp(reference)))
            else:
                rows = self.db.execute("""SELECT payload FROM (
                    SELECT payload, position_at, ROW_NUMBER() OVER (
                        PARTITION BY source, object_id ORDER BY collected_at DESC, seq DESC) AS n
                    FROM observations WHERE collected_at<=? AND collected_at>=?)
                    WHERE n=1 AND position_at>=? AND position_at<=? ORDER BY position_at DESC""",
                    (stamp(reference), stamp(cutoff), stamp(cutoff), stamp(reference)))
            items = [json.loads(row[0]) for row in rows]
        items = [item for item in items if item.get("latitude") is not None and item.get("longitude") is not None
                 and matches(item, filters or {})]
        return items[:limit] if limit is not None else items, len(items)

    def coverage(self, bounds, at=None):
        reference = instant(at)
        items, total = self.snapshot(limit=None, at=at, filters={'object_type': 'vessel', 'bounds': bounds})
        return {'total': total,
                'recent_15m': sum(reference - instant(item['updated_at']) <= timedelta(minutes=15) for item in items),
                'recent_24h': sum(reference - instant(item['updated_at']) <= timedelta(hours=24) for item in items),
                'last_position_at': max((item['updated_at'] for item in items), default=None),
                'medium': sum(50 <= (item.get('length') or 0) < 250 for item in items),
                'unknown_size': sum(not item.get('length') for item in items)}

    def history(self, start, end, filters=None, raw=False):
        start, end = instant(start), instant(end)
        if start > end or start < datetime.now(UTC) - timedelta(days=self.retention_days) or end > datetime.now(UTC) + timedelta(seconds=5):
            raise ValueError("Período inválido; use os últimos 30 dias.")
        with self.lock:
            self.flush()
            conditions, args = ["collected_at>=?", "collected_at<=?"], [stamp(start), stamp(end)]
            if filters and filters.get("source") not in (None, "", "all"):
                conditions.append("source=?")
                args.append(filters["source"])
            if filters and filters.get("ids"):
                conditions.append("object_id IN (" + ",".join("?" for _ in filters["ids"]) + ")")
                args.extend(filters["ids"])
            records = [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM observations WHERE " + " AND ".join(conditions) + " ORDER BY collected_at, seq", args)]
            records = [item for item in records if matches(item, filters or {})]
            if not raw:
                return records
            if filters and any(value not in (None, "", "all", []) for value in filters.values()):
                return self.raw_for_records(records)
            packets = [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM packets WHERE collected_at>=? AND collected_at<=? ORDER BY collected_at, id",
                (stamp(start), stamp(end)))]
            matches_by_packet = {}
            for item in records:
                matches_by_packet.setdefault(item["raw_id"], set()).add(item["object_id"])
            return [dict(packet, matched_object_ids=sorted(matches_by_packet.get(packet["raw_id"], [])), payload_scope="original") for packet in packets]

    def raw_for_records(self, records, include_positions=False):
        matches_by_packet = {}
        for record in records:
            matches_by_packet.setdefault(record["raw_id"], set()).add(record["object_id"])
            if include_positions and record.get("position_raw_id"):
                matches_by_packet.setdefault(record["position_raw_id"], set()).add(record["object_id"])
        ids, packets = list(matches_by_packet), []
        with self.lock:
            for offset in range(0, len(ids), 500):
                batch = ids[offset:offset+500]
                for row in self.db.execute("SELECT payload FROM packets WHERE id IN (" + ",".join("?" for _ in batch) + ")", batch):
                    packet = json.loads(row[0])
                    packets.append(export_packet(packet, sorted(matches_by_packet[packet["raw_id"]])))
        return sorted(packets, key=lambda packet: (packet["collected_at"], packet["raw_id"]))

    def archive(self, now=None):
        """Archive complete UTC days only; delete index rows only after verified copies."""
        cutoff = instant(now) - timedelta(days=self.retention_days)
        boundary = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
        archived = 0
        with self.lock:
            self.flush()
            for category, extension in (("brutos", "jsonl"), ("tratados", "csv")):
                for path in sorted((self.root / category).glob(f"*/*.{extension}")):
                    try:
                        day = datetime.strptime(path.stem, "%Y-%m-%d").replace(tzinfo=UTC)
                    except ValueError:
                        continue
                    if day >= boundary:
                        continue
                    relative = path.relative_to(self.root)
                    target = self.root / "historico" / relative.with_suffix(path.suffix + ".gz")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(target.suffix + ".tmp")
                    original = hashlib.sha256()
                    with path.open("rb") as source, gzip.open(temporary, "wb") as output:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            original.update(block)
                            output.write(block)
                    verified = hashlib.sha256()
                    with gzip.open(temporary, "rb") as archived_file:
                        for block in iter(lambda: archived_file.read(1024 * 1024), b""):
                            verified.update(block)
                    if original.digest() != verified.digest():
                        raise OSError("Falha ao verificar o arquivo histórico.")
                    with temporary.open("r+b") as stream:
                        os.fsync(stream.fileno())
                    temporary.replace(target)
                    target.with_suffix(target.suffix + ".sha256").write_text(original.hexdigest() + "\n", encoding="ascii")
                    path.unlink()
                    self.db.execute("DELETE FROM file_offsets WHERE path=?", (relative.as_posix(),))
                    archived += 1
            with self.db:
                # Missing or externally modified journals must never trigger silent data loss.
                partitions = self.db.execute("SELECT DISTINCT source, substr(collected_at,1,10) AS day FROM packets WHERE collected_at<?", (stamp(boundary),)).fetchall()
                for partition in partitions:
                    for category, extension in (("brutos", "jsonl"), ("tratados", "csv")):
                        if category == "tratados" and not self.db.execute(
                            "SELECT 1 FROM observations WHERE source=? AND collected_at>=? AND collected_at<? LIMIT 1",
                            (partition["source"], stamp(partition["day"] + "T00:00:00+00:00"), stamp(instant(partition["day"] + "T00:00:00+00:00") + timedelta(days=1)))).fetchone():
                            continue
                        target = self.root / "historico" / category / partition["source"] / f"{partition['day']}.{extension}.gz"
                        expected = target.with_suffix(target.suffix + ".sha256").read_text(encoding="ascii").strip()
                        digest = hashlib.sha256()
                        with gzip.open(target, "rb") as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(block)
                        if digest.hexdigest() != expected:
                            raise OSError("Arquivo histórico alterado; o índice foi preservado.")
                self.db.execute("DELETE FROM observations WHERE collected_at<?", (stamp(boundary),))
                self.db.execute("DELETE FROM packets WHERE collected_at<?", (stamp(boundary),))
                self.db.execute("DELETE FROM latest_state WHERE position_at<? OR (position_at IS NULL AND collected_at<?)", (stamp(cutoff), stamp(cutoff)))
            self.vessels = {key: value for key, value in self.vessels.items()
                            if value.get("updated_at", "") >= stamp(cutoff)
                            or (not value.get("updated_at") and value.get("collected_at", "") >= stamp(cutoff))}
        return archived

    def close(self):
        with self.lock:
            self.flush()
            self.db.close()


def matches(item, filters):
    query = filters.get("q", "").strip().casefold()
    if query and not any(query in str(item.get(field) or "").casefold() for field in ("name", "object_id", "mmsi", "imo", "icao24", "callsign")):
        return False
    for field in ("source", "object_type", "type"):
        if filters.get(field) not in (None, "", "all", item.get(field)):
            return False
    if filters.get("ids") and item.get("object_id") not in filters["ids"]:
        return False
    if filters.get("keys") and f"{item.get('source')}:{item.get('object_id')}" not in filters["keys"]:
        return False
    size, motion = filters.get("size") or "all", filters.get("motion") or "all"
    if size != "all":
        length = item.get('length')
        ranges = {'large': (250, float('inf')), 'medium': (50, 250),
                  'compact': (0, 50), 'small': (0, 250)}  # Preserve legacy <250 API filter.
        if size == 'unknown':
            if length is not None and length > 0:
                return False
        elif size not in ranges or length is None or length <= 0 or not ranges[size][0] <= length < ranges[size][1]:
            return False
    if motion != "all" and (item.get("speed") is None or (item["speed"] <= .5 if motion == "moving" else item["speed"] > .5)):
        return False
    if filters.get("bounds"):
        south, west, north, east = filters["bounds"]
        lat, lon = item.get("latitude"), item.get("longitude")
        if lat is None or lon is None or not south <= lat <= north or not (west <= lon <= east if west <= east else lon >= west or lon <= east):
            return False
    return True


def export_packet(packet, object_ids):
    """Keep API values intact, but exclude unmatched objects from batch responses."""
    result = dict(packet, matched_object_ids=object_ids, payload_scope="original")
    payload = packet["payload"]
    if isinstance(payload, dict) and isinstance(payload.get("states"), list):
        result["payload"] = dict(payload, states=[row for row in payload["states"]
            if isinstance(row, list) and row and str(row[0]).lower() in object_ids])
        result["payload_scope"] = "filtered_states"
    elif isinstance(payload, dict) and payload.get("demo"):
        result["payload"] = dict(payload,
            vessels=[row for row in payload.get("vessels", []) if row.get("mmsi") in object_ids],
            aircraft=[row for row in payload.get("aircraft", []) if row.get("object_id") in object_ids])
        result["payload_scope"] = "filtered_demo"
    return result

