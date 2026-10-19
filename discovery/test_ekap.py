import unittest
from unittest.mock import Mock
from bulucu import classify
from ekap_adapter import parse_cards, merge_items, ready, VerificationRequired

SOURCE = {'key':'ekap','name':'EKAP','url':'https://ekapv2.kik.gov.tr/ekap/search'}


def card(number='2026/54', title='VRF Klima Alımı', status='Katılıma Açık'):
    return f'<div id="ihale-list-item"><span class="badge">{status}</span><span class="badge">Mal</span><span class="badge">Açık</span><span class="ikn">{number}</span><span class="ihale">{title}</span><span class="idare">Örnek Hastane</span><span class="il-saat">İSTANBUL, 19.10.2026 11:00</span></div>'


class EkapTests(unittest.TestCase):
    def test_security_challenge_is_not_an_empty_success(self):
        page = Mock()
        page.locator.return_value.count.return_value = 0
        page.locator.return_value.inner_text.return_value = 'Kısa bir güvenlik kontrolü Devam etmek için güvenlik kontrolünü tamamlayın.'
        with self.assertRaises(VerificationRequired):
            ready(page)

    def test_explicit_empty_results_are_allowed(self):
        page = Mock()
        page.locator.return_value.count.return_value = 0
        page.locator.return_value.inner_text.return_value = '0 ihale listelenmektedir.'
        ready(page)

    def test_fields_and_cancelled(self):
        rows, count = parse_cards(card(status='İhale İptal Edilmiş'), SOURCE, classify, 'klima')
        self.assertEqual(count,1)
        self.assertEqual(rows[0]['stage'],'iptal')
        self.assertEqual(rows[0]['tender_number'],'2026/54')
        self.assertEqual(rows[0]['authority'],'Örnek Hastane')
        self.assertEqual(rows[0]['tender_date_iso'],'2026-10-19T11:00:00+03:00')
        self.assertTrue(rows[0]['url'].endswith('/2026_54'))

    def test_query_duplicates_and_distinct_tenders(self):
        store = {}
        for term in ['klima','VRF']:
            merge_items(store,parse_cards(card(),SOURCE,classify,term)[0])
        self.assertEqual(len(store),1)
        self.assertEqual(next(iter(store.values()))['discovery_queries'],['VRF','klima'])
        merge_items(store,parse_cards(card(number='2026/55'),SOURCE,classify)[0])
        self.assertEqual(len(store),2)

    def test_irrelevant_and_changed_markup(self):
        rows, count = parse_cards(card(title='Akaryakıt Alımı'),SOURCE,classify)
        self.assertEqual((rows,count),([],1))
        with self.assertRaises(ValueError):
            parse_cards(card(number='belirsiz'),SOURCE,classify)


if __name__=='__main__':
    unittest.main()
