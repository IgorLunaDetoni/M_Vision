"""Persistent vessel particulars, independent from the telemetry retention window."""
import json
import re
from datetime import datetime, timedelta, timezone


def now():
    return datetime.now(timezone.utc)


def signature(row):
    return f"{row['mmsi']}:{row.get('imo') or ''}"


class VesselRegistry:
    def __init__(self, db, lock):
        self.db, self.lock = db, lock
        db.execute("""CREATE TABLE IF NOT EXISTS vessel_registry (
            mmsi TEXT PRIMARY KEY, payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', next_attempt TEXT NOT NULL DEFAULT '')""")
        db.commit()

    def sync(self, item):
        """Called inside the telemetry transaction; synthetic vessels are excluded."""
        mmsi = str(item.get('mmsi') or '')
        if item.get('source') != 'aisstream' or not re.fullmatch(r'[0-9]{9}', mmsi):
            return
        existing = self.db.execute('SELECT payload, status, next_attempt FROM vessel_registry WHERE mmsi=?', (mmsi,)).fetchone()
        row = json.loads(existing['payload']) if existing else {
            'mmsi': mmsi, 'first_seen': item.get('collected_at'), 'manual': {},
            'enrichment': {}, 'checked_at': None, 'error': None}
        previous = signature(row)
        for key in ('name', 'imo', 'callsign', 'type', 'length', 'width', 'destination', 'status'):
            value = item.get(key)
            if value not in (None, ''):
                row[key] = value
        row['last_seen'] = item.get('collected_at')
        changed = previous != signature(row)
        if changed:
            if existing and previous.split(':', 1)[1]:
                history = row.setdefault('identity_history', [])
                history.append({'identifier': previous, 'manual': row['manual'],
                                'enrichment': row['enrichment'], 'changed_at': now().isoformat()})
                row['manual'] = {}
            row.update(enrichment={}, checked_at=None, error=None)
        status = 'pending' if changed or not existing else existing['status']
        due = '' if changed or not existing else existing['next_attempt']
        self.db.execute('INSERT OR REPLACE INTO vessel_registry VALUES (?, ?, ?, ?)',
                        (mmsi, json.dumps(row, ensure_ascii=False), status, due))

    def list(self, query='', category='', status='', limit=100, offset=0):
        with self.lock:
            rows = []
            for record in self.db.execute('SELECT * FROM vessel_registry ORDER BY mmsi'):
                item = json.loads(record['payload'])
                item['crawl_status'] = record['status']
                if category and category != 'all' and item.get('type', 'unknown') != category:
                    continue
                if status and status != 'all' and record['status'] != status:
                    continue
                searchable = ' '.join(str(item.get(key) or '') for key in ('name', 'mmsi', 'imo', 'callsign'))
                searchable += ' ' + json.dumps([item['manual'], item['enrichment']], ensure_ascii=False)
                if query.casefold() not in searchable.casefold():
                    continue
                rows.append(item)
            return rows[offset:offset + limit] if limit is not None else rows[offset:], len(rows)

    def edit(self, mmsi, values):
        if not isinstance(mmsi, str) or not re.fullmatch(r'[0-9]{9}', mmsi):
            raise ValueError('MMSI inválido.')
        allowed = {'model', 'manufacturer', 'vessel_class', 'notes', 'source_url'}
        if not isinstance(values, dict) or set(values) - allowed:
            raise ValueError('Campos inválidos.')
        if any(not isinstance(value, str) or len(value) > 2000 for value in values.values()):
            raise ValueError('Use texto de até 2000 caracteres por campo.')
        url = values.get('source_url', '')
        if url and not url.startswith(('https://', 'http://')):
            raise ValueError('A fonte deve ser uma URL HTTP ou HTTPS.')
        with self.lock, self.db:
            record = self.db.execute('SELECT payload FROM vessel_registry WHERE mmsi=?', (mmsi,)).fetchone()
            if not record:
                raise ValueError('Embarcação não cadastrada.')
            item = json.loads(record[0])
            item['manual'].update({key: value.strip() for key, value in values.items()})
            item['manual_updated_at'] = now().isoformat()
            self.db.execute('UPDATE vessel_registry SET payload=? WHERE mmsi=?', (json.dumps(item, ensure_ascii=False), mmsi))

    def claim(self):
        # The reservation is committed before network I/O, including across CLI processes.
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                record = self.db.execute('SELECT * FROM vessel_registry WHERE next_attempt<=? ORDER BY next_attempt, mmsi LIMIT 1',
                                         (now().isoformat(),)).fetchone()
                if record:
                    self.db.execute("UPDATE vessel_registry SET status='running', next_attempt=? WHERE mmsi=?",
                                    ((now() + timedelta(minutes=5)).isoformat(), record['mmsi']))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return json.loads(record['payload']) if record else None

    def complete(self, claimed, status, enrichment=None, error=None, retry_seconds=2592000):
        with self.lock, self.db:
            record = self.db.execute('SELECT payload FROM vessel_registry WHERE mmsi=?', (claimed['mmsi'],)).fetchone()
            if not record:
                return
            item = json.loads(record[0])
            if signature(item) != signature(claimed):
                return  # Identity changed during the request; leave the new lookup pending.
            item.update(checked_at=now().isoformat(), error=error)
            if enrichment is not None:
                item['enrichment'] = enrichment
            self.db.execute('UPDATE vessel_registry SET payload=?, status=?, next_attempt=? WHERE mmsi=?',
                            (json.dumps(item, ensure_ascii=False), status,
                             (now() + timedelta(seconds=retry_seconds)).isoformat(), claimed['mmsi']))
