import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import bulucu
import source_adapters as a


def source(adapter, key='kurum'):
    return {'adapter': adapter, 'key': key, 'name': key, 'url': 'https://example.com/ihaleler', 'stage': 'ilan'}


class AdapterTests(unittest.TestCase):
    def test_medipol_publish_date_is_not_deadline(self):
        html = '<div class="announcement-item"><span class="announcements-date-day">07</span><span class="announcements-date-month">Eylül</span><p class="announcements-title">VRF Alımı İhalesi İptal Kararı</p><a href="/ihaleler/1" aria-label="VRF Alımı"></a></div>'
        items, count = a.parse(html, source('medipol'), bulucu.classify)
        self.assertEqual(count, 1)
        self.assertEqual(items[0]['stage'], 'iptal')
        self.assertEqual(items[0]['tender_date_raw'], '')
        self.assertEqual(items[0]['published_date_raw'], '07 Eylül')

    def test_detail_date_context_excludes_delivery_date(self):
        html = '<p>2. Teslim Tarihi: 01.04.2026</p><p>3. İhalenin</p><p>a. Yapılacağı yer: Ankara</p><p>b. Tarihi ve saati:08/09/2026- 11:00</p>'
        self.assertEqual(a.detail_date(html), '08/09/2026- 11:00')
        self.assertEqual(a.parse_date(a.detail_date(html))[0], '2026-09-08T11:00:00+03:00')

    def test_ipkb_uses_description_and_status(self):
        html = '<tr class="type-tender"><td>Müteahhitlik</td><td><a href="/ihale/abc">ABC-01</a><p>Eğitim Yapıları Yeniden Yapım İnşaatı</p></td><td>01.10.2026</td><td>17.11.2026</td><td>İptal</td></tr>'
        items, count = a.parse(html, source('ipkb'), bulucu.classify)
        self.assertEqual(count, 1)
        self.assertIn('Eğitim Yapıları', items[0]['title'])
        self.assertEqual(items[0]['stage'], 'iptal')

    def test_izmir_document_dedup_and_condensers(self):
        html = '<tr>' + '<td>x</td>' * 5 + '<td><a href="/tr/IhaleDetay/1">KONDERSERLERİN MONTAJLI ALIMI</a></td><td>Teklif</td><td>12.10.2026 14:00</td></tr><a href="https://example.com/Ihaleler/sartname.docx">MEKANİK TESİSAT SARF MALZEME ALIMI</a><a href="https://example.com/Ihaleler/sartname.docx">MEKANİK TESİSAT SARF MALZEME ALIMI</a>'
        items, count = a.parse(html, source('izmir'), bulucu.classify)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['tender_date_raw'], '12.10.2026 14:00')
        self.assertTrue(items[1]['document_url'].endswith('.docx'))

    def test_different_authorities_same_title_are_distinct(self):
        title = 'Klima alımı'
        one = a.make_item(source('etu', 'one'), title, '/1', bulucu.classify)
        two = a.make_item(source('etu', 'two'), title, '/1', bulucu.classify)
        self.assertNotEqual(one['id'], two['id'])

    def test_date_and_closed_status(self):
        self.assertEqual(a.parse_date('12 Ekim 2026 10:30')[0], '2026-10-12T10:30:00+03:00')
        self.assertEqual(a.parse_date('07 Eylül'), (None, None))
        self.assertEqual(a.parse_date('31.02.2026'), (None, None))
        future = {'stage': 'iptal', 'tender_date_iso': '2027-10-12T10:30:00+03:00'}
        self.assertEqual(a.freshness(future), 'kapali')
        self.assertEqual(a.freshness({'stage':'ilan','tender_date_iso':'2020-10-12T10:30:00+03:00'}), 'tarih_gecmis')

    def test_valid_list_without_relevant_items_is_success(self):
        html = '<li class="ihaleler__list__item"><span>12.10.2026</span><a href="/1">Yemek alımı</a></li>'
        self.assertEqual(a.parse(html, source('etu'), bulucu.classify), ([], 1))
        with self.assertRaises(ValueError):
            a.parse('<html>Request Rejected</html>', source('etu'), bulucu.classify)

    def test_pagination_stays_same_host_and_preserves_first_page(self):
        self.assertIsNone(a.next_page('<a rel="next" href="https://other.example/2">Sonraki</a>', 'https://example.com/1'))
        html = '<li class="ihaleler__list__item"><span>12.10.2026</span><a href="/1">Klima alımı</a></li><a rel="next" href="?page=2">Sonraki</a>'
        config = dict(source('etu'), max_pages=3)
        with patch.object(bulucu, 'fetch', side_effect=[html, OSError('sayfa 2 hatası')]):
            items, count, pages, warnings = bulucu.collect_source(config)
        self.assertEqual(len(items), 1)
        self.assertEqual(pages, 1)
        self.assertTrue(warnings)


if __name__ == '__main__':
    unittest.main()
