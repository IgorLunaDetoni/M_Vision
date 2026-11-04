"""Low-rate public-data crawler. Match identifiers exactly; never guess by name."""
import argparse
import json
import os
import re
import ssl
import sqlite3
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from mvision.registry import VesselRegistry
from mvision.network import https_open

ENDPOINT = 'https://query.wikidata.org/sparql'
PROPERTIES = {
    'manufacturer': 'P176', 'vessel_class': 'P289', 'country': 'P8047',
    'vessel_subtype': 'P31', 'operator': 'P137', 'inception': 'P571',
    'service_entry': 'P729', 'gross_tonnage': 'P1093',
}


def query_for(vessel):
    imo = str(vessel.get('imo') or '')
    mmsi = str(vessel.get('mmsi') or '')
    if re.fullmatch(r'[0-9]{7}', imo):
        match = f'?ship wdt:P458 "{imo}".'
    elif re.fullmatch(r'[0-9]{9}', mmsi):
        match = f'?ship wdt:P587 "{mmsi}".'
    else:
        raise ValueError('Identificador inválido.')
    branches = ' UNION '.join('{ ?ship wdt:' + prop + ' ?value. BIND("' + field + '" AS ?field) }'
                              for field, prop in PROPERTIES.items())
    return '''PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX bd: <http://www.bigdata.com/rdf#>
SELECT DISTINCT ?ship ?shipLabel ?field ?value ?valueLabel
WHERE {
  { SELECT DISTINCT ?ship WHERE { ''' + match + ''' } LIMIT 2 }
  OPTIONAL { ''' + branches + ''' }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "pt,en". }
} LIMIT 1001'''


def lookup(vessel, opener=None):
    opener = opener or https_open
    request = Request(ENDPOINT + '?' + urlencode({'query': query_for(vessel), 'format': 'json'}),
                      headers={'Accept': 'application/sparql-results+json',
                               'User-Agent': 'MVisionLocal/1.0 (local vessel particulars; Python urllib)'})
    with opener(request, timeout=30) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Resposta muito grande.')
    bindings = json.loads(raw)['results']['bindings']
    if not isinstance(bindings, list):
        raise ValueError('Resposta inválida.')
    if len(bindings) >= 1001:
        raise ValueError('Resposta truncada; resultado não aplicado.')
    entities = {row['ship']['value'] for row in bindings}
    if not entities:
        return 'not_found', {}
    if len(entities) != 1:
        return 'ambiguous', {}  # Do not attach particulars from an ambiguous match.
    entity = next(iter(entities))
    if not re.fullmatch(r'https?://www\.wikidata\.org/entity/Q[0-9]+', entity):
        raise ValueError('Entidade inválida.')
    fields = {}
    field_sources = {}
    source_url = 'https://www.wikidata.org/wiki/' + entity.rsplit('/', 1)[-1]
    for field, prop in PROPERTIES.items():
        evidence = []
        for row in bindings:
            if row.get('field', {}).get('value') != field or 'value' not in row:
                continue
            value = row.get('valueLabel', row['value'])['value']
            if re.fullmatch(r'Q[0-9]+', value) or value.startswith('http://www.wikidata.org/entity/'):
                continue
            item = {'value': value[:2000], 'source': 'Wikidata', 'source_url': source_url,
                    'property': prop, 'value_id': row['value']['value']}
            if item not in evidence:
                evidence.append(item)
        if evidence:
            fields[field] = '; '.join(sorted({item['value'] for item in evidence}))[:2000]
            field_sources[field] = evidence
    for key, field in (('manufacturerLabel', 'manufacturer'), ('vesselClassLabel', 'vessel_class'),
                       ('countryLabel', 'country'), ('shipLabel', 'name')):
        values = sorted({row[key]['value'] for row in bindings if key in row
                         and not re.fullmatch(r'Q[0-9]+', row[key]['value'])})
        if values and field not in fields:
            fields[field] = '; '.join(values)[:2000]
    fields.update(source='Wikidata', source_url='https://www.wikidata.org/wiki/' + entity.rsplit('/', 1)[-1],
                  matched_by='imo' if re.fullmatch(r'[0-9]{7}', str(vessel.get('imo') or '')) else 'mmsi')
    fields['field_sources'] = field_sources
    return 'matched', fields


def crawl_one(registry, fetch=lookup):
    item = registry.claim()
    if item is None:
        return False, 60
    try:
        status, data = fetch(item)
        registry.complete(item, status, data)
        return True, 10
    except HTTPError as error:
        retry = error.headers.get('Retry-After', '') if error.headers else ''
        retry = max(300, min(int(retry), 86400)) if retry.isdigit() else 900
        registry.complete(item, 'error', error=f'HTTP {error.code}; nova tentativa agendada.', retry_seconds=retry)
        return True, retry
    except URLError as error:
        message = ('Falha na validação do certificado HTTPS da fonte; verifique data e certificados do computador.'
                   if isinstance(error.reason, ssl.SSLCertVerificationError) else
                   'Fonte pública indisponível; nova tentativa agendada.')
        registry.complete(item, 'error', error=message, retry_seconds=900)
        return True, 60
    except (OSError, ValueError, KeyError, TypeError):
        registry.complete(item, 'error', error='Falha na consulta pública; nova tentativa agendada.', retry_seconds=900)
        return True, 60


def collect_particulars(registry, stop):
    try:
        registry.retry_tls_errors()
    except sqlite3.Error:
        pass  # Existing retry times still apply if startup requeue is unavailable.
    while not stop.is_set():
        try:
            _, delay = crawl_one(registry)
        except sqlite3.Error:
            delay = 60
        if stop.wait(delay):
            break


def main():
    parser = argparse.ArgumentParser(description='Complementar o cadastro local com dados do Wikidata.')
    parser.add_argument('--database', default=str(Path(os.getenv('MVISION_DATA_DIR', 'data')) / 'vessels.sqlite3'))
    parser.add_argument('--limit', type=int, default=10, help='Máximo de embarcações consultadas nesta execução.')
    parser.add_argument('--retry-tls-errors', action='store_true', help='Reagendar somente falhas de certificado HTTPS antes do lote.')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('--limit deve ser de 1 a 100')
    path = Path(args.database)
    if not path.is_file():
        parser.error('Inicie o aplicativo primeiro para criar o cadastro local.')
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    registry = VesselRegistry(db, threading.RLock())
    if args.retry_tls_errors:
        print(f'{registry.retry_tls_errors()} falhas HTTPS reagendadas.', flush=True)
    stop = threading.Event()
    try:
        for index in range(args.limit):
            processed, delay = crawl_one(registry)
            if not processed:
                print('Nenhum cadastro pendente de consulta.')
                break
            print(f'Consulta {index + 1} concluída; resultado salvo no cadastro local.', flush=True)
            if index + 1 < args.limit:
                stop.wait(delay)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == '__main__':
    main()
