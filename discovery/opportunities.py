"""Keşif kayıtlarını kaynak kanıtına dayalı satış takip fırsatlarına dönüştürür."""
from datetime import datetime, timedelta
from urllib.parse import quote
from source_adapters import TR, parse_date
from source_adapters import normalize


def enrich(item, current=None):
    item = dict(item)
    current = current or datetime.now(TR)
    contacts = list(item.get('contacts') or [])
    contractors = list(item.get('contractors') or [])
    item['contacts'] = contacts
    item['contractors'] = contractors
    direct = item.get('relevance') == 'dogrudan'
    title_match = item.get('match_basis', 'title')
    reason = ('İş kapsamında klima/ısıtma-soğutma ifadesi var; teknik kapsam doğrulanmalı.' if title_match == 'scope' else 'Başlık iklimlendirme işine işaret ediyor; kapsam doğrulanmalı.') if direct else 'Bina/yatırım projesinde HVAC ihtiyacı olabilir; mekanik kapsam henüz doğrulanmadı.'
    stage = item.get('stage')
    published, _ = parse_date(item.get('published_date_raw'))
    age = (current - datetime.fromisoformat(published)).days if published else None
    target = item.get('authority') or item.get('project_owner')
    target_role = 'İdare / satınalma birimi'
    kind, status, priority = 'ihale', 'kontrol', 50 if direct else 35
    next_action = 'Kaynak ilanı ve teknik kapsamı doğrula; satınalma veya mekanik işler sorumlusunu bul.'
    if stage in ('iptal','kapandi'):
        status,priority='arsiv',0
        next_action='İptal/kapalı kayıt; yeni ilan veya projenin devamına ilişkin kanıt bekle.'
    elif stage == 'proje':
        kind='yatirim_projesi'
        status='kontrol' if age is None or age<=180 else 'arsiv'
        priority=55 if status!='arsiv' else 0
        target=item.get('project_owner') or target
        target_role='Yatırımcı / proje satınalma veya mekanik yüklenici'
        next_action='Projenin ilerleme durumunu ve HVAC satınalmasını doğrula; yatırımcı veya mekanik yükleniciye ulaş.'
        if item.get('source_presence') == 'missing':
            status,priority='kontrol',20
            reason='Proje son başarılı kaynak listesinde bulunamadı; güncel aşaması doğrulanmalı.'
            next_action='Resmî kaynaktan proje durumunu yeniden doğrula; tamamlandığı veya satınalmanın açık olduğu varsayılmamalı.'
        elif item.get('source_status') == 'Hemen teslim proje':
            status,priority='arsiv',0
            reason='Kaynak proje için hemen teslim bilgisi yayımlıyor; yeni HVAC ihtiyacı ayrıca doğrulanmalı.'
            next_action='Teslime hazır proje; yeni satınalma veya bakım ihtiyacına ilişkin kanıt bekle.'
        elif item.get('source_status') == 'Devam eden proje':
            status,priority='proje',65
    elif stage == 'sonuc':
        kind='yuklenici'
        target='; '.join(c['name'] for c in contractors if c.get('name')) or None
        target_role='İşi alan yüklenici / proje satınalma birimi'
        ends = [parse_date(c.get('period_end_raw'))[0] for c in contractors]
        known_ends = [datetime.fromisoformat(x) for x in ends if x]
        if item.get('procurement_type')=='Mal':
            kind,status,priority='tesis_takibi','arsiv',15
            target=item.get('authority')
            target_role='İdare / tesis teknik birimi'
            next_action='Mal alımı sonuçlanmış; yeni ihtiyaç veya bakım fırsatı için ayrıca kanıt gerekir.'
        elif known_ends and all(x<current for x in known_ends):
            status,priority='arsiv',10
            next_action='Yayımlanan sözleşme bitiş tarihi geçmiş; ek iş veya yeni ihtiyaç ayrıca doğrulanmalı.'
        elif contractors and (age is None or age<=90 or any(x>=current for x in known_ends)):
            status='yuklenici'
            priority=85 if direct else 70
            next_action='Yüklenicinin kurumsal iletişimini doğrula; HVAC tedariki ve montajının henüz satın alınıp alınmadığını öğren.'
        else:
            status,priority='kontrol' if age is None or age<=90 else 'arsiv',30
            next_action='Sonuç ilanından yükleniciyi ve proje ilerleme durumunu tamamla.'
    elif item.get('freshness')=='yaklasan':
        status,priority='teklif',90 if direct else 60
        next_action='İhale kapsamını ve son teklif tarihini doğrula; doğrudan teklif veya ana yükleniciyle çalışma yolunu değerlendir.'
    elif item.get('freshness')=='tarih_gecmis' or stage=='degerlendirme':
        kind='sonuc_takibi'
        status,priority=('takip',45) if age is None or age<=90 else ('arsiv',0)
        next_action='Teklif tarihi geçmiş; sonuç ilanından işi alan yükleniciyi bul. Projenin sürdüğü varsayılmamalı.'
    elif age is not None and age>180:
        status,priority='arsiv',0
    if item.get('match_basis')!='scope' and any(term in normalize(item.get('title','')) for term in ('sut sogutma','bisiklet yolu','basketbol saha','basketbol pota','yikim','klimali otobus','klimali arac')):
        status,priority='arsiv',0
        reason='HVAC satış kapsamı dışında görünen iş; arşivde tutuluyor.'
    item['opportunity']={'kind':kind,'status':status,'priority':priority,'reason':reason,'target_name':target,
        'target_role':target_role,'next_action':next_action,'hvac_scope_confirmed':False}
    item['contact_search_url'] = 'https://www.google.com/search?q='+quote(target+' kurumsal iletişim') if target else None
    target_contacts=[c for c in contacts if c.get('role')==('yuklenici' if kind=='yuklenici' else 'idare') and (c.get('phone') or c.get('email'))]
    item['missing_sales_fields']=[k for k,missing in [('target_name',not target),('target_phone_or_email',not target_contacts),('hvac_scope',True)] if missing]
    return item
