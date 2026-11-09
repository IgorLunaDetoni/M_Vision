import base64
import csv
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app import create_server
from mvision.antaq import DEFAULT_SOURCE, parse_export, normalize_row, valid_imo
from mvision.registry import VesselRegistry
from mvision.store import VesselStore, stamp


def export(rows):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(['Nome da Embarcação','Número IMO','MMSI','Inscrição','Empresa','Estaleiro','Comprimento'])
    writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')


class AntaqTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'vessels.sqlite3'
        self.store = VesselStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ais(self, mmsi='123456789', imo='9321483', name='TRACKED'):
        self.store.upsert(dict(source='aisstream',object_type='vessel',object_id=mmsi,mmsi=mmsi,
            imo=imo,name=name,type='cargo',latitude=-23.5,longitude=-43.1,updated_at=stamp()))
        self.store.flush()

    def apply(self, rows, commit=True):
        return self.store.registry.antaq.import_file(export(rows),'frota.csv',DEFAULT_SOURCE,commit=commit)

    def test_preview_is_read_only_then_import_is_idempotent_and_one_catalog_row(self):
        self.ais()
        self.store.registry.edit('123456789', {'manufacturer':'Manual yard'})
        rows = [['OFFICIAL','9321483','123456789','001-234','Operator','Public yard','125,5']]*2
        evidence_before = self.store.db.execute('SELECT COUNT(*) FROM vessel_field_sources').fetchone()[0]
        report = self.apply(rows, commit=False)
        self.assertEqual(report['created'],1)
        self.assertEqual(report['duplicates_in_file'],1)
        self.assertEqual(report['statuses']['matched'],1)
        self.assertEqual(self.store.registry.antaq.summary()['total'],0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM vessel_field_sources').fetchone()[0], evidence_before)
        self.apply(rows)
        second = self.apply(rows)
        self.assertEqual(second['created'],0)
        self.assertEqual(second['total'],1)
        items,total = self.store.registry.list()
        self.assertEqual(total,1)
        self.assertEqual(items[0]['antaq_match'],'matched')
        self.assertEqual(items[0]['name'],'TRACKED')
        self.assertEqual(items[0]['resolved']['manufacturer'],'Manual yard')
        self.assertTrue(any(r['source']=='ANTAQ' for r in items[0]['field_sources']['manufacturer']))
        self.assertEqual(self.store.snapshot()[1],1)
        self.assertIsNone(self.store.receipt_status()['last_received_at'])

    def test_same_name_never_links_and_later_ais_identity_links_without_new_row(self):
        self.ais(name='SAME NAME')
        self.apply([['SAME NAME','','','002-222','Operator','',''],
                    ['FUTURE','1234567','','003-333','Operator','','']])
        items,total = self.store.registry.list()
        self.assertEqual(total,3)
        self.assertEqual(self.store.registry.list(origin='unlinked')[1],2)
        self.ais('223456789','1234567','FUTURE AIS')
        self.assertEqual(self.store.registry.list()[1],3)  # Two AIS + one still unlinked.
        self.assertEqual(self.store.registry.list(origin='linked')[1],1)
        self.assertEqual(self.store.registry.list(origin='unlinked')[1],1)
        self.assertEqual(self.store.registry.list(query='002222')[1],1)

    def test_conflicting_mmsi_and_imo_remain_separate(self):
        self.ais()
        self.ais('223456789','1234567')
        report = self.apply([['CONFLICT','9321483','223456789','','','','']])
        self.assertEqual(report['statuses']['conflict'],1)
        self.assertEqual(self.store.registry.list()[1],3)
        self.assertEqual(self.store.registry.list(origin='linked')[1],0)

    def test_ambiguous_imo_reconciles_when_one_ais_identity_changes(self):
        self.ais()
        self.ais('223456789','9321483')
        self.apply([['AMBIGUOUS','9321483','','','','','']])
        self.assertEqual(self.store.registry.antaq.summary()['statuses']['ambiguous'],1)
        self.ais('223456789','1234567')
        self.assertEqual(self.store.registry.antaq.summary()['statuses']['matched'],1)
        self.ais('123456789','9876543')
        self.assertEqual(self.store.registry.antaq.summary()['statuses']['unmatched'],1)
        self.assertEqual(self.store.registry.list(origin='linked')[1],0)

    def test_reimport_with_new_imo_uses_registration_and_survives_restart(self):
        self.apply([['VESSEL','','','001-111','','','']])
        self.apply([['VESSEL','9321483','','001111','','','']])
        self.assertEqual(self.store.registry.antaq.summary()['total'],1)
        self.ais()
        self.store.close()
        self.store = VesselStore(self.path)
        self.assertEqual(self.store.registry.list()[1],1)
        self.assertEqual(self.store.registry.list(origin='linked')[1],1)

    def test_conflicting_identifiers_inside_file_roll_back_whole_import(self):
        with self.assertRaises(ValueError):
            self.apply([['A','9321483','123456789','001111','','',''],
                        ['A','9321483','223456789','001111','','','']])
        self.assertEqual(self.store.registry.antaq.summary()['total'],0)

    def test_invalid_imo_is_not_used_for_matching(self):
        self.ais()
        report = self.apply([['BAD','9321484','123456789','','','','']])
        self.assertEqual(report['statuses']['conflict'],1)
        self.assertEqual(self.store.registry.list(origin='linked')[1],0)

    def test_api_preview_apply_origin_guard_and_raw_export(self):
        self.ais()
        raw = export([['OFFICIAL','9321483','','001111','Operator','','']])
        server = create_server(port=0,source='aisstream',store=self.store)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        body = dict(filename='frota.csv',content=base64.b64encode(raw).decode(),source_url=DEFAULT_SOURCE)
        def post(commit, origin=base):
            request = Request(base+'/api/registry/antaq/import',json.dumps(dict(body,commit=commit)).encode(),
                              {'Content-Type':'application/json','Origin':origin})
            with urlopen(request) as response:
                return json.load(response)
        try:
            self.assertTrue(post(False)['preview'])
            self.assertEqual(self.store.registry.antaq.summary()['total'],0)
            with self.assertRaises(HTTPError):
                post(True,'https://unrelated.example')
            self.assertFalse(post(True)['preview'])
            self.assertEqual(len(list((self.store.root/'brutos'/'antaq'/'importacoes').glob('*.csv'))),1)
            with urlopen(base+'/api/registry?origin=linked') as response:
                self.assertEqual(json.load(response)['total'],1)
        finally:
            server.shutdown();server.server_close();thread.join()


class ExportParsingTests(unittest.TestCase):
    def test_csv_and_html_preserve_identifiers_and_normalize_decimal_comma(self):
        rows = parse_export(export([['VESSEL','IMO 9321483','012345678','001-234','','','125,5']]),'x.csv')
        item = normalize_row(rows[0])
        self.assertEqual(item['imo'],'9321483')
        self.assertEqual(item['mmsi'],'012345678')
        self.assertEqual(item['registration'],'001234')
        self.assertEqual(item['length'],'125.5')
        html = b'<table><tr><th>Nome</th><th>IMO</th></tr><tr><td>VESSEL</td><td>9321483</td></tr></table>'
        self.assertEqual(parse_export(html,'x.xls')[0]['imo'],'9321483')

    def test_xlsx_text_identifiers_and_formulas_are_not_evaluated(self):
        root = ET.Element('worksheet',xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main')
        data = ET.SubElement(root,'sheetData')
        for number,values in enumerate([['Nome','IMO','MMSI'],['VESSEL','9321483','012345678']],1):
            row = ET.SubElement(data,'row',r=str(number))
            for col,value in zip('ABC',values):
                cell = ET.SubElement(row,'c',r=col+str(number),t='inlineStr')
                ET.SubElement(ET.SubElement(cell,'is'),'t').text=value
        out = io.BytesIO()
        with ZipFile(out,'w') as archive:
            archive.writestr('xl/worksheets/sheet1.xml',ET.tostring(root))
        self.assertEqual(parse_export(out.getvalue(),'x.xlsx')[0]['mmsi'],'012345678')

    def test_non_vessel_file_and_invalid_imo(self):
        self.assertTrue(valid_imo('9321483'))
        self.assertFalse(valid_imo('9321484'))
        with self.assertRaises(ValueError):
            parse_export(b'Company;City\nExample;Santos','x.csv')
        with self.assertRaises(ValueError):
            parse_export(bytes.fromhex('d0cf11e0')+b'oldxls','x.xls')
