"""Package the actual read-only connector sources without changing any installed OCR code."""
import ast,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'app/dossiers/models.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='order_number')
normalizer=ast.get_source_segment(source,node)
cpis=(ROOT/'app/cpis_sync.py').read_text().replace('from .config import settings','from .connection_settings import settings').replace('from .dossiers.models import order_number','import re\n'+normalizer)
files={'raw_connectors/__init__.py':b'', 'raw_connectors/cpis_sync.py':cpis.encode(), 'raw_connectors/original_ocr.py':(ROOT/'app/original_ocr.py').read_bytes(),
       'raw_connectors/connection_settings.py':b"import os\nfrom types import SimpleNamespace\nsettings=SimpleNamespace(cpis_dsn=os.environ.get('CPIS_DSN',''),pg_dsn=os.environ.get('CPIS_PUBLISH_DSN',''))\n"}
for f in (ROOT/'deploy/raw-connectors').iterdir():files[f.name]=f.read_bytes()
kit=ROOT.parent/'pc-suite-kit'
files['original.env.example']=(kit/'original-ocr-import.env.example').read_bytes()
files['diagnose_cpis_readonly.ps1']=(kit/'diagnose_cpis_readonly.ps1').read_bytes()
manifest={k:hashlib.sha256(v).hexdigest() for k,v in files.items()}
files['manifest.json']=json.dumps(manifest,indent=2).encode()
out=ROOT/'docs/raw-completa/conectores-pc.zip'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for name,data in files.items():z.writestr(name,data)
(ROOT/'docs/raw-completa/conectores-manifest.json').write_text(json.dumps(manifest,indent=2))
print(out)
