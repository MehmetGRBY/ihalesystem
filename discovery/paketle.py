"""Paylaşım ZIP'i: uygulama, testler ve gerçek JSON çıktısı; araştırma dosyaları hariç."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse

ROOT = Path(__file__).resolve().parent
FILES = ['Baslat.cmd', 'README.md', 'JSON-SOZLESMESI.md', 'test_transfer.py', 'ekap_adapter.py', 'ekap_bulletin.py', 'opportunities.py', 'project_sources.py', 'test_opportunities.py', 'test_bulletin.py', 'test_ekap.py', 'requirements.txt', 'config.json', 'bulucu.py', 'source_adapters.py',
         'panel.html', 'panel.js', 'test_bulucu.py', 'test_adapters.py', 'paketle.py', '.gitignore']
FILES += ['network.py', 'pdf_text.py', 'company_contacts.py', 'test_reliability.py', 'test_priority_fixes.py']
parser = argparse.ArgumentParser()
parser.add_argument('--include-pdfs', action='store_true')
args = parser.parse_args()
target = ROOT.parent / ('EFA-Ihale-Bulucu-PDF.zip' if args.include_pdfs else 'EFA-Ihale-Bulucu.zip')
with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
    for name in FILES + ['data/ihaleler.json']:
        path = ROOT / name
        if path.exists():
            archive.write(path, 'EFA-Ihale-Bulucu/' + name)
    if args.include_pdfs:
        for path in sorted((ROOT / 'data' / 'ekap-bulten').glob('*.pdf')):
            archive.write(path, 'EFA-Ihale-Bulucu/data/ekap-bulten/' + path.name)
print(target)
