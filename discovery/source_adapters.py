"""Açık kurum listeleri için kaynak bazında ayrıştırıcılar."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

TR = timezone(timedelta(hours=3))
MONTHS = {name: i + 1 for i, name in enumerate(['ocak','subat','mart','nisan','mayis','haziran','temmuz','agustos','eylul','ekim','kasim','aralik'])}


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.lower().replace('ı', 'i')) if not unicodedata.combining(c))


def parse_date(raw):
    """Yıl eksikse tahmin yapma. Saat yoksa gün sonu; kesinlik ayrıca belirtilir."""
    raw = normalize(raw or '')
    match = re.search(r'\b(\d{1,2})[./](\d{1,2})[./](20\d{2})(?:\s*[-,]?\s*(\d{1,2})[:.](\d{2}))?', raw)
    if match:
        day, month, year, hour, minute = match.groups()
    else:
        match = re.search(r'\b(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(20\d{2})(?:\s+(\d{1,2}):(\d{2}))?', raw)
        if not match:
            return None, None
        day, month, year, hour, minute = match.groups()
        month = MONTHS[month]
    try:
        value = datetime(int(year), int(month), int(day), int(hour) if hour else 23, int(minute) if minute else 59, tzinfo=TR)
        return value.isoformat(), 'minute' if hour else 'day'
    except ValueError:
        return None, None


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs or {}, parent
        self.children = []

    @property
    def text(self):
        return ' '.join(' '.join(c.text if isinstance(c, Node) else c for c in self.children).split())

    def walk(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()):
                    yield child
                yield from child.walk(tag, cls)


class Tree(HTMLParser):
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.current = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, dict(attrs), self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        if self.current.tag not in ('script', 'style'):
            self.current.children.append(data)


def first(node, tag=None, cls=None):
    return next(node.walk(tag, cls), None)


def extract_tender_number(text='', title=''):
    """Etiketli numarayı veya başlıktaki tek numarayı bul; kurum kapsamı ayrıca korunur."""
    normalized = normalize(text or '')
    match = re.search(r'(?:ihale kayit (?:numarasi|no)\s*(?:\(ikn\))?\s*[:.]?\s*|\bikn\s*:\s*)(20\d{2}\s*/\s*\d+)\b', normalized)
    if not match:
        match = re.search(r'\b(20\d{2}\s*/\s*\d+)\s*[’\']?\s*ikn\b', normalized)
    if match:
        return re.sub(r'\s+', '', match[1])
    numbers = set(re.findall(r'\b20\d{2}/\d+\b', title or ''))
    return next(iter(numbers)) if len(numbers) == 1 else ''


def make_item(source, title, href, classify, tender_date='', published='', stage=None, **extra):
    kind, matches = classify(title)
    url = urljoin(source['url'], href or '')
    if urlsplit(url).scheme not in ('http', 'https'):
        return None
    title_norm = normalize(title)
    if not stage:
        stage = 'iptal' if 'iptal' in title_norm else 'duzeltme' if any(w in title_norm for w in ['duzeltme', 'zeyilname']) else source.get('stage', 'ilan')
    if not extra.get('tender_number'):
        extra['tender_number'] = extract_tender_number(title=title)
    if not kind:
        if stage not in ('iptal','duzeltme') or not extra['tender_number']:
            return None
        # Genel başlıklı değişiklik ilgili eski kaydı kapatabilsin; tek başına fırsat değildir.
        extra['lifecycle_only'] = True
    ident = hashlib.sha256((source['key'] + '|' + url).encode()).hexdigest()[:24]
    return dict(id=ident, title=title, url=url, source=source['name'], source_url=source['url'],
                source_key=source['key'], stage=stage, tender_date_raw=tender_date,
                published_date_raw=published, relevance=kind, matched_keywords=matches,
                has_detail_url=bool(href), needs_verification=True, **extra)


def append(items, item):
    if item:
        items.append(item)


def parse(html, source, classify):
    tree = Tree(html).root
    adapter = source['adapter']
    items, count = [], 0
    if adapter == 'medipol':
        cards = list(tree.walk(cls='announcement-item'))
        count = len(cards)
        for card in cards:
            title_node = first(card, cls='announcements-title')
            link = first(card, 'a')
            if title_node and link:
                day = first(card, cls='announcements-date-day')
                month = first(card, cls='announcements-date-month')
                # Bu tarih yayın tarihidir; ihale tarihi değildir. Yıl tahmini yapılmaz.
                published = ' '.join(n.text for n in [day, month] if n)
                append(items, make_item(source, title_node.text, link.attrs.get('href'), classify, published=published))
    elif adapter == 'etu':
        cards = list(tree.walk(cls='ihaleler__list__item'))
        count = len(cards)
        for card in cards:
            link, date = first(card, 'a'), first(card, 'span')
            if link:
                append(items, make_item(source, link.text, link.attrs.get('href'), classify, published=date.text if date else ''))
    elif adapter == 'ankara':
        cards = list(tree.walk(cls='tender-list-item'))
        count = len(cards)
        for card in cards:
            title, link = first(card, 'strong'), first(card, 'a')
            attrs = {}
            for attr in card.walk(cls='attribute'):
                label, value = first(attr, 'label'), first(attr, 'span')
                if label and value:
                    attrs[normalize(label.text)] = value.text
            if title and link:
                append(items, make_item(source, title.text, link.attrs.get('href'), classify,
                    tender_date=attrs.get('ihale tarihi:', ''), tender_number=attrs.get('ihale kayit no:', ''),
                    authority=attrs.get('ilgili birim:', '')))
    elif adapter in ('istinye', 'ipkb', 'izmir'):
        for row in tree.walk('tr'):
            cells = [n for n in row.children if isinstance(n, Node) and n.tag == 'td']
            if adapter == 'istinye' and len(cells) == 3:
                link = first(cells[1], 'a')
                if link:
                    count += 1
                    append(items, make_item(source, cells[1].text, link.attrs.get('href'), classify, tender_date=cells[2].text, tender_number=cells[0].text))
            elif adapter == 'ipkb' and 'type-tender' in row.attrs.get('class', '') and len(cells) >= 5:
                link = first(cells[1], 'a')
                count += 1
                states = {'iptal': 'iptal', 'degerlendiriliyor': 'degerlendirme', 'tamamlandi': 'sonuc', 'kapandi': 'kapandi', 'silindi': 'kapandi', 'pasif': 'kapandi'}
                append(items, make_item(source, cells[1].text, link.attrs.get('href') if link else '', classify,
                    tender_date=cells[3].text, published=cells[2].text,
                    stage=states.get(normalize(cells[4].text), 'ilan'), source_status=cells[4].text))
            elif adapter == 'izmir' and len(cells) >= 8:
                link = first(cells[5], 'a')
                if link and '/IhaleDetay/' in link.attrs.get('href', ''):
                    count += 1
                    append(items, make_item(source, link.text, link.attrs.get('href'), classify,
                        tender_date=cells[7].text, authority=cells[4].text, source_status=cells[6].text,
                        date_label='Son teklif tarihi'))
        # İzmir'in ayrı ihale dokümanı tabloları (PDF/DOCX bağlantıları).
        if adapter == 'izmir':
            for link in tree.walk('a'):
                href = link.attrs.get('href', '')
                if '/Ihaleler/' in href and re.search(r'\.(pdf|docx?)$', href, re.I):
                    count += 1
                    append(items, make_item(source, link.text, href, classify, document_url=href, date_label='İhale tarihi'))
    elif adapter == 'tki':
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not match:
            raise ValueError('TKİ sayfa verisi bulunamadı')
        data = json.loads(match[1])['props']['pageProps']['payload']['data']
        count = len(data)
        for row in data:
            meta = row.get('meta') or {}
            timestamp = meta.get('datetime')
            date = datetime.fromtimestamp(timestamp / 1000, TR).strftime('%d.%m.%Y %H:%M') if timestamp else ''
            append(items, make_item(source, row['title'], '/ihaleler/' + row['slug'], classify, tender_date=date,
                source_status=(meta.get('status') or {}).get('title', '')))
    else:
        raise ValueError('Desteklenmeyen kaynak adaptörü: ' + adapter)
    if not count:
        raise ValueError('Beklenen ilan listesi bulunamadı; kaynak boş veya sayfa yapısı değişmiş olabilir')
    # PDF tekrarları ve sayfalar arası tekrarlar tek kayıt olur.
    items = list({item['id']: item for item in items}.values())
    return items, count


def next_page(html, current_url):
    tree = Tree(html).root
    for link in tree.walk('a'):
        title = normalize(link.text)
        classes = link.attrs.get('class', '').split()
        rel = link.attrs.get('rel', '').split()
        if 'next' in rel or 'next' in classes or title in ('sonraki', 'next', 'sonraki sayfa', 'next page') or 'pager__item--next' in (link.parent.attrs.get('class', '') if link.parent else ''):
            href = urljoin(current_url, link.attrs.get('href', ''))
            if urlsplit(href).netloc == urlsplit(current_url).netloc and href != current_url:
                return href
    return None


def detail_date(html):
    tree = Tree(html).root
    text = tree.text
    # İlan tarihi ve doküman teslim tarihi ile karıştırmadan etiketli tarih alanları.
    normalized = normalize(text)
    labels = [r'ihale tarihi\s*:', r'ihalenin yapilacagi tarih\s*:', r'ihale ve teklif acma tarihi\s*:', r'ihale ve teklif acma tarihi ve saati\s*:', r'ihale \(son teklif verme\) tarih ve saati\s*:', r'\b3\.?\s*ihalenin.{0,350}?\b[b-c]\s*[-.)]*\s*tarihi ve saati\s*:']
    for label in labels:
        match = re.search(label, normalized)
        if match:
            raw = normalized[match.end():match.end() + 90]
            date_match = re.search(r'\b\d{1,2}[./]\d{1,2}[./]20\d{2}(?:\s*[-,]?\s*\d{1,2}[:.]\d{2})?|\b\d{1,2}\s+(?:' + '|'.join(MONTHS) + r')\s+20\d{2}(?:\s+\d{1,2}:\d{2})?', raw)
            if date_match:
                return date_match[0]
    return ''


def detail_info(html):
    tree = Tree(html).root
    # İlan gövdesi varsa menü ve genel kurum iletişimini çıktıya karıştırma.
    body = first(tree, cls='body') or first(tree, 'article') or first(tree, 'main')
    date = first(tree, 'span', 'date')
    number = extract_tender_number((body or tree).text)
    documents = []
    for link in (body or tree).walk('a'):
        href = link.attrs.get('href', '')
        if re.search(r'\.(?:pdf|docx?|xlsx?|zip)(?:[?#]|$)', href, re.I):
            documents.append({'url': href, 'label': link.text})
    return {'tender_date_raw': detail_date(html), 'published_date_raw': date.text if date else '',
            'tender_number': number,
            'announcement_text': body.text[:60000] if body else '',
            'document_links': documents}


def transfer_record(item):
    """Keşif verisini sabit alanlarla sun; eksik bilgiyi tahmin etme."""
    item = dict(item)
    for key in ('tender_number', 'authority', 'published_date_raw', 'announcement_text'):
        item[key] = item.get(key) or None
    links = list(item.get('document_links') or [])
    if item.get('document_url'):
        links.append({'url': item['document_url'], 'label': item['title']})
    unique = {}
    for link in links:
        url = urljoin(item['url'], link['url'])
        if urlsplit(url).scheme in ('http', 'https'):
            unique[url] = {'url': url, 'label': link.get('label', '')}
    item['document_links'] = list(unique.values())
    item['detail_url'] = item['url'] if item.get('has_detail_url') and not item.get('document_url') else None
    item['missing_fields'] = [key for key in ('tender_number', 'authority', 'tender_date_iso', 'announcement_text') if not item.get(key)]
    item['evidence'] = {'list_url': item['source_url'], 'detail_url': item['detail_url'],
                        'title': item['title'], 'date_raw': item.get('tender_date_raw') or None}
    return item


def freshness(item, current=None):
    if item.get('stage') in ('iptal', 'kapandi', 'sonuc'):
        return 'kapali'
    parsed = item.get('tender_date_iso')
    if not parsed:
        return 'tarih_belirsiz'
    try:
        return 'tarih_gecmis' if datetime.fromisoformat(parsed) < (current or datetime.now(TR)) else 'yaklasan'
    except ValueError:
        return 'tarih_belirsiz'
