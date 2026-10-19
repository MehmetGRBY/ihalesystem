import unittest
from datetime import datetime
from opportunities import enrich
from source_adapters import TR
from ekap_bulletin import merge_record,parse_text
from project_sources import emlak_projects,csb_detail
from bulucu import classify

NOW=datetime(2026,10,12,12,tzinfo=TR)


class OpportunityTests(unittest.TestCase):
    def test_award_is_sales_lead_even_when_tender_closed(self):
        item=dict(stage='sonuc',freshness='kapali',relevance='potansiyel',published_date_raw='12.10.2026',procurement_type='Yapım',contractors=[{'name':'Örnek İnşaat','period_end_raw':'01.10.2027'}],contacts=[{'role':'idare','phone':'02120000000'}])
        result=enrich(item,NOW)
        self.assertEqual(result['opportunity']['status'],'yuklenici')
        self.assertEqual(result['opportunity']['target_name'],'Örnek İnşaat')
        self.assertIn('target_phone_or_email',result['missing_sales_fields'])

    def test_cancelled_and_finished_contract_are_archive(self):
        self.assertEqual(enrich({'stage':'iptal'},NOW)['opportunity']['status'],'arsiv')
        result=enrich(dict(stage='sonuc',contractors=[{'name':'A','period_end_raw':'01.10.2025'}]),NOW)
        self.assertEqual(result['opportunity']['status'],'arsiv')

    def test_old_notice_cannot_overwrite_new_award(self):
        old={'stage':'sonuc','published_date_raw':'12.10.2026','contractors':[{'name':'A'}]}
        incoming={'stage':'ilan','published_date_raw':'01.09.2026','authority':'İdare'}
        merged=merge_record(old,incoming)
        self.assertEqual(merged['stage'],'sonuc')
        self.assertEqual(merged['authority'],'İdare')
        self.assertEqual(len(merged['contractors']),1)
        self.assertEqual(merge_record(merged,incoming),merged)

    def test_multiple_contractors_preserved(self):
        a={'stage':'sonuc','published_date_raw':'12.10.2026','contractors':[{'name':'A'}]}
        b={'stage':'sonuc','published_date_raw':'12.10.2026','contractors':[{'name':'B'}]}
        self.assertEqual(len(merge_record(a,b)['contractors']),2)

    def test_result_template_extracts_winner_and_period(self):
        text='''1. 2026/123 BİNA İNŞAATI YAPTIRILACAKTIR
BİNA İNŞAATI YAPTIRILACAKTIR
ÖRNEK BELEDİYE BAŞKANLIĞI
İhale kayıt numarası : 2026/123
1- İhalenin
a) Tarihi : 20.09.2026
b) Türü : Yapım işi
2- İhale konusu yapım işinin
a) Adı : Hastane Binası Yapım İşi
b) Yapılacağı yer : İstanbul
4- Sözleşmenin
a) Tarihi : 08.10.2026
b) Bedeli : 100 TRY
c) Süresi : 19.10.2026 - 21.04.2028
d) Yüklenicisi : Örnek İnşaat Limited Şirketi
e) Yüklenicinin uyruğu : Türkiye
f) Yüklenicinin adresi : Kamuya açık iş adresi
Kamuoyuna saygıyla duyurulur.
'''
        rows,_=parse_text(text,{'name':'EKAP'},classify,'BULTEN_12102026_YAPIM_SONUC.pdf','12.10.2026')
        self.assertEqual(rows[0]['title'],'Hastane Binası Yapım İşi')
        self.assertEqual(rows[0]['contractors'][0]['period_end_raw'],'21.04.2028')
        self.assertEqual(rows[0]['authority'],'ÖRNEK BELEDİYE BAŞKANLIĞI')

    def test_scope_match_avoids_boilerplate(self):
        text='''1. 2026/123 OFİS YENİLEME
İhale Kayıt Numarası (İKN) : 2026/123
3.1. Adı : Ofis İşleri
3.2. Niteliği : VRF Klima montajı
3.3. Yapılacağı yer : İstanbul
4.4. Benzer işler : havalandırma
'''
        rows,_=parse_text(text,{'name':'EKAP'},classify,'BULTEN_12102026_YAPIM.pdf','12.10.2026')
        self.assertEqual(rows[0]['match_basis'],'scope')
        self.assertEqual(rows[0]['relevance'],'dogrudan')
        self.assertFalse(parse_text(text.replace('VRF Klima montajı','Boya işi'),{'name':'EKAP'},classify,'BULTEN_12102026_YAPIM.pdf','12.10.2026')[0])

    def test_private_projects_keep_delivery_status_and_ced_not_mining(self):
        source={'key':'projects','name':'Projeler','url':'https://example.com'}
        html='<div class="single-p durum-devam-eden"><h5 class="sing-title">Proje A</h5></div><div class="single-p durum-hemen-teslim"><h5 class="sing-title">Proje B</h5></div>'
        rows,count=emlak_projects(html,source)
        self.assertEqual((len(rows),count),(2,2))
        self.assertEqual(enrich(rows[0],NOW)['opportunity']['status'],'proje')
        self.assertEqual(enrich(rows[1],NOW)['opportunity']['status'],'arsiv')
        self.assertIsNone(csb_detail('<div class="haber-detay-desc-wrapper">Kalker ocağı kapasite artışı projesi</div>',source,'https://example.com/detail'))
        lead=csb_detail('<div class="haber-detay-desc-wrapper">İstanbul adresinde, Örnek Ltd. Şti. tarafından yapılması planlanan “Yeni Otel Projesi”</div>',source,'https://example.com/detail')
        self.assertEqual(lead['project_owner'],'Örnek Ltd. Şti.')
        self.assertEqual(lead['title'],'Yeni Otel Projesi')


if __name__=='__main__':
    unittest.main()
