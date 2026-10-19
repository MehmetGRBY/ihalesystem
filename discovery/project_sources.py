"""İhale dışındaki resmî yatırım ve devam eden yapı proje kaynakları."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from source_adapters import Tree, first, normalize, next_page, parse_date

CACHE=Path(__file__).resolve().parent/'data'/'project-cache'
BUILDINGS=('otel','hotel','hastane','konaklama','turizm tesisi','fabrika','uretim tesisi','alisveris merkezi','avm','ofis','konut','yurt','saglik tesisi','veri merkezi','lojistik merkezi')


def item(source,title,url,text,status,owner=None,published='',city=None):
    return dict(id=hashlib.sha256((source['key']+'|'+url+'|'+title).encode()).hexdigest()[:24],title=title,
        url=url,source=source['name'],source_key=source['key'],source_url=source['url'],stage='proje',
        has_detail_url=url!=source['url'],tender_date_raw='',tender_date_iso=None,date_precision=None,
        published_date_raw=published,source_status=status,project_owner=owner,authority=owner,
        city=city,relevance='potansiyel',matched_keywords=[w for w in BUILDINGS if w in normalize(title+' '+text[:1200])],
        needs_verification=True,announcement_text=text[:60000],source_excerpt=text[:1500],contacts=[],
        acquisition_method='official_project_page',match_basis='project')


def emlak_projects(html,source):
    rows=[]
    cards=list(Tree(html).root.walk(cls='single-p'))
    if not cards:
        raise ValueError('Emlak Konut proje kartları bulunamadı; sayfa yapısı değişmiş olabilir')
    for card in cards:
        classes = card.attrs.get('class','').split()
        status = 'Devam eden proje' if 'durum-devam-eden' in classes else 'Hemen teslim proje' if 'durum-hemen-teslim' in classes else 'Proje durumu belirsiz'
        title=first(card,cls='sing-title')
        location=first(card,cls='sing-loc')
        if not title or not title.text:
            raise ValueError('Emlak Konut kartında proje adı okunamadı; liste eksiksiz doğrulanamadı')
        record = item(source,title.text,source['url'],card.text,status,
            owner='Emlak Konut GYO — proje geliştirici listesi',city=location.text if location else None)
        record['source_presence'] = 'present'
        rows.append(record)
    return rows,len(cards)


def csb_detail(html,source,url):
    tree=Tree(html).root
    body=first(tree,cls='haber-detay-desc-wrapper')
    if not body:
        raise ValueError('ÇED duyuru gövdesi bulunamadı')
    text=body.text
    normalized=normalize(text)
    if not any(word in normalized for word in BUILDINGS):
        return None
    # Maden/enerji/altyapı duyuruları salt çevre onayı nedeniyle bina fırsatı sayılmaz.
    candidates=re.findall(r'[“‘"\']([^”’"\']{8,350})[”’"\']',text)
    title=next((x for x in candidates if any(w in normalize(x) for w in BUILDINGS)),None)
    if not title:
        title=extract_project_title(text)
    if not title:
        return None
    prefix=text.split('tarafından',1)[0]
    owner_match=re.search(r'(?:,|adresinde|içerisinde)\s*([^,]{3,240}(?:Ltd\.?\s*Şti\.?|A\.?Ş\.?|Anonim Şirketi|Limited Şirketi))\s*$',prefix,re.I)
    owner=' '.join(owner_match[1].split()) if owner_match else None
    published=''
    parent=body.parent
    for span in parent.walk('span') if parent else []:
        if parse_date(span.text)[0]:
            published=span.text
            break
    status='ÇED / planlama duyurusu'
    if 'ced olumsuz' in normalized or 'iptal' in normalized:
        return None
    record=item(source,title,url,text,status,owner,published,source.get('city'))
    # Metnin içindeki iletişimin yatırımcıya mı danışmana mı ait olduğu varsayılmaz.
    emails=sorted(set(re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',text)))
    record['contacts']=[{'role':'duyuru','name':None,'email':email,'phone':None,'address':None,'source_url':url} for email in emails]
    return record


def extract_project_title(text):
    match=re.search(r'((?:[^.!?]{0,120})(?:Otel|Hotel|Hastane|Üretim Tesisi|Fabrika|Konaklama|Turizm Tesisi)[^.!?]{0,180}(?:Projesi|projesi))',text,re.I)
    return ' '.join(match[1].split()) if match else None


def collect(source,classify,fetch):
    if source['adapter']=='emlak_projects':
        rows,count=emlak_projects(fetch(source['url']),source)
        return rows,count,1,[]
    rows,count,pages,warnings=[],0,0,[]
    page_url=source['url']
    seen=set()
    CACHE.mkdir(parents=True,exist_ok=True)
    import time
    for _ in range(min(5,source.get('max_pages',2))):
        if not page_url:
            break
        html=fetch(page_url)
        tree=Tree(html).root
        urls=[]
        for a in tree.walk('a'):
            href=urljoin(page_url,a.attrs.get('href',''))
            if re.search(r'-duyuru-\d+$',href) and urlsplit(href).netloc==urlsplit(source['url']).netloc and href not in seen:
                seen.add(href)
                urls.append((href,a.text))
        if not urls and not pages:
            raise ValueError('ÇED duyuru listesi bulunamadı')
        pages+=1
        for url,title in urls[:source.get('max_details',20)]:
            # Genel başlıklı ÇED duyurularında gerçek proje metni okunur.
            if 'ced' not in normalize(title) and not any(w in normalize(title) for w in BUILDINGS):
                continue
            count+=1
            try:
                path=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.html')
                if path.exists() and time.time()-path.stat().st_mtime<6*3600:
                    detail=path.read_text(encoding='utf-8')
                else:
                    detail=fetch(url)
                    path.write_text(detail,encoding='utf-8')
                record=csb_detail(detail,source,url)
                if record:
                    rows.append(record)
            except Exception as exc:
                warnings.append(f'{url}: {exc}')
        page_url=next_page(html,page_url)
    return list({r['id']:r for r in rows}.values()),count,pages,warnings
