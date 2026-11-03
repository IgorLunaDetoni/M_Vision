"""Explicitly fictional vessels; coordinates are illustrative, never live AIS."""
from datetime import datetime, timedelta, timezone


# name, type, lat, lon, destination, length (m), speed (kn), course
SEEDS = [
    ("AURORA ATLANTIC", "tanker", -24.8, -44.8, "Santos, Brasil", 330, 12.4, 42),
    ("HORIZON ENERGY", "tanker", 25.1, 56.9, "Fujairah, EAU", 294, 10.8, 175),
    ("NORTH MERIDIAN", "tanker", 51.6, 2.8, "Rotterdam, Países Baixos", 277, 9.2, 68),
    ("PACIFIC EMBER", "tanker", 1.1, 104.4, "Singapura", 333, 8.6, 230),
    ("CORAL VENTURE", "tanker", 28.1, -92.4, "Houston, EUA", 250, 11.5, 310),
    ("ATLAS CRUDE", "tanker", 12.2, 44.6, "Suez, Egito", 336, 12.9, 295),
    ("LUMEN SPIRIT", "tanker", 6.2, 79.1, "Colombo, Sri Lanka", 274, 12.1, 85),
    ("SOUTHERN PETREL", "tanker", -35.8, 18.8, "Cidade do Cabo, África do Sul", 285, 13.1, 275),
    ("BLUE ESTUARY", "tanker", 35.4, 140.4, "Chiba, Japão", 243, 0.1, 140),
    ("AMBER STRAIT", "tanker", 35.7, -5.5, "Algeciras, Espanha", 228, 10.2, 90),
    ("BOREALIS FUEL", "tanker", 58.3, 4.2, "Bergen, Noruega", 244, 11.7, 355),
    ("OCEAN CEDAR", "tanker", -5.9, 10.1, "Luanda, Angola", 298, 11.2, 185),
    ("VECTOR EUROPA", "container", 36.1, 15.8, "Pireu, Grécia", 366, 18.2, 75),
    ("VECTOR PACIFIC", "container", 30.2, -151.4, "Los Angeles, EUA", 399, 20.3, 85),
    ("VECTOR ORIENT", "container", 30.2, 123.4, "Shanghai, China", 400, 17.4, 335),
    ("VECTOR AMERICAS", "container", 8.4, -79.7, "Balboa, Panamá", 294, 1.2, 130),
    ("VECTOR BALTIC", "container", 54.8, 12.8, "Gdansk, Polônia", 230, 15.6, 65),
    ("VECTOR JAVA", "container", -5.4, 107.2, "Jacarta, Indonésia", 300, 16.8, 120),
    ("VECTOR SOUTH", "container", -35.8, -54.2, "Montevidéu, Uruguai", 294, 16.2, 220),
    ("VECTOR WEST", "container", 33.1, -119.4, "Los Angeles, EUA", 366, 0.2, 15),
    ("IRON HORIZON", "bulk", -21.4, -39.6, "Tubarão, Brasil", 327, 12.2, 190),
    ("IRON PILBARA", "bulk", -19.4, 117.6, "Port Hedland, Austrália", 292, 11.4, 330),
    ("IRON EQUATOR", "bulk", -1.2, -42.1, "São Luís, Brasil", 362, 13.3, 65),
    ("IRON EAST", "bulk", 36.2, 122.8, "Qingdao, China", 289, 10.8, 280),
    ("GRAIN HORIZON", "bulk", 43.1, -10.4, "Antuérpia, Bélgica", 229, 12.4, 30),
    ("GRAIN FRONTIER", "bulk", -38.8, 146.3, "Melbourne, Austrália", 225, 11.6, 290),
    ("POLAR GAS", "gas", 25.7, 52.3, "Ras Laffan, Catar", 345, 16.1, 105),
    ("CELESTE LNG", "gas", 11.2, 111.4, "Yokohama, Japão", 290, 17.4, 45),
    ("ATLANTIC LNG", "gas", 30.2, -34.2, "Sines, Portugal", 295, 18.2, 70),
    ("ARCTIC GLOW", "gas", 69.8, 18.8, "Hammerfest, Noruega", 299, 15.3, 215),
    ("ISLAND TRADER", "cargo", 18.1, -66.5, "San Juan, Porto Rico", 156, 9.2, 280),
    ("COASTAL BRIDGE", "cargo", -12.1, -37.6, "Salvador, Brasil", 182, 10.6, 205),
    ("INDIAN TRADER", "cargo", -4.8, 40.4, "Mombaça, Quênia", 170, 11.1, 5),
    ("TASMAN BRIDGE", "cargo", -38.1, 170.9, "Auckland, Nova Zelândia", 199, 13.5, 120),
    ("COASTAL SCOUT", "other", 48.2, -125.1, "Vancouver, Canadá", 85, 8.1, 65),
    ("MARINE DISCOVERY", "other", 64.2, -23.4, "Reykjavík, Islândia", 98, 0.0, 270),
]


def demo_vessels(now=None):
    now = now or datetime.now(timezone.utc)
    vessels = []
    for i, (name, kind, lat, lon, destination, length, speed, course) in enumerate(SEEDS):
        # DEMO prefix deliberately prevents these identifiers from appearing real.
        vessels.append(dict(
            mmsi=f"DEMO-{i + 1:03d}", imo=f"DEMO-IMO-{i + 1:03d}",
            name=name, type=kind, latitude=lat, longitude=lon,
            destination=destination, length=length, width=round(length / 6.2),
            speed=speed, course=course, heading=course,
            status="Fundeado" if speed < 0.5 else "Em navegação",
            updated_at=(now - timedelta(minutes=(i * 7) % 94)).isoformat(),
            source="demo", callsign=None,
        ))
    return vessels


def demo_aircraft(now=None):
    now = now or datetime.now(timezone.utc)
    seeds = [("DEMO AIR 01", -23.6, -46.5, 420, 70), ("DEMO AIR 02", 51.5, -.1, 380, 215),
             ("DEMO AIR 03", 40.7, -74.0, 460, 110), ("DEMO AIR 04", 1.3, 103.8, 440, 325),
             ("DEMO AIR 05", -33.9, 151.2, 410, 40), ("DEMO AIR 06", 25.2, 55.3, 390, 180)]
    return [dict(object_id=f"DEMO-AIR-{i+1:03d}", object_type="aircraft", icao24=f"DEMO-AIR-{i+1:03d}",
                 name=name, callsign=name, type="aircraft", latitude=lat, longitude=lon,
                 speed=speed, course=course, heading=course, altitude=10000, status="Em voo",
                 updated_at=(now - timedelta(minutes=i*3)).isoformat(), source="demo",
                 event_at=None, timestamp_basis="demo") for i, (name, lat, lon, speed, course) in enumerate(seeds)]

