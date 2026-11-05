import json
import ssl
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import create_server
from mvision.enrichment import crawl_one, lookup, query_for
from mvision.store import VesselStore
from mvision.diagnostics import diagnose
from mvision.registry import VesselRegistry


def vessel(**fields):
    return dict(source='aisstream', object_id='123456789', mmsi='123456789',
                object_type='vessel', name='TEST', type='fishing', **fields)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'vessels.sqlite3'
        self.store = VesselStore(self.path)
        self.store.upsert(vessel(imo='9876543'))
        self.store.flush()
        self.registry = self.store.registry

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_sync_persistence_static_only_and_demo_exclusion(self):
        self.store.upsert(dict(vessel(), source='demo', mmsi='DEMO-123'))
        self.store.flush()
        self.assertEqual(self.registry.list()[1], 1)
        self.assertEqual(self.store.snapshot()[1], 0)
        self.store.close()
        self.store = VesselStore(self.path)
        self.registry = self.store.registry
        self.assertEqual(self.registry.list()[0][0]['imo'], '9876543')

    def test_manual_values_survive_crawler_and_telemetry(self):
        self.registry.edit('123456789', {'model': 'Modelo confirmado', 'manufacturer': 'Estaleiro manual'})
        claimed = self.registry.claim()
        self.registry.complete(claimed, 'matched', {'manufacturer': 'Outro estaleiro', 'vessel_class': 'Classe A'})
        self.store.upsert(vessel())
        self.store.flush()
        item = self.registry.list(query='Modelo confirmado', category='fishing')[0][0]
        self.assertEqual(item['manual']['model'], 'Modelo confirmado')
        self.assertEqual(item['manual']['manufacturer'], 'Estaleiro manual')
        self.assertEqual(item['enrichment']['manufacturer'], 'Outro estaleiro')
        self.assertIsNone(self.registry.claim())

    def test_identity_change_requeues_and_rejects_old_result(self):
        claimed = self.registry.claim()
        self.assertIsNone(self.registry.claim())
        self.store.upsert(vessel(imo='1234567'))
        self.store.flush()
        self.registry.complete(claimed, 'matched', {'manufacturer': 'Wrong vessel'})
        current = self.registry.list()[0][0]
        self.assertEqual(current['crawl_status'], 'pending')
        self.assertEqual(current['enrichment'], {})
        self.assertEqual(self.registry.claim()['imo'], '1234567')

    def test_network_error_and_not_found_are_not_fabricated(self):
        def fail(_):
            raise OSError('network unavailable')
        self.assertTrue(crawl_one(self.registry, fail)[0])
        item = self.registry.list(status='error')[0][0]
        self.assertEqual(item['enrichment'], {})
        self.assertIsNotNone(item['checked_at'])

    def test_http_rate_limit_defers_requests(self):
        def limited(_):
            raise HTTPError('https://query.wikidata.org', 429, 'limit', {'Retry-After': '1200'}, None)
        self.assertEqual(crawl_one(self.registry, limited), (True, 1200))
        self.assertIsNone(self.registry.claim())

    def test_only_tls_failures_are_requeued(self):
        def fail(_):
            raise URLError(ssl.SSLCertVerificationError('expired'))
        crawl_one(self.registry, fail)
        self.assertEqual(self.registry.list(status='error')[1], 1)
        self.assertEqual(self.registry.retry_tls_errors(), 1)
        item = self.registry.list()[0][0]
        self.assertEqual(item['crawl_status'], 'pending')
        self.assertIsNone(item['error'])
        self.assertEqual(self.registry.retry_tls_errors(), 0)
        self.registry.complete(self.registry.claim(), 'error', error='HTTP 429', retry_seconds=3600)
        self.assertEqual(self.registry.retry_tls_errors(), 0)
        self.assertIsNone(self.registry.claim())

    def test_edit_validation(self):
        for fields in ({'source_url': 'javascript:alert(1)'}, {'model': 123}, {'imo': '0000000'}):
            with self.assertRaises(ValueError):
                self.registry.edit('123456789', fields)

    def test_field_sources_history_conflicts_and_identity_isolation(self):
        self.registry.edit('123456789', {'manufacturer': 'Manual yard', 'source_url': 'https://example.org/manual'})
        self.registry.complete(self.registry.claim(), 'matched', {
            'manufacturer': 'Public yard', 'source': 'Wikidata', 'source_url': 'https://www.wikidata.org/wiki/Q1',
            'field_sources': {'manufacturer': [{'value': 'Public yard', 'property': 'P176',
                                               'source_url': 'https://www.wikidata.org/wiki/Q1'}]}})
        row = self.registry.list()[0][0]
        self.assertEqual(row['conflicts'], ['manufacturer'])
        evidence = row['field_sources']['manufacturer']
        self.assertEqual({e['value'] for e in evidence}, {'Manual yard', 'Public yard'})
        self.assertTrue(all(e['collected_at'] for e in evidence))
        self.registry.edit('123456789', {'manufacturer': 'New manual yard'})
        self.store.close()
        self.store = VesselStore(self.path)
        self.registry = self.store.registry
        row = self.registry.list()[0][0]
        self.assertEqual(len(row['field_sources']['manufacturer']), 3)
        self.assertEqual(row['manual']['manufacturer'], 'New manual yard')
        self.store.upsert(vessel(imo='1234567'))
        self.store.flush()
        self.assertNotIn('manufacturer', self.registry.list()[0][0]['field_sources'])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM vessel_field_sources WHERE field='manufacturer'").fetchone()[0], 3)

    def test_diagnostics_counts_missing_unknown_and_manual_precedence(self):
        self.registry.edit('123456789', {'manufacturer': 'Manual yard'})
        self.registry.complete(self.registry.claim(), 'matched', {'manufacturer': 'Public yard', 'operator': 'Operator'})
        self.store.upsert(dict(vessel(), mmsi='223456789', object_id='223456789', type='unknown', length=0))
        self.store.flush()
        report = diagnose(self.store.db)
        self.assertEqual(report['total'], 2)
        self.assertEqual(report['coverage']['type']['filled'], 1)
        self.assertEqual(report['coverage']['length']['filled'], 0)
        self.assertEqual(report['coverage']['manufacturer']['manual'], 1)
        self.assertEqual(report['coverage']['manufacturer']['external'], 0)
        self.assertEqual(report['coverage']['operator']['external'], 1)
        self.assertEqual(report['identifiers']['missing_imo'], 1)

    def test_legacy_sources_backfill_without_inventing_field_dates(self):
        self.store.db.execute('DELETE FROM vessel_field_sources')
        self.store.db.commit()
        self.registry = VesselRegistry(self.store.db, self.store.lock)
        evidence = self.registry.list()[0][0]['field_sources']['name'][0]
        self.assertEqual(evidence['value'], 'TEST')
        self.assertTrue(evidence['metadata']['legacy'])
        self.assertIsNone(evidence['collected_at'])

    def test_api_and_manual_edit(self):
        server = create_server(port=0, source='aisstream', store=self.store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/registry?type=fishing') as response:
                self.assertEqual(json.load(response)['total'], 1)
            with urlopen(base + '/api/registry/diagnostics') as response:
                self.assertEqual(json.load(response)['coverage']['imo']['filled'], 1)
            with urlopen(base + '/api/coverage?bounds=-24,-44,-23,-42') as response:
                coverage = json.load(response)
                self.assertEqual(coverage['total'], 0)  # Static-only fixture has no position.
                self.assertTrue(coverage['subscription_contains_area'])
            self.store.ingest('aisstream', {'MessageType': 'ShipStaticData'}, [], '2026-11-05T12:00:00+00:00')
            with urlopen(base + '/api/objects?q=does-not-exist') as response:
                objects = json.load(response)
            self.assertEqual(objects['objects'], [])
            self.assertEqual(objects['last_received_at'], '2026-11-05T12:00:00.000000+00:00')
            with urlopen(base + '/api/receipts') as response:
                self.assertEqual(json.load(response)['last_received_at'], objects['last_received_at'])
            body = json.dumps({'mmsi': '123456789', 'fields': {'model': 'Teste'}}).encode()
            request = Request(base + '/api/registry', body, {'Content-Type': 'application/json', 'Origin': base})
            with urlopen(request) as response:
                self.assertTrue(json.load(response)['saved'])
            request = Request(base + '/api/registry', body, {'Content-Type': 'application/json', 'Origin': 'https://external.example'})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
            with urlopen(base + '/registry.html') as response:
                self.assertIn(b'Cadastro', response.read())
            with self.assertRaises(HTTPError) as invalid:
                urlopen(base + '/api/registry?limit=0')
            self.assertEqual(invalid.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class LookupTests(unittest.TestCase):
    def fetch(self, rows):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps({'results': {'bindings': rows}}).encode()
        def opener(request, timeout):
            self.assertEqual(timeout, 30)
            self.assertIn('User-agent', request.headers)
            return Response()
        return lookup({'mmsi': '123456789', 'imo': '9876543'}, opener)

    def test_exact_identifier_query_prefers_imo(self):
        query = query_for({'imo': '9876543', 'mmsi': '123456789'})
        self.assertIn('wdt:P458 "9876543"', query)
        self.assertNotIn('P587', query)
        self.assertIn('wdt:P587 "123456789"', query_for({'mmsi': '123456789'}))
        with self.assertRaises(ValueError): query_for({'mmsi': '123" injection'})

    def test_missing_ambiguous_and_exact_results(self):
        self.assertEqual(self.fetch([]), ('not_found', {}))
        first = {'ship': {'value': 'http://www.wikidata.org/entity/Q123'},
                 'manufacturerLabel': {'value': 'Estaleiro'}, 'vesselClassLabel': {'value': 'Classe X'}}
        status, data = self.fetch([first])
        self.assertEqual(status, 'matched')
        self.assertEqual(data['vessel_class'], 'Classe X')
        self.assertNotIn('model', data)
        self.assertEqual(data['source_url'], 'https://www.wikidata.org/wiki/Q123')
        self.assertEqual(self.fetch([first, {'ship': {'value': 'http://www.wikidata.org/entity/Q456'}}]), ('ambiguous', {}))

    def test_extended_properties_keep_multiple_values_and_field_provenance(self):
        def binding(field, value, label=None):
            row = {'ship': {'value': 'http://www.wikidata.org/entity/Q123'},
                   'field': {'value': field}, 'value': {'value': value}}
            if label: row['valueLabel'] = {'value': label}
            return row
        status, data = self.fetch([
            binding('operator', 'http://www.wikidata.org/entity/Q1', 'Operator A'),
            binding('operator', 'http://www.wikidata.org/entity/Q2', 'Operator B'),
            binding('gross_tonnage', '12000'), binding('inception', '2001-01-01T00:00:00Z'),
            binding('vessel_subtype', 'http://www.wikidata.org/entity/Q3', 'Container ship'),
        ])
        self.assertEqual(status, 'matched')
        self.assertEqual(data['operator'], 'Operator A; Operator B')
        self.assertEqual(len(data['field_sources']['operator']), 2)
        self.assertEqual(data['field_sources']['gross_tonnage'][0]['property'], 'P1093')
        self.assertEqual(data['inception'], '2001-01-01T00:00:00Z')
        self.assertNotIn('model', data)
        query = query_for({'imo': '9876543'})
        self.assertIn('UNION', query)
        self.assertIn('wdt:P1093', query)

    def test_truncated_result_is_rejected(self):
        with self.assertRaises(ValueError):
            self.fetch([{'ship': {'value': 'http://www.wikidata.org/entity/Q123'}}] * 1001)


if __name__ == '__main__':
    unittest.main()
