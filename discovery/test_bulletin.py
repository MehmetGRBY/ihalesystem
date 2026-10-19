import unittest
import tempfile
from pathlib import Path
from datetime import date
from unittest.mock import patch
import ekap_bulletin
from bulucu import classify
from ekap_bulletin import parse_text, form_fields

SOURCE={'name':'EKAP Bülteni'}
BODY='''1. 2026/100 KLİMA ALINACAKTIR
İhale Kayıt Numarası (İKN) : 2026/100
1- İdarenin
1.1. Adı : Örnek Hastane
1.2. Adresi : İstanbul
2- İhalenin
2.1. Tarih ve Saati : 27.10.2026 - 10:30
2.2. Yapılacağı adres : İstanbul
3- İhale konusu
3.1. Adı : VRF Klima
Sistemleri Alımı
3.2. Niteliği, türü ve miktarı : 2 cihaz
3.4. Süresi/teslim tarihi : 01.12.2026
'''


class BulletinTests(unittest.TestCase):
    def test_unpublished_day_is_cached_without_error(self):
        def fake_curl(args):
            path=Path(args[args.index('-o')+1])
            html='<p>11.10.2026 tarihinde Kamu İhale Bülteni yayımlanmamıştır!</p>' if '--data-binary' in args else '<input type="hidden" name="__VIEWSTATE" value="state"><select name="kind"><option value="2">Yapım</option></select>'
            path.write_text(html,encoding='utf-8')
        with tempfile.TemporaryDirectory(dir=ekap_bulletin.ROOT) as folder:
            with patch.object(ekap_bulletin,'STORE',Path(folder)),patch.object(ekap_bulletin,'curl',side_effect=fake_curl) as mocked:
                self.assertEqual(ekap_bulletin.download('Yapim',date(2026,10,11)),[])
                calls=mocked.call_count
                self.assertEqual(ekap_bulletin.download('Yapim',date(2026,10,11)),[])
                self.assertEqual(mocked.call_count,calls)

    def test_body_not_toc_and_correct_deadline(self):
        rows,count=parse_text('1. 2026/100 KLİMA ALINACAKTIR ........ 5\n\f'+BODY,SOURCE,classify,'BULTEN_12102026_MAL.pdf','12.10.2026')
        self.assertEqual((len(rows),count),(1,1))
        self.assertEqual(rows[0]['title'],'VRF Klima Sistemleri Alımı')
        self.assertEqual(rows[0]['authority'],'Örnek Hastane')
        self.assertEqual(rows[0]['tender_date_iso'],'2026-10-27T10:30:00+03:00')
        self.assertEqual(rows[0]['bulletin_reference']['page_start'],2)
        self.assertIn('2 cihaz',rows[0]['announcement_text'])

    def test_cancel_and_distinct_ikn(self):
        text=BODY.replace('İhale Kayıt','İhale iptal edilmiştir.\nİhale Kayıt')
        rows,_=parse_text(text,SOURCE,classify,'BULTEN_12102026_MAL.pdf','12.10.2026')
        self.assertEqual(rows[0]['stage'],'iptal')
        self.assertIsNone(rows[0]['tender_date_iso'])
        second,_=parse_text(BODY.replace('2026/100','2026/101'),SOURCE,classify,'BULTEN_12102026_MAL.pdf','12.10.2026')
        self.assertNotEqual(rows[0]['id'],second[0]['id'])

    def test_form_fields_ignore_login_and_nonhidden(self):
        fields=form_fields('<input name="__VIEWSTATE" type="hidden" value="a&amp;b"><input name="login" type="submit"><input name="date" type="text">')
        self.assertEqual(fields,{'__VIEWSTATE':'a&b'})


if __name__=='__main__':
    unittest.main()
