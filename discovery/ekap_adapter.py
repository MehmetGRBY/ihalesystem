"""EKAP'ın halka açık arama ekranı; kullanıcı doğrulamasını çözmez."""
import hashlib
import re
import time
from pathlib import Path
from source_adapters import Tree, first, normalize, parse_date

PROFILE = Path(__file__).resolve().parent / 'data' / 'ekap-browser'
URL = 'https://ekapv2.kik.gov.tr/ekap/search'


class VerificationRequired(RuntimeError):
    pass


def parse_cards(html, source, classify, query=''):
    items, count = [], 0
    for card in Tree(html).root.walk():
        if card.attrs.get('id') != 'ihale-list-item':
            continue
        count += 1
        title, number = first(card, cls='ihale'), first(card, cls='ikn')
        authority, date = first(card, cls='idare'), first(card, cls='il-saat')
        if not title or not number or not re.fullmatch(r'20\d{2}/\d+', number.text):
            raise ValueError('EKAP ilan satırı değişmiş: başlık veya İKN okunamadı')
        relevance, matches = classify(title.text)
        if not relevance:
            continue
        badges = [n.text for n in card.walk(cls='badge')]
        status = badges[0] if badges else ''
        normalized = normalize(status)
        stage = 'iptal' if 'iptal' in normalized else 'sonuc' if 'sonuc' in normalized or 'sozlesme' in normalized else 'kapandi' if 'kapali' in normalized else 'ilan'
        raw_date = date.text.split(',', 1)[-1].strip() if date else ''
        iso, precision = parse_date(raw_date)
        item = dict(id=hashlib.sha256(('ekap|' + number.text).encode()).hexdigest()[:24],
            title=title.text, tender_number=number.text, authority=authority.text if authority else '',
            url=URL + '/' + number.text.replace('/', '_'), source=source['name'], source_key=source['key'],
            source_url=source['url'], has_detail_url=True, stage=stage, source_status=status,
            tender_date_raw=raw_date, tender_date_iso=iso, date_precision=precision,
            relevance=relevance, matched_keywords=matches, needs_verification=True,
            city=date.text.split(',', 1)[0].strip() if date and ',' in date.text else None,
            procurement_type=badges[1] if len(badges)>1 else None,
            procurement_procedure=badges[2] if len(badges)>2 else None,
            discovery_queries=[query] if query else [], source_excerpt=card.text)
        items.append(item)
    return items, count


def merge_items(existing, incoming):
    for item in incoming:
        old = existing.get(item['id'])
        if old:
            item['discovery_queries'] = sorted(set(old['discovery_queries'] + item['discovery_queries']))
        existing[item['id']] = item


def open_context(playwright, headless=True):
    PROFILE.mkdir(parents=True, exist_ok=True)
    # Botun kendi profili; kullanıcının kişisel tarayıcı profiline erişilmez.
    try:
        return playwright.chromium.launch_persistent_context(str(PROFILE), channel='msedge', headless=headless)
    except Exception as exc:
        raise RuntimeError('EKAP tarayıcısı açılamadı. Microsoft Edge kurulu olmalı; aynı bot profilini kullanan diğer işlemi kapatın. ' + str(exc).splitlines()[0]) from exc


def ready(page, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.locator('#ihale-list-item').count():
            return
        text = normalize(page.locator('body').inner_text())
        if 'guvenlik kontrolunu tamamlayin' in text or 'kisa bir guvenlik kontrolu' in text:
            raise VerificationRequired('EKAP kullanıcı doğrulaması istiyor. Botu durdurup python bulucu.py --ekap-setup çalıştırın; açılan Edge ekranında doğrulamayı kendiniz tamamlayın.')
        if re.search(r'\b0 ihale listelenmektedir|sonuc bulunamadi|kayit bulunamadi', text):
            return
        page.wait_for_timeout(500)
    raise RuntimeError('EKAP arama sonuçları yüklenemedi. python bulucu.py --ekap-setup ile tarayıcıda kontrol edin; kullanıcı doğrulaması, bağlantı veya sayfa yapısı engeli olabilir.')


def collect(source, classify):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('EKAP için python -m pip install -r requirements.txt çalıştırın') from exc
    items, count, pages, warnings = {}, 0, 0, []
    terms = source.get('search_terms') or ['klima', 'havalandırma', 'ısıtma', 'soğutma', 'VRF', 'mekanik tesisat']
    with sync_playwright() as p:
        context = open_context(p, source.get('headless', True))
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15000)
            for term in terms:
                try:
                    page.goto(source['url'], wait_until='domcontentloaded', timeout=45000)
                    ready(page)
                    # İlk açılış turu arama alanını kapatabilir.
                    tour = page.locator('button').filter(has_text='✕')
                    if tour.count() and tour.first.is_visible():
                        tour.first.click()
                    page.locator('#search-by-word input').fill(term)
                    # Liste boşalmadan eski sonuçları okumayı önle.
                    previous = page.locator('#ihale-list-item').all_inner_texts()
                    page.locator('button.search-button').click()
                    page.wait_for_function("old => JSON.stringify(Array.from(document.querySelectorAll('#ihale-list-item')).map(x=>x.innerText)) !== JSON.stringify(old)", arg=previous, timeout=30000)
                    ready(page)
                    for index in range(min(5, max(1, source.get('max_pages', 3)))):
                        batch, examined = parse_cards(page.content(), source, classify, term)
                        merge_items(items, batch)
                        count += examined
                        pages += 1
                        next_button = page.locator('[title="İleri"]')
                        if not examined or index + 1 == source.get('max_pages', 3) or not next_button.count() or not next_button.is_enabled():
                            break
                        previous = page.locator('#ihale-list-item').all_inner_texts()
                        next_button.click()
                        page.wait_for_function("old => JSON.stringify(Array.from(document.querySelectorAll('#ihale-list-item')).map(x=>x.innerText)) !== JSON.stringify(old)", arg=previous, timeout=30000)
                        ready(page)
                except VerificationRequired as exc:
                    if not pages:
                        raise
                    warnings.append(str(exc))
                    break
                except Exception as exc:
                    if not pages:
                        raise RuntimeError(f'EKAP {term}: {exc}') from exc
                    warnings.append(f'EKAP {term}: {exc}')
            if not pages:
                raise RuntimeError('; '.join(warnings) or 'EKAP araması tamamlanamadı')
        finally:
            context.close()
    return list(items.values()), count, pages, warnings


def setup():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        context = open_context(p, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(URL, wait_until='domcontentloaded', timeout=45000)
            print('Açılan Edge ekranında EKAP güvenlik doğrulamasını kendiniz tamamlayın. İhale listesi görünene kadar bekleniyor (5 dakika).', flush=True)
            page.locator('#ihale-list-item').first.wait_for(timeout=300000)
            print('EKAP listesi açıldı. Bot profili kaydedildi. Şimdi python bulucu.py ile başlatabilirsiniz.', flush=True)
        finally:
            context.close()
