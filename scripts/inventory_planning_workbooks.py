"""Read every worksheet, including textual rules, without changing workbooks.

The compressed cell ledger is the complete evidence; the JSON index is a summary.
Run: .venv/bin/python scripts/inventory_planning_workbooks.py --output DIRECTORY
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.formula.translate import Translator

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
FILES = ('LayoutPlaneamentoPerfis.xlsx', 'Met2_Plan_Perfis.xlsm', 'Met3_Plan_Cantoneiras.xlsm')


def inventory(path, output):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {'file': str(path), 'sha256': digest, 'sheets': {}, 'names': []}
    with ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            with archive.open('xl/sharedStrings.xml') as stream:
                for _, node in ET.iterparse(stream, events=('end',)):
                    if node.tag == NS+'si':
                        strings.append(''.join(x.text or '' for x in node.iter(NS+'t')))
                        node.clear()
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        result['names'] = [dict(n.attrib, value=n.text) for n in book.iter(NS+'definedName')]
        relations = {r.get('Id'): r.get('Target') for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        if 'xl/vbaProject.bin' in archive.namelist():
            vba = archive.read('xl/vbaProject.bin')
            result['vba_sha256'] = hashlib.sha256(vba).hexdigest()
            (output/(path.stem+'-vbaProject.bin')).write_bytes(vba)
        ledger = output/(path.stem+'-cells.jsonl.gz')
        result['cell_ledger'] = ledger.name
        with gzip.open(ledger, 'wt', encoding='utf8') as dest:
            for sheet in book.find(NS+'sheets'):
                name = sheet.get('name')
                target = relations[sheet.get(REL+'id')]
                target = target.lstrip('/') if target.startswith('/') else 'xl/'+target
                counts = Counter(); shared = {}; samples = {}; validations = []
                with archive.open(target) as stream:
                    for _, node in ET.iterparse(stream, events=('end',)):
                        if node.tag.endswith('}dataValidation'):
                            validations.append(ET.tostring(node, encoding='unicode'))
                        if node.tag != NS+'row':
                            continue
                        counts['rows'] += 1
                        for cell in node:
                            coord = cell.get('r'); kind = cell.get('t')
                            val = cell.findtext(NS+'v'); formula = cell.find(NS+'f')
                            if kind == 's' and val is not None:
                                val = strings[int(val)]
                            elif kind == 'inlineStr':
                                val = ''.join(x.text or '' for x in cell.iter(NS+'t'))
                            elif val is not None and kind not in ('str', 'e'):
                                try:
                                    val = float(val)
                                    if val.is_integer(): val = int(val)
                                except ValueError:
                                    pass
                            text = formula.text if formula is not None else None
                            if formula is not None and formula.get('t') == 'shared':
                                index = formula.get('si')
                                if text: shared[index] = (text, coord)
                                elif index in shared:
                                    expression, origin = shared[index]
                                    text = Translator('='+expression, origin=origin).translate_formula(coord)[1:]
                            if val is None and formula is None: continue
                            counts['cells'] += 1
                            if formula is not None:
                                counts['formulas'] += 1
                                column = ''.join(c for c in coord if c.isalpha())
                                samples.setdefault(column, {'cell': coord, 'formula': text, 'cached': val})
                            if kind == 'e': counts['errors'] += 1
                            dest.write(json.dumps({'sheet': name, 'cell': coord, 'value': val,
                                                   'formula': text, 'type': kind}, ensure_ascii=False)+'\n')
                        node.clear()
                result['sheets'][name] = {'counts': dict(counts), 'formula_examples_by_column': samples,
                                          'validations': validations, 'state': sheet.get('state', 'visible')}
                print(path.name, name, dict(counts), flush=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Workbook changed during inventory')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('/home/luis/projects/DATARESEARCHMTG'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    results = [inventory(args.source/name, args.output) for name in FILES]
    (args.output/'workbook-inventory.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
