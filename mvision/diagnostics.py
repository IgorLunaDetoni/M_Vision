"""Read-only registry coverage report: python -m mvision.diagnostics."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3

FIELDS = ('name', 'imo', 'callsign', 'type', 'length', 'width', 'manufacturer',
          'vessel_class', 'country', 'model', 'vessel_subtype', 'operator',
          'inception', 'service_entry', 'gross_tonnage')


def present(value):
    return value not in (None, '', 'unknown', 0, '0')


def diagnose(db):
    # One read transaction gives a consistent view even while AIS is collecting.
    records = db.execute('SELECT payload, status FROM vessel_registry').fetchall()
    rows = [json.loads(record[0]) for record in records]
    total = len(rows)
    coverage = {}
    for field in FIELDS:
        counts = Counter()
        for row in rows:
            for source, values in (('manual', row.get('manual', {})),
                                   ('external', row.get('enrichment', {})), ('ais', row)):
                if present(values.get(field)):
                    counts[source] += 1
                    counts['filled'] += 1
                    break
        coverage[field] = dict(filled=counts['filled'], missing=total-counts['filled'],
                               percent=round(100*counts['filled']/total, 1) if total else 0,
                               manual=counts['manual'], external=counts['external'], ais=counts['ais'])
    imo_groups = Counter(str(row.get('imo')) for row in rows if re.fullmatch(r'\d{7}', str(row.get('imo', ''))))
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(), 'total': total,
        'statuses': dict(Counter(status for _, status in records)),
        'types': dict(Counter(row.get('type') or 'unknown' for row in rows)),
        'coverage': coverage,
        'identifiers': {
            'valid_format_imo': sum(imo_groups.values()),
            'missing_imo': sum(not row.get('imo') for row in rows),
            'invalid_format_imo': sum(bool(row.get('imo')) and not re.fullmatch(r'\d{7}', str(row['imo'])) for row in rows),
            'shared_imo': {key: count for key, count in imo_groups.items() if count > 1},
        },
        'errors': dict(Counter(row.get('error') or 'Não detalhado' for row, (_, status) in zip(rows, records) if status == 'error')),
        'checked': sum(bool(row.get('checked_at')) for row in rows),
        'with_external_data': sum(any(present(row.get('enrichment', {}).get(k)) for k in FIELDS) for row in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=str(Path(os.getenv('MVISION_DATA_DIR', 'data')) / 'vessels.sqlite3'))
    parser.add_argument('--output', help='Salvar também o relatório JSON neste caminho.')
    args = parser.parse_args()
    path = Path(args.database).resolve()
    if not path.is_file():
        parser.error('Banco não encontrado. Inicie a coleta AIS primeiro.')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        report = diagnose(db)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + '\n', encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()
