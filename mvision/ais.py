"""AISStream adapter. Authentication stays exclusively on the server."""
import asyncio
import json
import math
import random
from mvision.store import stamp

POSITIONS = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}
MESSAGE_TYPES = sorted(POSITIONS | {"ShipStaticData"})
DEFAULT_BOUNDING_BOXES = (((-40, -80), (10, -25)),)
STATUSES = {0: "Em navegação", 1: "Fundeado", 2: "Sem governo", 3: "Manobra restrita",
            4: "Restrito pelo calado", 5: "Atracado", 6: "Encalhado", 7: "Em pesca",
            8: "À vela", 15: "Não informado"}


def number(value, minimum, maximum, inclusive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if minimum <= value and (value <= maximum if inclusive else value < maximum) else None


def text(value):
    return value.replace("@", "").strip()[:120] if isinstance(value, str) else ""


def vessel_type(code):
    # AIS cargo codes do not distinguish bulk/container or LNG/oil tankers.
    if not isinstance(code, int):
        return "unknown"
    if 80 <= code <= 89:
        return "tanker"
    if 70 <= code <= 79:
        return "cargo"
    return "unknown" if code == 0 else "other"


def normalize(message, received_at=None):
    """Return a partial update; static packets never refresh position timestamps."""
    if not isinstance(message, dict):
        return None
    kind = message.get("MessageType")
    if kind not in MESSAGE_TYPES:
        return None
    metadata = message.get("MetaData") or {}
    envelope = message.get("Message") or {}
    if not isinstance(metadata, dict) or not isinstance(envelope, dict):
        return None
    payload = envelope.get(kind)
    if not isinstance(payload, dict) or payload.get("Valid") is False:
        return None
    mmsi = str(metadata.get("MMSI") or payload.get("UserID") or "")
    if len(mmsi) != 9 or not mmsi.isascii() or not mmsi.isdigit():
        return None
    now = stamp(received_at)
    update = {"mmsi": mmsi, "object_id": mmsi, "object_type": "vessel", "source": "aisstream"}
    name = text(payload.get("Name")) or text(metadata.get("ShipName"))
    if name:
        update["name"] = name
    if kind in POSITIONS:
        lat = number(payload.get("Latitude"), -90, 90)
        lon = number(payload.get("Longitude"), -180, 180)
        if lat is None or lon is None:
            return None
        event_at = None
        upstream_time = metadata.get("time_utc")
        if isinstance(upstream_time, str):
            try:
                candidate = stamp(upstream_time.removesuffix(" UTC"))
                if candidate <= now:
                    event_at = candidate
            except ValueError:
                pass
        update.update(latitude=lat, longitude=lon, updated_at=event_at or now,
                      event_at=event_at, timestamp_basis="source" if event_at else "collection",
                      speed=number(payload.get("Sog"), 0, 102.3, False),
                      course=number(payload.get("Cog"), 0, 360, False),
                      heading=number(payload.get("TrueHeading"), 0, 360, False))
        if "NavigationalStatus" in payload:
            update["status"] = STATUSES.get(payload["NavigationalStatus"], "Não informado")
    if kind == "ShipStaticData" or kind == "ExtendedClassBPositionReport":
        if "Type" in payload:
            update["type"] = vessel_type(payload["Type"])
        dimensions = payload.get("Dimension") or {}
        if isinstance(dimensions, dict):
            for field, a, b in (("length", "A", "B"), ("width", "C", "D")):
                first, second = number(dimensions.get(a), 0, 511), number(dimensions.get(b), 0, 511)
                if first is not None and second is not None and first + second > 0:
                    update[field] = first + second
        for key, field in (("Destination", "destination"), ("CallSign", "callsign")):
            value = text(payload.get(key))
            if value:
                update[field] = value
        imo = number(payload.get("ImoNumber"), 1000000, 9999999)
        if imo is not None:
            update["imo"] = str(int(imo))
    return update


def parse_boxes(raw=None):
    boxes = (json.loads(raw) if raw is not None else
             [[list(corner) for corner in box] for box in DEFAULT_BOUNDING_BOXES])
    if not isinstance(boxes, list) or not boxes:
        raise ValueError("AISSTREAM_BOUNDING_BOXES deve conter ao menos uma área.")
    for box in boxes:
        if not isinstance(box, list) or len(box) != 2:
            raise ValueError("Cada área deve conter dois cantos [latitude, longitude].")
        for corner in box:
            if not isinstance(corner, list) or len(corner) != 2 or number(corner[0], -90, 90) is None or number(corner[1], -180, 180) is None:
                raise ValueError("Coordenadas inválidas em AISSTREAM_BOUNDING_BOXES.")
    return boxes


async def collect(store, key, boxes, connect=None):
    if connect is None:
        from websockets.asyncio.client import connect
    delay = 1
    while True:
        store.set_connection("connecting")
        try:
            async with connect("wss://stream.aisstream.io/v0/stream", compression="deflate",
                               ping_interval=20, ping_timeout=20, open_timeout=20) as socket:
                await socket.send(json.dumps({"APIKey": key, "BoundingBoxes": boxes,
                                              "FilterMessageTypes": MESSAGE_TYPES}))
                async for raw in socket:
                    try:
                        message = json.loads(raw)
                        if not isinstance(message, dict):
                            continue
                        if message.get("error") or message.get("Error"):
                            # Do not echo upstream errors: they may contain credentials.
                            store.set_connection("error")
                            break
                        if message.get("MessageType") == "SubscriptionConfirmation":
                            store.set_connection("connected")
                            delay = 1
                        received_at = stamp()
                        update = normalize(message, received_at)
                        if message.get("MessageType") in MESSAGE_TYPES:
                            store.ingest("aisstream", message, [update] if update else [], received_at)
                        if update:
                            store.set_connection("connected")
                            delay = 1
                    except (ValueError, TypeError, KeyError):
                        continue
        except asyncio.CancelledError:
            raise
        except Exception:
            store.set_connection("reconnecting")
        if store.connection != "error":
            store.set_connection("reconnecting")
        await asyncio.sleep(delay + random.uniform(0, 1))
        delay = min(delay * 2, 60)
