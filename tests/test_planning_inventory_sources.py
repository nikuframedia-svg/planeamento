"""Source inventory must read the actual Excel cells, not invented references."""
from zipfile import ZipFile
import pytest
from scripts.inventory_planning_traceability import source_cells,coordinates


def test_reader_resolves_shared_formula_even_when_its_master_is_not_requested(tmp_path):
    path=tmp_path/'source.xlsx'
    with ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml','''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Plano" sheetId="1" r:id="rId1"/></sheets><definedNames><definedName name="Referencia">Plano!$C$7:$C$8</definedName></definedNames></workbook>''')
        z.writestr('xl/_rels/workbook.xml.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>''')
        z.writestr('xl/sharedStrings.xml','''<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><r><t>Referência </t></r><r><t>técnica</t></r></si></sst>''')
        z.writestr('xl/worksheets/sheet1.xml','''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="6"><c r="A6" t="s"><v>0</v></c></row><row r="7"><c r="A7"/><c r="C7"><f t="shared" si="0" ref="C7:C8">A7+B7</f><v>5</v></c></row><row r="8"><c r="A8" t="inlineStr"><is><t>ARRED.PARA.CIMA(Q/(S/L);0)</t></is></c><c r="C8"><f t="shared" si="0"/><v>13</v></c></row></sheetData></worksheet>''')
    original=path.read_bytes()
    cells,samples,names=source_cells(path,{'Plano':[coordinates('A6'),coordinates('C8')]},{'Plano':['A']})
    assert cells[('Plano','A6')]['value']=='Referência técnica'
    assert cells[('Plano','C8')]['formula']=='A8+B8'
    assert cells[('Plano','C8')]['value']==13
    assert samples[('Plano','A')]['cell']=='A8'
    assert samples[('Plano','A')]['value']=='ARRED.PARA.CIMA(Q/(S/L);0)'
    assert names[0]['value']=='Plano!$C$7:$C$8'
    assert path.read_bytes()==original


@pytest.mark.parametrize('reference',['AS7:AM7','A8:A7','A:A','7:7','not-a-cell'])
def test_inventory_rejects_non_concrete_or_reversed_ranges(reference):
    with pytest.raises(ValueError):coordinates(reference)
