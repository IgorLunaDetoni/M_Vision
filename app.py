"""Run: python app.py. Demo mode uses only the Python standard library."""
import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import math
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from mvision.ais import collect, parse_boxes
from mvision.aircraft import OpenSkyClient, collect_aircraft
from mvision.demo import demo_aircraft, demo_vessels
from mvision.exports import export_data
from mvision.enrichment import collect_particulars
from mvision.diagnostics import diagnose
from mvision.store import VesselStore, instant, stamp
from mvision.antaq import MAX_FILE, DEFAULT_SOURCE

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"


def query_filters(params):
    filters = {key: params.get(key, [""])[0] for key in ("q", "source", "object_type", "type", "size", "motion")}
    if "ids" in params:
        filters["ids"] = [value for value in params["ids"][0].split(",") if value]
    if "keys" in params:
        filters["keys"] = [value for value in params["keys"][0].split(",") if value]
    if "bounds" in params:
        bounds = [float(value) for value in params["bounds"][0].split(",")]
        if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
            raise ValueError("Área inválida.")
        south, west, north, east = bounds
        if not (-90 <= south <= north <= 90 and -180 <= west <= 180 and -180 <= east <= 180):
            raise ValueError("Área inválida.")
        filters["bounds"] = bounds
    return filters


def create_server(port=8000, source="demo", store=None, interval=300):
    temporary = None
    owned = store is None
    if store is None:
        temporary = tempfile.TemporaryDirectory(prefix="mvision-demo-")
        store = VesselStore(Path(temporary.name) / "index.sqlite3")
    if source == "demo":
        # The demo has its own index and source partition, never real telemetry.
        vessels, aircraft = demo_vessels(), demo_aircraft()
        store.ingest("demo", {"demo": True, "vessels": vessels, "aircraft": aircraft},
                     [dict(v, object_id=v["mmsi"], object_type="vessel", timestamp_basis="demo") for v in vessels] + aircraft)
        store.set_connection("demo", "demo")
        store.flush()

    class LocalServer(ThreadingHTTPServer):
        def server_close(self):
            super().server_close()
            if owned:
                store.close()
                temporary.cleanup()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, body, status=200, content_type="application/json; charset=utf-8", filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.send_header("Cache-Control", "no-cache")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            if self.path not in ('/api/registry', '/api/registry/antaq/import'):
                return self.respond(b'{"error":"Not found"}', 404)
            origin = self.headers.get('Origin')
            allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
            if (origin and origin not in allowed) or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.respond(b'{"error":"Forbidden"}', 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                importing = self.path == '/api/registry/antaq/import'
                if not 0 < length <= (24*1024*1024 if importing else 16000):
                    raise ValueError('Tamanho inválido.')
                body = json.loads(self.rfile.read(length))
                if importing:
                    filename = body.get('filename')
                    if not isinstance(filename, str) or len(filename) > 300:
                        raise ValueError('Nome de arquivo inválido.')
                    raw = base64.b64decode(body['content'], validate=True)
                    if len(raw) > MAX_FILE:
                        raise ValueError('Use um arquivo de até 16 MB.')
                    committing = body.get('commit') is True
                    with store.lock:
                        store.flush()
                        # Retain the original export before committing its normalized rows.
                        if committing:
                            target = store.root/'brutos'/'antaq'/'importacoes'
                            target.mkdir(parents=True, exist_ok=True)
                            suffix = Path(filename).suffix.lower()
                            suffix = suffix if suffix in ('.csv','.xlsx','.html','.htm','.xls','.txt') else '.bin'
                            (target/(hashlib.sha256(raw).hexdigest()+suffix)).write_bytes(raw)
                        report = store.registry.antaq.import_file(raw, filename, body.get('source_url') or DEFAULT_SOURCE,
                                                                 commit=committing)
                    return self.respond(json.dumps(report, ensure_ascii=False).encode())
                store.registry.edit(body['mmsi'], body['fields'])
                return self.respond(b'{"saved":true}')
            except (ValueError, TypeError, KeyError) as error:
                message = str(error) if self.path.endswith('/antaq/import') and isinstance(error, ValueError) else 'Cadastro inválido. Revise os campos.'
                return self.respond(json.dumps({'error': message}).encode(), 400)
            except (OSError, sqlite3.Error):
                return self.respond(b'{"error":"Storage unavailable"}', 503)

        def do_GET(self):
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path.startswith("/api/"):
                try:
                    return self.api(path, parse_qs(url.query))
                except (ValueError, TypeError, OverflowError) as error:
                    message = str(error) if isinstance(error, ValueError) and "Use CSV" in str(error) else "Parâmetros inválidos. Use datas com fuso e períodos dentro dos últimos 30 dias."
                    return self.respond(json.dumps({"error": message}).encode(), 400)
                except (OSError, sqlite3.Error):
                    return self.respond(json.dumps({"error": "Falha no armazenamento local. Verifique permissões e espaço em disco."}).encode(), 503)
            asset = (PUBLIC / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not asset.is_relative_to(PUBLIC) or not asset.is_file():
                return self.respond(b'{"error":"Not found"}', 404)
            mime = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
            self.respond(asset.read_bytes(), content_type=mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))

        def api(self, path, params):
            first = lambda key, default=None: params.get(key, [default])[0]
            filters = query_filters(params)
            at = first("at")
            if path == '/api/receipts':
                return self.respond(json.dumps(dict(store.receipt_status(), source=source), ensure_ascii=False).encode())
            if path == '/api/coverage':
                bounds = filters.get('bounds')
                if not bounds:
                    raise ValueError('Informe a área a verificar.')
                report = store.coverage(bounds, at=at)
                boxes = parse_boxes(os.getenv('AISSTREAM_BOUNDING_BOXES'))
                south, west, north, east = bounds
                inside = west <= east and any(min(a[0], b[0]) <= south <= north <= max(a[0], b[0])
                    and min(a[1], b[1]) <= west <= east <= max(a[1], b[1]) for a, b in boxes)
                report.update(subscription_contains_area=inside, source=source, connections=store.connections,
                              reference_at=at, served_at=stamp())
                return self.respond(json.dumps(report, ensure_ascii=False).encode())
            if path == '/api/registry/diagnostics':
                with store.lock:
                    store.flush()
                    report = diagnose(store.db)
                    report['antaq'] = store.registry.antaq.summary()
                return self.respond(json.dumps(report, ensure_ascii=False).encode())
            if path == '/api/registry/antaq':
                return self.respond(json.dumps(store.registry.antaq.summary(), ensure_ascii=False).encode())
            if path == '/api/registry':
                limit, offset = int(first('limit', '100')), int(first('offset', '0'))
                if not 1 <= limit <= 500 or offset < 0:
                    raise ValueError('Paginação inválida.')
                with store.lock:
                    store.flush()
                    rows, total = store.registry.list(first('q', ''), first('type', ''), first('status', ''), limit, offset,
                                                      origin=first('origin', ''))
                return self.respond(json.dumps({'vessels': rows, 'total': total, 'limit': limit, 'offset': offset},
                                               ensure_ascii=False).encode())
            if path in ("/api/objects", "/api/vessels"):
                if path == "/api/vessels":
                    filters["object_type"] = "vessel"
                limit = int(first("limit", "5000"))
                if not 1 <= limit <= 20000:
                    raise ValueError("Limite inválido.")
                rows, total = store.snapshot(limit=limit, at=at, filters=filters)
                payload = {"source": source, "connection": store.connection, "connections": store.connections,
                           **store.receipt_status(),
                           "objects": rows, "vessels": rows, "total": total, "truncated": total > len(rows),
                           "served_at": stamp(), "reference_at": at, "retention_days": store.retention_days,
                           "refresh_seconds": 50, "storage_error": store.storage_error}
                return self.respond(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
            if path == "/api/trajectory":
                object_id = first("object_id")
                if not object_id:
                    raise ValueError("Objeto obrigatório.")
                filters["ids"] = [object_id]
                end = instant(at)
                hours = float(first("hours", "6"))
                if not math.isfinite(hours) or not 0 < hours <= 720:
                    raise ValueError("Intervalo inválido.")
                start = max(end - timedelta(hours=hours), datetime.now(timezone.utc) - timedelta(days=30) + timedelta(seconds=1))
                rows = store.history(start, end, filters)
                points, seen = [], set()
                for row in rows:
                    identity = (row.get("updated_at"), row.get("latitude"), row.get("longitude"))
                    if identity in seen or row.get("latitude") is None or row.get("longitude") is None:
                        continue
                    seen.add(identity)
                    points.append(row)
                return self.respond(json.dumps({"points": points}, ensure_ascii=False, allow_nan=False).encode())
            if path == "/api/export":
                format = first("format", "csv")
                dataset = first("dataset", "treated")
                if format not in {"csv", "xlsx"} or dataset not in {"raw", "treated"}:
                    raise ValueError("Exportação inválida.")
                start, end = first("start"), first("end")
                if bool(start) != bool(end):
                    raise ValueError("Informe início e fim.")
                if start:
                    rows = store.history(start, end, filters, raw=dataset == "raw")
                else:
                    rows, _ = store.snapshot(limit=None, at=at, filters=filters)
                    if dataset == "raw":
                        rows = store.raw_for_records(rows, include_positions=True)
                body, mime = export_data(rows, format, raw=dataset == "raw")
                if self.command == "HEAD":
                    return self.respond(b"", content_type=mime)
                name = f"mvision-{dataset}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.{format}"
                target = store.root / "exportacoes" / name
                temporary_file = target.with_suffix(target.suffix + ".tmp")
                temporary_file.write_bytes(body)
                temporary_file.replace(target)
                return self.respond(body, content_type=mime, filename=name)
            return self.respond(b'{"error":"Not found"}', 404)

        def log_message(self, *_args):
            pass

    server = LocalServer(("127.0.0.1", port), Handler)
    server.data_root = store.root
    return server


def main():
    source = os.getenv("VESSEL_SOURCE", "demo").strip().lower()
    if source not in {"demo", "aisstream", "disabled"}:
        raise SystemExit("VESSEL_SOURCE deve ser demo, aisstream ou disabled.")
    aircraft_source = os.getenv("AIRCRAFT_SOURCE", "disabled").strip().lower()
    if aircraft_source not in {"disabled", "opensky"}:
        raise SystemExit("AIRCRAFT_SOURCE deve ser disabled ou opensky.")
    if source == "demo" and aircraft_source != "disabled":
        raise SystemExit("Use VESSEL_SOURCE=aisstream para combinar fontes reais. A demonstração fica isolada.")
    interval = int(os.getenv("COLLECTION_INTERVAL_SECONDS", "300"))
    if interval < 300:
        raise SystemExit("COLLECTION_INTERVAL_SECONDS deve ser pelo menos 300 nesta versão.")
    if aircraft_source == "opensky":
        if os.getenv("OPENSKY_LICENSE_CONFIRMED", "").lower() != "true":
            raise SystemExit("Confirme a licença operacional da OpenSky antes de definir OPENSKY_LICENSE_CONFIRMED=true.")
        if not os.getenv("OPENSKY_CLIENT_ID") or not os.getenv("OPENSKY_CLIENT_SECRET"):
            raise SystemExit("Defina OPENSKY_CLIENT_ID e OPENSKY_CLIENT_SECRET no servidor.")
    data_root = Path(os.getenv("MVISION_DATA_DIR", str(ROOT / "data"))).resolve()
    if data_root == PUBLIC or PUBLIC in data_root.parents:
        raise SystemExit("MVISION_DATA_DIR deve ficar fora da pasta pública.")
    # Retain compatibility with an existing vessels.sqlite3; demo gets a separate index.
    store = VesselStore(data_root / ("demo.sqlite3" if source == "demo" else "vessels.sqlite3"), data_root)
    store.archive()
    stop = threading.Event()
    workers = []
    collector_loop = None
    if source == "aisstream":
        key = os.getenv("AISSTREAM_API_KEY", "").strip()
        if not key:
            raise SystemExit("Defina AISSTREAM_API_KEY no ambiente do servidor.")
        try:
            import websockets  # noqa: F401
        except ImportError:
            raise SystemExit("Instale o coletor: python -m pip install -r requirements.txt")
        try:
            boxes = parse_boxes(os.getenv("AISSTREAM_BOUNDING_BOXES"))
        except (ValueError, TypeError) as exc:
            raise SystemExit(str(exc))
        collector_loop = asyncio.new_event_loop()
        task = collector_loop.create_task(collect(store, key, boxes))
        def run_ais():
            try:
                collector_loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass
            finally:
                collector_loop.close()
        workers.append(threading.Thread(target=run_ais, daemon=True))
    if aircraft_source == "opensky":
        client = OpenSkyClient(os.environ["OPENSKY_CLIENT_ID"], os.environ["OPENSKY_CLIENT_SECRET"])
        workers.append(threading.Thread(target=collect_aircraft, args=(store, client, stop, interval), daemon=True))
    if source == 'aisstream' and os.getenv('VESSEL_ENRICHMENT_ENABLED', 'true').lower() == 'true':
        workers.append(threading.Thread(target=collect_particulars, args=(store.registry, stop), daemon=True))

    def persist():
        next_archive = 0
        while not stop.wait(5):
            try:
                store.flush()
                if datetime.now(timezone.utc).timestamp() >= next_archive:
                    store.archive()
                    next_archive = datetime.now(timezone.utc).timestamp() + 3600
            except (OSError, sqlite3.Error):
                store.storage_error = True
                print("Falha ao gravar ou arquivar dados locais. Verifique o disco; nova tentativa em 5 segundos.", flush=True)

    workers.append(threading.Thread(target=persist, daemon=True))
    server = create_server(int(os.getenv("PORT", "8000")), source, store, interval)
    for worker in workers:
        worker.start()
    print(f"M Vision: http://127.0.0.1:{server.server_port} | fonte: {source}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if collector_loop and collector_loop.is_running():
            collector_loop.call_soon_threadsafe(task.cancel)
        for worker in workers:
            worker.join(timeout=50)
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
