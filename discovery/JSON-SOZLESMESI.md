# Satış fırsatı çıktısı — sürüm 1.3

Dosya: `data/ihaleler.json`. Aynı içerik: `GET /api/export`.
Üst alanlar: `schema_version`, `exported_at`, `items`.
Önceki sürümün alanları korunur. Bu uygulama başka bir botu çağırmaz.

Her kayıtta `id`, `revision`, `title`, `source`, `source_key`, `source_url`,
`url`, `stage`, `relevance`, `matched_keywords`, `first_seen_at`,
`last_seen_at`, `updated_at`, `freshness` bulunur.

| Alan | Anlam |
| --- | --- |
| detail_url | Ayrı ilan sayfası varsa bağlantısı; yoksa null |
| tender_number | Kaynaktan çıkarılmış ihale numarası; her kurum numarası EKAP numarası değildir |
| authority | Listede bulunan ilgili birim; yoksa null. Kaynak kurumun adı source alanındadır |
| tender_date_raw / tender_date_iso | Kaynak tarih metni / saat dilimi içeren ayrıştırılmış tarih |
| date_precision | minute veya day; saat yoksa gün sonu kullanılır; tarih çözülemezse null |
| published_date_raw | Yayın tarihi metni; ihale tarihi değildir |
| announcement_text | Desteklenen detay sayfasının ilan gövdesi; en fazla 60.000 karakter; yoksa null |
| document_links | url ve label içeren doküman bağlantıları; bulunamazsa boş liste |
| missing_fields | Bulunamayan numara, birim, tarih ve ilan metni alanları |
| evidence | Liste bağlantısı, detay bağlantısı, kaynak başlığı ve ham tarih |
| needs_verification | true: kaynak ve doküman üzerinden doğrulama gerekir |

Detay metni şu an EKAP resmî bültenleri, desteklenen proje/ÇED sayfaları,
Medipol, Ankara Medipol ve TOBB ETÜ kaynaklarında,
her kaynak taramasında ilk 20 eşleşme için alınır. Diğer kaynaklar liste
verisi ve bağlantıları sağlar. EKAP resmî bülten PDF metni okunur; diğer ihale
eklerinin içeriği ayrıca çözümlenmez.
Eksik alanlar tahmin edilmez. Genel site iletişim bilgisi ihale yetkilisi
olarak sunulmaz. Liste bağlantısı olan kayıtlar başlık ve tarih üzerinden
kaynak listesinde bulunabilir.

Tüketici id ve revision ile tekrarları yönetebilir; `since` parametresi
saat dilimli ISO tarih alır ve updated_at bu tarihten büyük kayıtları döndürür.
Kapalı, iptal veya tarihi geçmiş kayıtlar da arşivde kalır. freshness alanını
kullanarak seçim yapılmalıdır. HVAC eşleşmesi başlığa dayanır; teknik
şartnamede ilgili iş bulunacağının garantisi değildir.

## Satış takip alanları

| Alan | Anlam |
| --- | --- |
| opportunity.kind | ihale, yuklenici, yatirim_projesi, sonuc_takibi veya tesis_takibi |
| opportunity.status | teklif, yuklenici, proje, takip, kontrol veya arsiv |
| opportunity.priority | 0–100 takip sıralaması; satış olasılığı değildir |
| opportunity.reason | Kayda neden bakıldığı; HVAC ihtiyacı garanti edilmez |
| opportunity.target_name / target_role | Ulaşılacak taraf ve rol; isim bulunamazsa null |
| opportunity.next_action | Satış araştırmasındaki sonraki adım |
| opportunity.hvac_scope_confirmed | false: teknik şartname ve satınalma ihtiyacı henüz doğrulanmadı |
| contractors | Sonuç ilanından çıkarılmış yükleniciler, iş adresi ve sözleşme alanları |
| contacts | role, name, phone, email, address, source_url; eksikler null olabilir |
| missing_sales_fields | Hedef isim, hedef telefon/e-posta veya doğrulanmış HVAC kapsamı eksikleri |
| contact_search_url | Kurumsal iletişim araştırması için arama bağlantısı; bulunan telefon değildir |
| match_basis / match_evidence | Başlık, iş kapsamı veya proje kaynağına dayanan eşleşme ve kanıt metni |
| project_owner | ÇED metninde çıkarılabilen yatırımcı; yoksa null |
| related_announcements | Aynı kurum ve numarayla birleştirilen kaynak ilan/düzeltme/iptal metinleri; compact çıktıda çıkarılır |
| source_presence | Emlak Konut listesinde present veya missing; kaybolma tamamlanma kanıtı değildir |
| missing_since_at / last_known_source_status | Listeden kaybolduğunda ilk saptama zamanı ve önceki kaynak durumu |

contacts.role idare, yuklenici veya duyuru olabilir. İdare telefonu yüklenicinin
telefonu olarak kullanılmamalıdır. Bir yüklenici kaydı bir iş ortaklığının tamamını
tek isim metninde içerebilir. İletişimin güncelliği ayrıca doğrulanmalıdır.
Sözleşme başlangıç/bitiş alanları kaynakta yoksa hesaplanmaz. Satış durumu okuma
anında tarih ve aşamaya göre türetilir; teklif vermeye hukuken uygunluk kararı değildir.

Sonuç/kapalı ihale freshness=kapali olabilirken opportunity.status=yuklenici olabilir.
Satış takibi yapan tüketici yalnızca freshness filtresiyle yüklenicileri elememelidir.

EKAP'ın varsayılan kaynağı resmî Kamu İhale Bülteni'dir. `acquisition_method`
değeri `official_bulletin` olur. `bulletin_reference` içindeki `filename`,
`published_date` ve `page_start` resmî PDF'e işaret eder; PDF yalnızca --include-pdfs ile oluşturulan paylaşım ZIP'inde
data/ekap-bulten klasöründedir. `tender_number` resmî İKN'dir. `announcement_text`
ilan gövdesini içerir; teknik şartnamenin tamamı değildir. Arama ekranı üzerinden
detaya gitmek yine kullanıcı doğrulaması isteyebilir. Mal, Yapım ve Hizmet ilanları
ile sonuç bültenleri okunur.
Arşiv hedefi varsayılan 90 gündür, kademeli doldurulur. Tamamlanan/kalan günler
api/status içindeki EKAP archive nesnesinde bulunur. Bütün hedef tarihler tamamlanmadan
çıktı 90 günlük eksiksiz arşiv olarak sunulmamalıdır. Sonuç bültenleri de okunur.

archive.provisional_days bugünün geçici kontrolüdür. completed_days yalnız geçmiş
günleri sayar; remaining_days tamamlanan ve bugün geçici kontrol edilen günler
dışındaki arşiv işidir. remaining_days=0 bugünün yayınının kesinleştiği anlamına
gelmez. Son günler recheck_days penceresiyle yeniden kontrol edilir.
