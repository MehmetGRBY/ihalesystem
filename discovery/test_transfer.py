import unittest
from source_adapters import detail_info, transfer_record


class TransferTests(unittest.TestCase):
    def test_scoped_text_and_documents(self):
        info = detail_info('<main><div class="body">İhale kayıt numarası: 2026/54 <a href="/a.pdf">Şartname</a></div></main><footer>Genel iletişim</footer>')
        self.assertEqual(info['tender_number'], '2026/54')
        self.assertNotIn('Genel iletişim', info['announcement_text'])
        record = transfer_record(dict(info, title='Klima', url='https://example.org/ilan', source_url='https://example.org/list', has_detail_url=True))
        self.assertEqual(record['document_links'][0]['url'], 'https://example.org/a.pdf')
        self.assertIn('authority', record['missing_fields'])

    def test_list_only_does_not_invent_detail(self):
        record = transfer_record(dict(title='Hastane yapımı', url='https://example.org/list', source_url='https://example.org/list', has_detail_url=False))
        self.assertIsNone(record['detail_url'])
        self.assertIsNone(record['tender_number'])
        self.assertEqual(record['document_links'], [])
        self.assertEqual(record['evidence']['title'], 'Hastane yapımı')


if __name__ == '__main__':
    unittest.main()
