"""CSV and native XLSX export using the standard library."""
import io
import json
import math
import re
import zipfile
from xml.sax.saxutils import escape

from mvision.store import FIELDS, csv_text

RAW_FIELDS = ["raw_id", "source", "collected_at", "matched_object_ids", "payload_scope", "payload"]


def export_data(rows, format="csv", raw=False):
    fields = RAW_FIELDS if raw else FIELDS
    table = [{field: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
              for field, value in row.items()} for row in rows]
    if format == "csv":
        # Downloaded CSVs protect spreadsheet readers; canonical journals remain unchanged.
        safe = [{key: "'" + value if isinstance(value, str) and re.match(r"^[\s]*[=+@\-\t\r\n]", value) else value
                 for key, value in row.items()} for row in table]
        return ("\ufeff" + csv_text(safe, fields, header=True)).encode("utf-8"), "text/csv; charset=utf-8"
    if format != "xlsx":
        raise ValueError("Formato inválido.")
    if len(table) > 1048575:
        raise ValueError("O período excede o limite de linhas do Excel. Use CSV ou reduza o período.")

    def cell(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return f"<c><v>{value}</v></c>"
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value if value is not None else ""))
        if len(value) > 32767:
            raise ValueError("Uma resposta bruta excede o limite de texto do Excel. Use CSV.")
        return '<c t="inlineStr"><is><t xml:space="preserve">' + escape(value) + "</t></is></c>"

    sheet = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for index, values in enumerate([fields] + [[row.get(field) for field in fields] for row in table], 1):
        sheet.append(f'<row r="{index}">' + "".join(cell(value) for value in values) + "</row>")
    sheet.append("</sheetData></worksheet>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Dados" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", "".join(sheet))
    return buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
