import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bulucu

SOURCE = {"name": "TOKİ", "url": "https://www.toki.gov.tr/ihale-tarihleri", "stage": "ilan"}


class Tests(unittest.TestCase):
    def test_relevance(self):
        self.assertEqual(bulucu.classify("KLİMA VE HAVALANDIRMA ALIMI")[0], "dogrudan")
        self.assertEqual(bulucu.classify("Hastane binası inşaatı")[0], "potansiyel")
        self.assertIsNone(bulucu.classify("Hastane yemek hizmet alımı")[0])
        self.assertIsNone(bulucu.classify("Özel güvenlik hizmeti")[0])

    def test_rows_with_and_without_links(self):
        html = '<tr><td>1</td><td><a href="/ihale-tarihleri/1">Okul inşaatı</a></td><td>0</td><td>12 Ekim 2026</td></tr><tr><td>2</td><td>Hastane inşaatı</td><td>0</td><td>15 Ekim 2026</td></tr>'
        items = bulucu.parse_toki(html, SOURCE)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["has_detail_url"])
        self.assertFalse(items[1]["has_detail_url"])
        self.assertNotEqual(items[0]["id"], items[1]["id"])

    def test_dedup_and_date_update(self):
        with tempfile.TemporaryDirectory(dir=bulucu.ROOT) as folder:
            with patch.object(bulucu, "DATA", Path(folder)), patch.object(bulucu, "DB", Path(folder) / "test.sqlite3"):
                item = bulucu.parse_toki('<tr><td>1</td><td>Okul inşaatı</td><td>0</td><td>12 Ekim</td></tr>', SOURCE)[0]
                with bulucu.connect() as conn:
                    self.assertEqual(bulucu.save_items(conn, [item]), (1, 0))
                    self.assertEqual(bulucu.save_items(conn, [item]), (0, 0))
                    item["tender_date_raw"] = "15 Ekim"
                    self.assertEqual(bulucu.save_items(conn, [item]), (0, 1))
                self.assertEqual(len(bulucu.records()), 1)
                self.assertEqual(bulucu.records()[0]["revision"], 2)

    def test_failed_source_is_visible(self):
        with tempfile.TemporaryDirectory(dir=bulucu.ROOT) as folder:
            with patch.object(bulucu, "DATA", Path(folder)), patch.object(bulucu, "DB", Path(folder) / "test.sqlite3"), patch.object(bulucu, "fetch", side_effect=OSError("ağ yok")), patch('ekap_adapter.collect', side_effect=OSError('ağ yok')), patch('ekap_bulletin.collect', side_effect=OSError('ağ yok')):
                result = bulucu.scan()
                self.assertTrue(all(s["status"] in ("error", "disabled") for s in result["sources"]))
                self.assertEqual(bulucu.records(), [])


if __name__ == "__main__":
    unittest.main()
