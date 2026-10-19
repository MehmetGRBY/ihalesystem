"""EKAP'ın açık günlük bülten indirme formundan resmî PDF ilanları."""
import hashlib
import io
import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zipfile import ZipFile
from source_adapters import Tree, normalize, parse_date, TR, MONTHS

URL = 'https://ekap.kik.gov.tr/EKAP/Ilan/BultenIndirme.aspx'
ROOT = Path(__file__).resolve().parent
STORE = ROOT / 'data' / 'ekap-bulten'
KINDS = {'Mal': '1', 'Yapim': '2', 'Hizmet': '3'}


def form_fields(html):
    return {node.attrs['name']: node.attrs.get('value', '') for node in Tree(html).root.walk('input')
            if node.attrs.get('type') == 'hidden' and node.attrs.get('name')}


def curl(args):
    for attempt in range(3):
        result = subprocess.run(['curl.exe' if __import__('os').name=='nt' else 'curl', '--fail', '--silent', '--show-error', '--location', '--max-time', '60', *args], capture_output=True, timeout=70)
        if result.returncode not in (6,7,28,52,56) or attempt==2:
            break
        time.sleep(2**attempt)
    if result.returncode:
        raise RuntimeError('EKAP bülten bağlantısı: ' + result.stderr.decode('utf-8',errors='replace')[:500])


def download(kind, date):
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / f'{date:%Y%m%d}_{kind}.json'
    # Yakın geçmişteki boş/eksik bir indirme kalıcı önbellek olmasın.
    if cache.exists() and (date < datetime.now(TR).date() - timedelta(days=7) or datetime.now(TR).timestamp() - cache.stat().st_mtime < 4*3600):
        files = [STORE / name for name in json.loads(cache.read_text())]
        if all(p.exists() for p in files):
            return files
    with tempfile.TemporaryDirectory(dir=STORE) as folder:
        folder = Path(folder)
        html, cookie, body, output = [folder/name for name in ('form.html','cookies.txt','post.txt','response.bin')]
        curl(['-c',str(cookie),URL,'-o',str(html)])
        fields = form_fields(html.read_text(encoding='utf-8-sig'))
        if '__VIEWSTATE' not in fields:
            raise RuntimeError('EKAP bülten formu değişmiş veya erişilemiyor')
        fields.update(__EVENTTARGET='ctl00$ContentPlaceHolder1$btnYukle',__EVENTARGUMENT='')
        fields['ctl00$ContentPlaceHolder1$ddlIhaleTuru'] = KINDS[kind]
        fields['ctl00$ContentPlaceHolder1$etBultenTarihi$EkapTakvimTextBox_etBultenTarihi'] = date.strftime('%d.%m.%Y')
        # Gerçek formdaki select adını ve seçenek değerini kullan.
        selects = list(Tree(html.read_text(encoding='utf-8-sig')).root.walk('select'))
        selector = next((n for n in selects if any(normalize(o.text).startswith(normalize({'Yapim':'Yapım','Hizmet':'Hizmet','Mal':'Mal'}[kind])) for o in n.walk('option'))),None)
        if not selector:
            raise RuntimeError('EKAP bülten türü alanı bulunamadı')
        option = next(o for o in selector.walk('option') if normalize(o.text).startswith(normalize({'Yapim':'Yapım','Hizmet':'Hizmet','Mal':'Mal'}[kind])))
        fields.pop('ctl00$ContentPlaceHolder1$ddlIhaleTuru',None)
        fields[selector.attrs['name']] = option.attrs['value']
        body.write_text(urlencode(fields),encoding='ascii')
        curl(['-b',str(cookie),'-H','Content-Type: application/x-www-form-urlencoded','--data-binary','@'+str(body),URL,'-o',str(output)])
        raw = output.read_bytes()
        if raw.startswith(b'PK'):
            with ZipFile(io.BytesIO(raw)) as archive:
                members = [m for m in archive.infolist() if m.filename.lower().endswith('.pdf')]
                if not members or sum(m.file_size for m in members)>100*1024*1024:
                    raise RuntimeError('EKAP bülten arşivi geçersiz veya çok büyük')
                files = []
                for member in members:
                    # ZIP içindeki klasör yollarını kullanma.
                    name = Path(member.filename).name
                    if not re.fullmatch(r'BULTEN_\d{8}_[A-Z_]+\.pdf', name):
                        raise RuntimeError('Beklenmeyen EKAP bülten dosya adı')
                    if not name.startswith('BULTEN_'+date.strftime('%d%m%Y')+'_'):
                        raise RuntimeError('EKAP istenen tarih yerine farklı tarihli bülten döndürdü')
                    path = STORE/name
                    path.write_bytes(archive.read(member))
                    files.append(path)
        elif raw.startswith(b'%PDF'):
            path = STORE/f'BULTEN_{date:%d%m%Y}_{kind.upper()}.pdf'
            path.write_bytes(raw)
            files = [path]
        else:
            text = normalize(Tree(raw.decode('utf-8',errors='replace')).root.text)
            if re.search(r'bulten.{0,160}(?:bulunamad|bulunmamak|yayinlanmamis|yayimlanmamis|mevcut degil)',text):
                cache.write_text('[]',encoding='utf-8')
                return []
            raise RuntimeError('EKAP PDF/ZIP yerine sayfa döndürdü; tarih, yayın veya erişim kontrol edilmeli. '+text[-700:])
        cache.write_text(json.dumps([p.name for p in files]),encoding='utf-8')
        return files


def extract_field(text, pattern):
    match = re.search(pattern,text,re.I|re.S)
    return ' '.join(match[1].split()) if match else ''


def correction_date(text):
    """Yeni ihale tarihini etiketli alandan al; eski tarih/yayın/teslim tarihini kullanma."""
    normalized = normalize(text)
    section = re.split(r'duzeltilen\s+hususlar\s*:?|duzeltilecek\s+hususlar\s*:?', normalized)[-1]
    label = r'(?:ihale(?:nin)?\s+(?:tarih(?:i)?\s*(?:ve\s*saat(?:i)?)?|yapilacagi\s+tarih)|2\.1\.\s*tarih\s+ve\s+saati)\s*[:=]?\s*'
    date_pattern = r'\b(?:\d{1,2}[./]\d{1,2}[./]20\d{2}|\d{1,2}\s+(?:' + '|'.join(MONTHS) + r')\s+20\d{2})(?:\s*[-,]?\s*\d{1,2}[:.]\d{2})?'
    found = []
    for match in re.finditer(label, section):
        value = section[match.end():match.end()+220]
        value = re.split(r'\b(?:teslim\s+tarihi|ilan\s+tarihi|dokuman\s+teslim)',value,maxsplit=1)[0]
        # "Eski tarih ... yerine yeni tarih ..." değişiklik metninde yeni değeri seç.
        if 'yerine' in value:
            value = value.split('yerine',1)[1]
        date = re.match(r'[^\d]{0,35}(' + date_pattern + ')', value)
        if date and parse_date(date[1])[0]:
            found.append(date[1])
    return found[-1] if found else ''


def merge_record(old, incoming):
    """Geçmiş ilan güncel sonucu ezmez; kaynaklar ve çoklu yükleniciler korunur."""
    def order(row):
        date = parse_date(row.get('published_date_raw'))[0] or ''
        stage = {'ilan':0,'duzeltme':1,'sonuc':2,'iptal':3}.get(row.get('stage'),0)
        return date,stage
    old_order, incoming_order = order(old), order(incoming)
    if not old_order[0] or not incoming_order[0]:
        # Tarihi okunamayan eski ilan bir iptal veya sonucu yeniden açmasın.
        old_order, incoming_order = old_order[::-1], incoming_order[::-1]
    primary, other = (incoming,old) if incoming_order>=old_order else (old,incoming)
    merged = dict(primary)
    if old.get('id'):
        merged['id'] = old['id']
    for key in ('authority','tender_date_raw','tender_date_iso','date_precision'):
        if not merged.get(key) and other.get(key):
            merged[key]=other[key]
    refs = {}
    for row in (old,incoming):
        for ref in (row.get('bulletin_references') or []) + ([row['bulletin_reference']] if row.get('bulletin_reference') else []):
            refs[json.dumps(ref,sort_keys=True)]=ref
    merged['bulletin_references']=[refs[k] for k in sorted(refs)]
    contractors={}
    contacts={}
    for row in (old,incoming):
        for c in row.get('contractors') or []:
            contractors[json.dumps(c,sort_keys=True)]=c
        for c in row.get('contacts') or []:
            contacts[json.dumps(c,sort_keys=True)]=c
    merged['contractors']=[contractors[k] for k in sorted(contractors)]
    merged['contacts']=[contacts[k] for k in sorted(contacts)]
    if {'dogrudan':2,'potansiyel':1}.get(other.get('relevance'),0) > {'dogrudan':2,'potansiyel':1}.get(merged.get('relevance'),0):
        merged['relevance']=other['relevance']
        merged['matched_keywords']=other.get('matched_keywords',[])
        merged['match_basis']=other.get('match_basis','title')
        merged['match_evidence']=other.get('match_evidence')
    if merged.get('source_key') != 'ekap':
        events = {}
        fields = ('title','url','stage','published_date_raw','tender_date_raw','announcement_text','document_links')
        for row in (other,primary):
            for event in row.get('related_announcements', []):
                events[(event.get('url'),event.get('stage'))] = event
            if not row.get('related_announcements'):
                event = {k:row[k] for k in fields if k in row}
                events[(row.get('url'),row.get('stage'))] = event
        merged['related_announcements'] = [events[k] for k in sorted(events, key=lambda k: (k[0] or '',k[1] or ''))]
    if merged.get('relevance'):
        merged.pop('lifecycle_only',None)
    return merged


def parse_text(text, source, classify, filename, published):
    # İçindekilerdeki noktalı satırları dışla; ilan gövdesindeki numaralı başlıkları kullan.
    starts = list(re.finditer(r'^[ \t\f]*\d+\.[ \t]+(20\d{2}/\d+)[ \t]+([^\n]+)',text,re.M))
    starts = [m for m in starts if '...' not in m[2]]
    items = []
    for index, match in enumerate(starts):
        block = text[match.start():starts[index+1].start() if index+1<len(starts) else len(text)]
        # Son ilanın arkasındaki indeks kaydını ve sonraki bölümleri dahil etme.
        block = re.split(r'\n\s*(?:İHALE KAYIT NUMARASINA GÖRE|İNDEKS|İHALE İNDEKSİ)',block,maxsplit=1)[0]
        number = match[1]
        if not re.search(r'İhale\s+Kayıt\s+(?:Numarası|No)[^:]{0,30}:\s*'+re.escape(number),block,re.I):
            continue
        title = extract_field(block,r'3\.1\.\s*Ad[ıi]\s*:\s*(.*?)\s*3\.2\.')
        title = title or extract_field(block,r'2\s*[-.)]?\s*a\)\s*(?:Ad[ıi]|Niteliği[^:]*):\s*(.*?)\s*b\)') or match[2].strip()
        # PDF'in her sayfasında tekrarlanan üst/alt bilgileri alanlara karıştırma.
        block=re.sub(r'KAMU İHALE BÜLTENİ[^\n]*\n[^\n]*İHALELERİ BÜLTENİ[^\n]*\n\s*Kamu İhale Kurumu[^\n]*\n','',block)
        title=extract_field(block,r'3\.1\.\s*Ad[ıi]\s*:\s*(.*?)\s*3\.2\.') or extract_field(block,r'2\s*[-–]\s*İhale\s+konusu.{0,120}?a\)\s*Ad[ıi]\s*:\s*(.*?)\s*b\)') or title
        before_number = block[:re.search(r'İhale\s+Kayıt',block,re.I).start()]
        norm = normalize(before_number)
        stage = 'sonuc' if '_SONUC' in filename else 'iptal' if 'iptal' in norm else 'duzeltme' if 'duzeltme' in norm or 'duzeltilmistir' in norm else 'ilan'
        relevance, matches = classify(title)
        scope=extract_field(block,r'3\.2\.\s*Niteliği[^:]*:\s*(.*?)\s*3\.3\.')
        scope_kind,scope_matches=classify(scope)
        basis='title'
        if scope_kind=='dogrudan':
            relevance,matches,basis='dogrudan',scope_matches,'scope'
        # Uygulama kapsamındaki HVAC ifadesi hariç salt yıkım/çatı/araç/gıda işi satış adayı değildir.
        excluded=any(term in normalize(title) for term in ('yikim','cati','cephe boy','basketbol pota','basketbol saha','bisiklet yolu','akaryakit','sut sogutma','klimali arac','klimali otobus'))
        if excluded and scope_kind!='dogrudan':
            if stage not in ('iptal','duzeltme'):
                continue
            relevance,matches=None,[]
        if not relevance and not excluded and stage!='ilan' and 'YAPIM' in filename:
            relevance, matches = classify(title+' yapım')
        lifecycle_only = not relevance and stage in ('iptal','duzeltme')
        if not relevance and not lifecycle_only:
            continue
        authority = extract_field(block,r'1\.1\.\s*Ad[ıi]\s*:\s*(.*?)\s*1\.2\.')
        authority = authority or extract_field(block,r'1\s*[-.)]?\s*a\)\s*(?:Ad[ıi]|İdarenin adı)\s*:\s*(.*?)\s*b\)')
        raw_date = extract_field(block,r'2\.1\.\s*Tarih\s*ve\s*Saati\s*:\s*([\d./]+\s*[-,]?\s*\d{1,2}[:.]\d{2})') if stage=='ilan' else correction_date(block) if stage=='duzeltme' else ''
        if stage=='sonuc':
            raw_date=extract_field(block,r'1\s*[-–]\s*İhalenin\s*a\)\s*Tarihi\s*:\s*([\d./]+)')
            lines=[line.strip() for line in before_number.splitlines() if line.strip()]
            start=next((i for i,line in enumerate(lines) if re.search(r'MÜDÜRLÜĞÜ|BAŞKANLIĞI|REKTÖRLÜĞÜ|KOMUTANLIĞI|BELEDİYE|ÜNİVERSİTESİ',line)),None)
            if start is not None:
                authority=' '.join(lines[start:])
        contractors=[]
        name=extract_field(block,r'd\)\s*Yüklenicisi\s*:\s*(.*?)\s*e\)\s*Yüklenicinin') if stage=='sonuc' else ''
        if name:
            contract_part=re.split(r'4\s*[-–]\s*Sözleşmenin',block,maxsplit=1)[-1]
            period=extract_field(contract_part,r'c\)\s*Süresi\s*:\s*(.*?)\s*d\)')
            dates=re.findall(r'\b\d{2}[./]\d{2}[./]20\d{2}\b',period)
            contractors.append({'name':name,'address':extract_field(contract_part,r'f\)\s*Yüklenicinin\s*adresi\s*:\s*(.*?)\s*Kamuoyuna'),
                'contract_date_raw':extract_field(contract_part,r'a\)\s*Tarihi\s*:\s*([\d./]+)'),
                'contract_amount_raw':extract_field(contract_part,r'b\)\s*Bedeli\s*:\s*(.*?)\s*c\)'),
                'period_start_raw':dates[0] if len(dates)>=2 else None,'period_end_raw':dates[-1] if len(dates)>=2 else None,
                'source_url':URL,'bulletin_filename':filename})
        contacts=[]
        phone=extract_field(block,r'1\.3\.\s*Telefon\s*numarası\s*:\s*([+\d\s(),-]{7,60})(?=\s*\d\.\d\.|\n[^\d\s(),+-])')
        address=extract_field(block,r'1\.2\.\s*Adresi\s*:\s*(.*?)\s*1\.3\.')
        if phone or address:
            contacts.append({'role':'idare','name':authority,'phone':phone or None,'address':address or None,'email':None,'source_url':URL,'bulletin_filename':filename})
        contacts.extend({'role':'yuklenici','name':c['name'],'address':c['address'] or None,'phone':None,'email':None,'source_url':URL,'bulletin_filename':filename} for c in contractors)
        iso, precision = parse_date(raw_date)
        page_start = text.count('\f',0,match.start(1))+1
        items.append(dict(id=hashlib.sha256(('ekap|'+number).encode()).hexdigest()[:24],
            title=title,tender_number=number,authority=authority,source=source['name'],source_key='ekap',
            source_url=URL,url='https://ekapv2.kik.gov.tr/ekap/search/'+number.replace('/','_'),
            has_detail_url=True,stage=stage,tender_date_raw=raw_date,tender_date_iso=iso,date_precision=precision,
            published_date_raw=published,relevance=relevance,matched_keywords=matches,match_basis=basis,match_evidence=(scope[:1200] if basis=='scope' else title),needs_verification=True,
            contractors=contractors,contacts=contacts,procurement_type='Yapım' if 'YAPIM' in filename else 'Hizmet' if 'HIZMET' in filename else 'Mal',
            announcement_text=block[:60000],source_excerpt=block[:1500],
            acquisition_method='official_bulletin',bulletin_reference={'filename':filename,'published_date':published,'page_start':page_start}))
        if lifecycle_only:
            items[-1]['lifecycle_only'] = True
    return items,len(starts)


def progress_summary(source):
    path=STORE/'archive-progress.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    today=datetime.now(TR).date()
    target=min(365,max(min(7,max(1,source.get('bulletin_days',1))),source.get('archive_days',90)))
    done=sum((today-timedelta(days=i)).isoformat() in data.get('completed_dates',[]) for i in range(1,target))
    provisional = int(today.isoformat() in data.get('provisional_dates',[]))
    return {'target_days':target,'completed_days':done,'provisional_days':provisional,'remaining_days':target-done-provisional}


def collect(source, classify, on_batch=None):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError('EKAP bülteni için python -m pip install -r requirements.txt çalıştırın') from exc
    items, count, pages, warnings = {},0,0,[]
    STORE.mkdir(parents=True,exist_ok=True)
    progress_path=STORE/'archive-progress.json'
    progress=json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {'completed_dates':[]}
    today=datetime.now(TR).date()
    daily=min(7,max(1,source.get('bulletin_days',1)))
    target=min(365,max(daily,source.get('archive_days',90)))
    daily=max(daily,min(target,7,max(1,source.get('recheck_days',3))))
    # Bugünün yayını gün içinde değişebilir; kalıcı tamamlanmış gün değildir.
    progress['completed_dates']=[d for d in progress['completed_dates'] if d<today.isoformat()]
    progress['provisional_dates']=[d for d in progress.get('provisional_dates',[]) if d==today.isoformat()]
    offsets=list(range(daily))
    pending=[i for i in range(daily,target) if (today-timedelta(days=i)).isoformat() not in progress['completed_dates']]
    offsets+=pending[:max(1,min(30,source.get('backfill_batch_days',5)))]
    for offset in offsets:
        date = today-timedelta(days=offset)
        date_items={}
        date_ok=True
        print(f'EKAP bülten/sonuç: {date}',flush=True)
        for kind in ('Mal','Yapim','Hizmet'):
            try:
                files = download(kind,date)
                for file in files:
                    text_file=file.with_suffix('.txt')
                    if text_file.exists() and text_file.stat().st_mtime>=file.stat().st_mtime:
                        text=text_file.read_text(encoding='utf-8')
                        page_count=text.count('\f')+1
                    else:
                        from pdf_text import read_pdf
                        text,page_count,engine=read_pdf(file)
                        # Alan gövdesi çıkmazsa farklı PDF şablonunda güvenilir yavaş okuyucuya dön.
                        if not parse_text(text,source,classify,file.name,date.strftime('%d.%m.%Y'))[1] and engine!='pypdf':
                            text,page_count,engine=read_pdf(file,fast=False)
                        text_file.write_text(text,encoding='utf-8')
                    rows, examined = parse_text(text,source,classify,file.name,date.strftime('%d.%m.%Y'))
                    if not examined:
                        raise RuntimeError(f'{file.name}: beklenen ilan gövdesi bulunamadı')
                    count += examined
                    pages += page_count
                    for row in rows:
                        items[row['id']]=merge_record(items[row['id']],row) if row['id'] in items else row
                        date_items[row['id']]=merge_record(date_items[row['id']],row) if row['id'] in date_items else row
            except Exception as exc:
                date_ok=False
                warnings.append(f'{date} {kind}: {exc}')
        if on_batch and date_items:
            on_batch(list(date_items.values()))
        if date_ok:
            if date == today:
                progress['provisional_dates']=[date.isoformat()]
            else:
                progress['completed_dates']=sorted(set(progress['completed_dates']+[date.isoformat()]))
            progress_path.write_text(json.dumps(progress,ensure_ascii=False),encoding='utf-8')
        print(f'EKAP {date}: {sum(not row.get("lifecycle_only",False) for row in date_items.values())} satış adayı',flush=True)
    if not pages and warnings:
        raise RuntimeError('; '.join(warnings))
    return list(items.values()),count,pages,warnings
