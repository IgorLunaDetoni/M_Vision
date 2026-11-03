"""Optional worldwide OpenSky adapter. Secrets and OAuth responses never enter journals."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mvision.ais import number, text
from mvision.store import instant, stamp

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"


def normalize_state(state, received_at=None):
    if not isinstance(state, list) or len(state) < 17:
        return None
    identifier = state[0]
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", identifier):
        return None
    lon, lat = number(state[5], -180, 180), number(state[6], -90, 90)
    if lat is None or lon is None:
        return None
    # time_position, rather than last_contact, dates the coordinates.
    timestamp = number(state[3], 0, instant(received_at).timestamp())
    if timestamp is None:
        return None
    event_at = stamp(datetime.fromtimestamp(timestamp, timezone.utc))
    velocity = number(state[9], 0, 2000)
    course = number(state[10], 0, 360, False)
    callsign = text(state[1])
    return dict(object_id=identifier.lower(), object_type="aircraft", icao24=identifier.lower(),
                callsign=callsign, name=callsign or identifier.upper(), source="opensky", type="aircraft",
                latitude=lat, longitude=lon, speed=velocity * 1.94384449244 if velocity is not None else None,
                course=course, heading=course, altitude=number(state[7], -1000, 100000),
                status="Em solo" if state[8] is True else "Em voo" if state[8] is False else "Não informado",
                event_at=event_at, updated_at=event_at, timestamp_basis="source", origin_country=text(state[2]))


class OpenSkyClient:
    def __init__(self, client_id, client_secret, opener=urlopen):
        self.client_id, self.client_secret, self.opener = client_id, client_secret, opener
        self.token = None
        self.expires_at = 0

    def fetch(self):
        if not self.token or time.monotonic() >= self.expires_at:
            body = urlencode({"grant_type": "client_credentials", "client_id": self.client_id,
                              "client_secret": self.client_secret}).encode()
            request = Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
            with self.opener(request, timeout=30) as response:
                data = json.load(response)
            self.token = data["access_token"]
            self.expires_at = time.monotonic() + max(1, int(data.get("expires_in", 1800)) - 30)
        request = Request(STATES_URL, headers={"Authorization": f"Bearer {self.token}", "User-Agent": "M-Vision/0.2"})
        try:
            with self.opener(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 401:
                self.token = None
            raise


def collect_aircraft(store, client, stop, interval=300):
    while not stop.is_set():
        store.set_connection("connecting", "opensky")
        wait = interval
        try:
            packet = client.fetch()
            if stop.is_set():
                return
            if not isinstance(packet, dict) or not isinstance(packet.get("states"), (list, type(None))):
                raise ValueError("Resposta inválida.")
            received_at = stamp()
            updates = [item for state in packet.get("states") or [] if (item := normalize_state(state, received_at))]
            store.ingest("opensky", packet, updates, received_at)
            store.set_connection("connected", "opensky")
        except HTTPError as error:
            store.set_connection("rate_limited" if error.code == 429 else "error", "opensky")
            if error.code == 429:
                try:
                    wait = max(interval, int(error.headers.get("X-Rate-Limit-Retry-After-Seconds", interval)))
                except (TypeError, ValueError):
                    pass
        except Exception:
            store.set_connection("reconnecting", "opensky")
        stop.wait(wait)
