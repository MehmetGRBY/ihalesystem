"""Resmî şirket sitelerinden doğrulanmış, sınırlı iletişim eşleştirmeleri.

Genel firma adı araması yapmaz. Liste dışındaki şirketlerin iletişimini tahmin etmez.
"""
import re
from source_adapters import normalize

DIRECTORY = [
    ('wox yapı anonim şirketi', None, 'info@woxyapi.com.tr', 'https://www.woxyapi.com.tr/tr/iletisim.html', 'şirket merkezi'),
    ('nena grup endüstriyel makine inşaat sanayi ve ticaret anonim şirketi', '0312 490 93 92', 'info@nenagrup.com', 'https://nenagrup.com/iletisim/', 'grup merkezi'),
    ('mikrotek tıbbi cihazlar ve havalandırma sistemleri inşaat sanayi ticaret limited şirketi', '0212 222 35 44', 'info@mikrotekair.com.tr', 'https://www.mikrotekair.com.tr/en/contact/', 'şirket merkezi'),
    ('akar taahhüt yapı inşaat sanayi ve ticaret anonim şirketi', '0216 507 11 07', 'info@akartaahhutyapi.com', 'https://www.akartaahhutyapi.com/', 'şirket merkezi'),
]


def key(value):
    return ' '.join(re.findall(r'[a-z0-9]+', normalize(value)))


def enrich(item):
    item = dict(item)
    contacts = [c for c in item.get('contacts', []) if c.get('acquisition_method') != 'verified_company_directory']
    for contractor in item.get('contractors', []):
        name = contractor.get('name', '')
        # Ortak girişimin üyeleri ayrı şirketler olabilir. Tam unvan sınırı gerekir.
        candidate = ' ' + key(name) + ' '
        for legal, phone, email, url, scope in DIRECTORY:
            if ' ' + key(legal) + ' ' not in candidate:
                continue
            contacts.append(dict(role='yuklenici', name=legal.title(), phone=phone,
                                 email=email, address=None, source_url=url,
                                 acquisition_method='verified_company_directory',
                                 verification_status='published_on_matched_company_site',
                                 checked_at='2026-10-13', contact_scope=scope,
                                 note='Genel merkez iletişimi; proje satınalma yetkilisi henüz doğrulanmadı.'))
    item['contacts'] = contacts
    return item
