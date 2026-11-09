"""Persistent vessel particulars, independent from the telemetry retention window."""
import json
import re
from datetime import datetime, timedelta, timezone
from mvision.antaq import AntaqRegistry


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
        db.execute("""CREATE TABLE IF NOT EXISTS vessel_field_sources (
            identity TEXT NOT NULL, field TEXT NOT NULL, source TEXT NOT NULL,
            value TEXT NOT NULL, source_url TEXT NOT NULL, property TEXT NOT NULL,
            first_collected_at TEXT, collected_at TEXT, metadata TEXT NOT NULL,
            PRIMARY KEY (identity, field, source, value, source_url, property))""")
        self.antaq = AntaqRegistry(self)
        # Backfill only known timestamps; never invent a date for legacy records.
        for record in db.execute('SELECT payload FROM vessel_registry').fetchall():
            item = json.loads(record['payload'])
            self.record_sources(item, {k: item[k] for k in ('name', 'imo', 'callsign', 'type', 'length', 'width', 'destination')
                                       if item.get(k) not in (None, '')}, 'AISStream', None, legacy=True)
            self.record_sources(item, item.get('manual', {}), 'Manual', item.get('manual_updated_at'), legacy=True)
            self.record_sources(item, item.get('enrichment', {}), 'Wikidata', item.get('checked_at'), legacy=True)
        self.antaq.reconcile()
        db.commit()

    def record_sources(self, item, values, source, collected_at, legacy=False):
        metadata_keys = {'source', 'source_url', 'matched_by', 'field_sources', 'notes'}
        for field, value in values.items():
            if field in metadata_keys or value in (None, ''):
                continue
            entries = values.get('field_sources', {}).get(field) or [
                {'value': str(value), 'source_url': values.get('source_url', '')}]
            for entry in entries:
                self.db.execute('''INSERT INTO vessel_field_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(identity, field, source, value, source_url, property) DO UPDATE SET
                    collected_at=COALESCE(excluded.collected_at, collected_at),
                    metadata=CASE WHEN json_extract(excluded.metadata, '$.legacy')=0
                                  THEN excluded.metadata ELSE metadata END''',
                    (signature(item), field, source, str(entry['value']), entry.get('source_url', ''),
                     entry.get('property', ''), collected_at, collected_at,
                     json.dumps(dict(entry, legacy=legacy), ensure_ascii=False)))

    def sources(self, item):
        result = {}
        for record in self.db.execute('SELECT * FROM vessel_field_sources WHERE identity=? ORDER BY field, source, value',
                                      (signature(item),)):
            entry = dict(record)
            entry.pop('identity')
            entry['metadata'] = json.loads(entry['metadata'])
            result.setdefault(entry.pop('field'), []).append(entry)
        return result

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
        self.record_sources(row, {k: item[k] for k in ('name', 'imo', 'callsign', 'type', 'length', 'width', 'destination')
                                  if item.get(k) not in (None, '')}, 'AISStream', item.get('collected_at'))
        if changed or not existing:
            self.antaq.reconcile(row)

    def list(self, query='', category='', status='', limit=100, offset=0, origin=''):
        with self.lock:
            candidates = []
            for record in self.db.execute('SELECT * FROM vessel_registry ORDER BY mmsi'):
                item = json.loads(record['payload'])
                item['crawl_status'] = record['status']
                item['origin'] = 'aisstream'
                candidates.append(item)
            candidates = self.antaq.catalog(candidates)
            rows = []
            for item in candidates:
                if origin == 'antaq' and not item.get('antaq'):
                    continue
                if origin == 'aisstream' and item['origin'] != 'aisstream':
                    continue
                if origin == 'linked' and item.get('antaq_match') != 'matched':
                    continue
                if origin == 'unlinked' and item['origin'] != 'antaq':
                    continue
                if category and category != 'all' and item.get('type', 'unknown') != category:
                    continue
                if status and status != 'all' and item['crawl_status'] != status:
                    continue
                searchable = ' '.join(str(item.get(key) or '') for key in ('name', 'mmsi', 'imo', 'callsign'))
                searchable += ' ' + json.dumps([item['manual'], item['enrichment'], item.get('antaq', {})], ensure_ascii=False)
                if query.casefold() not in searchable.casefold():
                    continue
                rows.append(item)
            page = rows[offset:offset + limit] if limit is not None else rows[offset:]
            for item in page:
                item['field_sources'] = self.sources(item) if item['origin'] == 'aisstream' else item.get('field_sources', {})
                item['conflicts'] = [key for key, value in item.get('manual', {}).items()
                                     if key not in ('notes', 'source_url') and value
                                     and item.get('enrichment', {}).get(key)
                                     and value != item['enrichment'][key]]
            return page, len(rows)

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
            self.record_sources(item, item['manual'], 'Manual', item['manual_updated_at'])
            self.db.execute('UPDATE vessel_registry SET payload=? WHERE mmsi=?', (json.dumps(item, ensure_ascii=False), mmsi))

    def retry_tls_errors(self):
        count = 0
        with self.lock, self.db:
            for record in self.db.execute("SELECT mmsi, payload FROM vessel_registry WHERE status='error'").fetchall():
                item = json.loads(record['payload'])
                if 'certificado HTTPS' not in (item.get('error') or ''):
                    continue
                item['error'] = None
                self.db.execute("UPDATE vessel_registry SET payload=?, status='pending', next_attempt='' WHERE mmsi=?",
                                (json.dumps(item, ensure_ascii=False), record['mmsi']))
                count += 1
        return count

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
                self.record_sources(item, enrichment, enrichment.get('source', 'Wikidata'), item['checked_at'])
            self.db.execute('UPDATE vessel_registry SET payload=?, status=?, next_attempt=? WHERE mmsi=?',
                            (json.dumps(item, ensure_ascii=False), status,
                             (now() + timedelta(seconds=retry_seconds)).isoformat(), claimed['mmsi']))
