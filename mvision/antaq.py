"""Import ANTAQ fleet exports and reconcile exact vessel identities, never names."""
import argparse
import csv
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import unicodedata
from collections import defaultdict
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

MAX_FILE = 16 * 1024 * 1024
DEFAULT_SOURCE = 'https://www.gov.br/antaq/pt-br/assuntos/navegacao/maritima-de-de-apoio/frota'


def folded(value):
    value = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in value if not unicodedata.combining(c)))


ALIASES = {
    'name': ('nome', 'embarcacao', 'nomeembarcacao', 'nomedaembarcacao', 'navio', 'vesselname'),
    'imo': ('imo', 'numeroimo', 'nroimo', 'noimo', 'imo number'),
    'mmsi': ('mmsi', 'numerommsi'),
    'registration': ('inscricao', 'numeroinscricao', 'numerodeinscricao', 'inscricaodaembarcacao',
                     'ninscricao', 'noinscricao', 'tie', 'rpm', 'numerotie', 'registro', 'registroembarcacao'),
    'antaq_id': ('idembarcacao', 'codigoembarcacao', 'codembarcacao', 'codigoantaq'),
    'callsign': ('irin', 'indicativo', 'indicativodechamada', 'callsign'),
    'vessel_subtype': ('tipo', 'tipoembarcacao', 'tipodeembarcacao', 'tipodaembarcacao'),
    'operator': ('empresa', 'razaosocial', 'nomeempresa', 'empresadenavegacao', 'armador'),
    'length': ('comprimento', 'comprimentototal', 'comprimentom', 'comprimentototalm'),
    'width': ('boca', 'bocam', 'largura', 'larguram'),
    'gross_tonnage': ('ab', 'arqueacaobruta', 'gt'),
    'deadweight': ('tpb', 'toneladasdeportebruto', 'portebruto', 'dwt'),
    'year_built': ('anoconstrucao', 'anodeconstrucao'),
    'manufacturer': ('estaleiro', 'fabricante', 'estaleiroconstrutor'),
    'country': ('bandeira', 'paisderegistro', 'paisdabandeira'),
    'navigation': ('navegacao', 'tipodenavegacao', 'modalidade'),
    'authorization_status': ('situacao', 'situacaodaembarcacao', 'situacaoembarcacao', 'status'),
}
HEADERS = {folded(alias): field for field, aliases in ALIASES.items() for alias in aliases}


def valid_imo(value):
    return bool(re.fullmatch(r'[0-9]{7}', value) and
                sum(int(value[i]) * (7-i) for i in range(6)) % 10 == int(value[6]))


def identifier(value, prefix=''):
    value = str(value or '').strip().upper()
    if prefix and value.startswith(prefix):
        value = value[len(prefix):].strip()
    if value in ('', '-', 'N/A', 'NA', '0', '0000000', '000000000'):
        return ''
    if re.fullmatch(r'[0-9]+\.0', value):
        value = value[:-2]
    return re.sub(r'[\s.\-/]', '', value)


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.rows, self.row, self.cell = [], None, None, None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            if self.depth == 0:
                self.rows = []
            self.depth += 1
        if self.depth and tag == 'tr':
            self.row = []
        if self.row is not None and tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(self.cell).strip())
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == 'table':
            self.depth -= 1
            if self.depth == 0 and self.rows is not None:
                self.tables.append(self.rows)
                self.rows = None


def xlsx_tables(raw):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > 3000 or sum(i.file_size for i in archive.infolist()) > 80*1024*1024:
            raise ValueError('Planilha descompactada muito grande.')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(t.text or '' for t in item.findall('.//s:t', ns)) for item in root]
        result = []
        for name in sorted(n for n in archive.namelist() if re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml', n)):
            rows = []
            for row in ET.fromstring(archive.read(name)).findall('.//s:sheetData/s:row', ns):
                cells = []
                for cell in row.findall('s:c', ns):
                    ref = re.match(r'[A-Z]+', cell.get('r', ''))
                    column = 0
                    for char in ref.group() if ref else 'A':
                        column = column*26 + ord(char)-64
                    if column > 300:
                        raise ValueError('Planilha contém colunas demais.')
                    cells.extend([''] * max(0, column-len(cells)))
                    # Never interpret a formula as an identifier, even with a cached value.
                    value = '' if cell.find('s:f', ns) is not None else cell.findtext('s:v', '', ns)
                    if cell.get('t') == 's' and value:
                        value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//s:t', ns))
                    cells[column-1] = value
                rows.append(cells)
            result.append(rows)
        return result


def parse_export(raw, filename):
    if not raw or len(raw) > MAX_FILE:
        raise ValueError('Use um arquivo de até 16 MB.')
    if raw.startswith(b'PK'):
        try:
            tables = xlsx_tables(raw)
        except (BadZipFile, ET.ParseError, KeyError, IndexError) as exc:
            raise ValueError('Planilha XLSX inválida.') from exc
    else:
        if raw.startswith(bytes.fromhex('d0cf11e0')):
            raise ValueError('Salve o arquivo XLS antigo como CSV ou XLSX antes de importar.')
        text = None
        for encoding in ('utf-8-sig', 'utf-16', 'cp1252'):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeError:
                pass
        if text is None:
            raise ValueError('Não foi possível ler a codificação do arquivo.')
        if re.search(r'<table\b', text, re.I):
            parser = Tables()
            parser.feed(text)
            tables = parser.tables
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:16000], delimiters=';,\t,|')
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ';'
            tables = [list(csv.reader(io.StringIO(text), delimiter=delimiter))]
    result = []
    for table in tables:
        header = None
        for row in table:
            mapped = [HEADERS.get(folded(cell)) for cell in row]
            if 'name' in mapped and any(key in mapped for key in ('imo', 'mmsi', 'registration', 'antaq_id')):
                header = mapped
                continue
            if header is None or not any(str(v).strip() for v in row):
                continue
            fields = {key: str(value).strip()[:2000] for key, value in zip(header, row) if key and str(value).strip()}
            if fields.get('name'):
                result.append(fields)
    if not result:
        raise ValueError('Nenhuma tabela de embarcações encontrada. Inclua nome e uma coluna IMO, MMSI, inscrição ou código da embarcação.')
    if len(result) > 100000:
        raise ValueError('O arquivo excede 100 mil registros.')
    return result


def normalize_row(row):
    row = dict(row)
    issues = []
    for key, pattern in (('imo', r'[0-9]{7}'), ('mmsi', r'[0-9]{9}')):
        value = identifier(row.get(key), key.upper())
        if value and (not re.fullmatch(pattern, value) or (key == 'imo' and not valid_imo(value))):
            issues.append(key)
        row[key] = value
    row['registration'] = identifier(row.get('registration'))
    for key in ('length', 'width', 'gross_tonnage', 'deadweight'):
        if key in row:
            value = row[key].replace(' ', '')
            if ',' in value:
                value = value.replace('.', '').replace(',', '.')
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value) and float(value) > 0:
                row[key] = value
            else:
                row.pop(key)
    row['identifier_issues'] = issues
    return row


def match_record(row, vessels):
    if row.get('identifier_issues') or row.get('source_conflicts'):
        return 'conflict', None, 'Identificador inválido no arquivo; revisar antes de vincular.'
    imo, mmsi = row.get('imo'), row.get('mmsi')
    if isinstance(vessels, dict):
        by_imo, by_mmsi = vessels['imo'].get(imo, []), vessels['mmsi'].get(mmsi, [])
    else:
        by_imo = [v for v in vessels if imo and v.get('imo') == imo]
        by_mmsi = [v for v in vessels if mmsi and v['mmsi'] == mmsi]
    if len(by_imo) > 1:
        return 'ambiguous', None, 'O IMO está associado a vários MMSIs na base AIS.'
    if by_imo and by_mmsi and by_imo[0]['mmsi'] != by_mmsi[0]['mmsi']:
        return 'conflict', None, 'IMO e MMSI apontam para cadastros diferentes.'
    if by_imo:
        if mmsi and mmsi != by_imo[0]['mmsi']:
            return 'conflict', None, 'O MMSI informado difere do cadastro com esse IMO.'
        return 'matched', by_imo[0], 'imo'
    if by_mmsi:
        if imo and by_mmsi[0].get('imo') and imo != by_mmsi[0]['imo']:
            return 'conflict', None, 'O IMO informado difere do cadastro com esse MMSI.'
        return 'matched', by_mmsi[0], 'mmsi'
    if not imo and not mmsi:
        return 'needs_identifier', None, 'Inscrição ANTAQ sem IMO/MMSI correspondente no AIS; nome não confirma identidade.'
    return 'unmatched', None, 'Nenhum identificador correspondente na base AIS atual.'


class AntaqRegistry:
    def __init__(self, registry):
        self.registry, self.db, self.lock = registry, registry.db, registry.lock
        self.db.execute('''CREATE TABLE IF NOT EXISTS antaq_vessels (
            id TEXT PRIMARY KEY, payload TEXT NOT NULL, match_status TEXT NOT NULL,
            matched_mmsi TEXT, matched_identity TEXT, matched_by TEXT NOT NULL,
            imported_at TEXT NOT NULL, source_url TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS antaq_imports (
            sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL, source_url TEXT NOT NULL,
            imported_at TEXT NOT NULL, report TEXT NOT NULL)''')
        for key in ('imo', 'mmsi', 'registration', 'antaq_id'):
            self.db.execute(f"CREATE INDEX IF NOT EXISTS antaq_{key} ON antaq_vessels(json_extract(payload, '$.{key}'))")
        self.db.execute('CREATE INDEX IF NOT EXISTS antaq_link ON antaq_vessels(matched_mmsi)')

    def reconcile(self, changed=None):
        from mvision.registry import signature
        if not self.db.execute('SELECT 1 FROM antaq_vessels LIMIT 1').fetchone():
            return
        vessels = [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM vessel_registry')]
        index = {key: defaultdict(list) for key in ('imo','mmsi')}
        for vessel in vessels:
            for key in index:
                if vessel.get(key):
                    index[key][vessel[key]].append(vessel)
        sql, params = 'SELECT * FROM antaq_vessels', []
        if changed:
            sql += " WHERE matched_mmsi=? OR json_extract(payload,'$.mmsi')=? OR json_extract(payload,'$.imo')=?"
            params = [changed['mmsi'], changed['mmsi'], changed.get('imo') or '__none__']
        for record in self.db.execute(sql, params).fetchall():
            row = json.loads(record['payload'])
            status, vessel, reason = match_record(row, index)
            identity = signature(vessel) if vessel else None
            self.db.execute('UPDATE antaq_vessels SET match_status=?, matched_mmsi=?, matched_identity=?, matched_by=? WHERE id=?',
                            (status, vessel['mmsi'] if vessel else None, identity, reason, record['id']))
            if vessel:
                evidence = {key: value for key, value in row.items() if key in ALIASES and value}
                evidence['source_url'] = record['source_url']
                evidence['field_sources'] = {key: [dict(value=str(value), source_url=record['source_url'],
                    external_id=record['id'], matched_by=reason)] for key, value in evidence.items() if key != 'source_url'}
                self.registry.record_sources(vessel, evidence, 'ANTAQ', record['imported_at'])

    def summary(self):
        with self.lock:
            counts = dict(self.db.execute('SELECT match_status, COUNT(*) FROM antaq_vessels GROUP BY match_status'))
            latest = self.db.execute('SELECT imported_at, filename FROM antaq_imports ORDER BY imported_at DESC LIMIT 1').fetchone()
            return dict(total=sum(counts.values()), statuses=counts,
                        last_imported_at=latest[0] if latest else None, filename=latest[1] if latest else None)

    def import_file(self, raw, filename, source_url, commit=False):
        from mvision.registry import now
        parsed = [normalize_row(row) for row in parse_export(raw, filename)]
        parsed_url = urlsplit(source_url)
        if parsed_url.scheme != 'https' or parsed_url.username or parsed_url.password or not (
                parsed_url.hostname == 'www.gov.br' and parsed_url.path.startswith('/antaq/') or
                (parsed_url.hostname or '').endswith('.antaq.gov.br')):
            raise ValueError('Informe uma URL HTTPS oficial da ANTAQ como origem do arquivo.')
        report = dict(input_rows=len(parsed), created=0, updated=0, unchanged=0, duplicates_in_file=0)
        imported_at = now().isoformat()
        seen = set()
        with self.lock:
            self.db.execute('SAVEPOINT antaq_import')
            try:
                for row in parsed:
                    # Stable official identifiers make repeated exports idempotent.
                    key = next((f'{k}:{row[k]}' for k in ('imo', 'registration', 'mmsi', 'antaq_id') if row.get(k)
                                and k not in row['identifier_issues']), None)
                    key = key or 'row:' + hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                    if key in seen:
                        report['duplicates_in_file'] += 1
                    seen.add(key)
                    payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
                    existing = self.db.execute('SELECT payload FROM antaq_vessels WHERE id=?', (key,)).fetchone()
                    if existing:
                        previous = json.loads(existing['payload'])
                        if any(row.get(k) and previous.get(k) and row[k] != previous[k] for k in ('imo','mmsi','registration')):
                            row['source_conflicts'] = {k: sorted({str(row.get(k) or ''), str(previous.get(k) or '')})
                                                       for k in ('imo','mmsi','registration') if row.get(k) != previous.get(k)}
                            payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
                    # A later export may add IMO to a record previously identified by registration.
                    if not existing:
                        keys = [k for k in ('registration','antaq_id','mmsi') if row.get(k)]
                        same = self.db.execute('SELECT id,payload FROM antaq_vessels WHERE '+
                            ' OR '.join(f"json_extract(payload,'$.{k}')=?" for k in keys),
                            [row[k] for k in keys]).fetchall() if keys else []
                        if len(same) == 1:
                            previous = json.loads(same[0]['payload'])
                            if not any(row.get(k) and previous.get(k) and row[k] != previous[k] for k in ('imo','mmsi')):
                                key, existing = same[0]['id'], same[0]
                    report['created' if not existing else 'unchanged' if existing['payload'] == payload else 'updated'] += 1
                    self.db.execute('''INSERT INTO antaq_vessels VALUES (?,?,'unmatched',NULL,NULL,'',?,?)
                        ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, imported_at=excluded.imported_at,
                        source_url=excluded.source_url''', (key, payload, imported_at, source_url))
                self.reconcile()
                report.update(self.summary())
                report['preview'] = not commit
                self.db.execute('INSERT OR REPLACE INTO antaq_imports VALUES (?,?,?,?,?)',
                                (hashlib.sha256(raw).hexdigest(), Path(filename).name, source_url, imported_at,
                                 json.dumps(report, ensure_ascii=False)))
                if not commit:
                    self.db.execute('ROLLBACK TO antaq_import')
                self.db.execute('RELEASE antaq_import')
            except Exception:
                self.db.execute('ROLLBACK TO antaq_import')
                self.db.execute('RELEASE antaq_import')
                raise
        return report

    def records(self):
        return [dict(r, data=json.loads(r['payload'])) for r in self.db.execute('SELECT * FROM antaq_vessels ORDER BY id')]

    def catalog(self, vessels):
        from mvision.registry import signature
        by_mmsi = {v['mmsi']: v for v in vessels}
        standalone = []
        for record in self.records():
            row = record['data']
            vessel = by_mmsi.get(record['matched_mmsi'])
            if vessel and record['matched_identity'] == signature(vessel) and record['match_status'] == 'matched':
                vessel.setdefault('antaq_records', []).append(record['id'])
                vessel['antaq_match'] = 'matched'
                fields = vessel.setdefault('antaq', {})
                for key, value in row.items():
                    if key in ALIASES and value:
                        fields[key] = value
                fields.update(source_url=record['source_url'], imported_at=record['imported_at'],
                              matched_by=record['matched_by'])
                continue
            standalone.append(dict(name=row['name'], mmsi=row.get('mmsi') or None, imo=row.get('imo') or None,
                callsign=row.get('callsign'), registry_id='antaq:'+record['id'], type='unknown', origin='antaq',
                manual={}, enrichment={}, antaq=dict(row, source_url=record['source_url'], imported_at=record['imported_at']),
                antaq_match=record['match_status'], antaq_match_reason=record['matched_by'], crawl_status='not_applicable',
                field_sources={key: [dict(value=str(value),source='ANTAQ',source_url=record['source_url'],
                                         collected_at=record['imported_at'])]
                               for key,value in row.items() if key in ALIASES and value}))
        for vessel in vessels+standalone:
            resolved = dict(vessel.get('enrichment') or {})
            resolved.update({key: value for key,value in vessel.get('antaq', {}).items() if key in ALIASES and value})
            resolved.update({key: vessel[key] for key in ('name','imo','mmsi','callsign','length','width','destination')
                             if vessel.get(key) not in (None, '')})
            resolved.update({key: value for key,value in vessel.get('manual', {}).items() if value})
            vessel['resolved'] = resolved
        return vessels+standalone


def main():
    from mvision.registry import VesselRegistry
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path, help='Exportação CSV, XLSX ou HTML de tabela da ANTAQ.')
    parser.add_argument('--database', default=str(Path(os.getenv('MVISION_DATA_DIR', 'data'))/'vessels.sqlite3'))
    parser.add_argument('--source-url', default=DEFAULT_SOURCE)
    parser.add_argument('--apply', action='store_true', help='Gravar após conferir a prévia sem esta opção.')
    args = parser.parse_args()
    if not Path(args.database).is_file():
        parser.error('Inicie o aplicativo para criar o cadastro primeiro.')
    with sqlite3.connect(args.database, timeout=30) as db:
        db.row_factory = sqlite3.Row
        registry = VesselRegistry(db, threading.RLock())
        raw = args.file.read_bytes()
        report = registry.antaq.import_file(raw, args.file.name, args.source_url, commit=args.apply)
        if args.apply:
            target = Path(args.database).parent/'brutos'/'antaq'/'importacoes'
            target.mkdir(parents=True, exist_ok=True)
            (target/(hashlib.sha256(raw).hexdigest()+args.file.suffix.lower())).write_bytes(raw)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
