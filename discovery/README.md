# EFA Satış Fırsatı Bulucu

Klima, ısıtma-soğutma ve montaj satışı için ihale, yüklenici ve yatırım projesi keşfi.
Python 3.11+, curl ve pypdf gerekir. Windows'ta curl hazırdır. EKAP'ın varsayılan
yöntemi resmî bültendir; Edge ve CAPTCHA kurulumu gerekmez. Eski tarayıcı adaptörü
isteğe bağlı kod olarak korunur; normal çalışmada kullanılmaz.

Depo yalnızca uygulama kodunu içerir. Çalışma verileri, PDF arşivi ve tarayıcı
oturumu Git'e eklenmez. Yeni kurulum ilk çalıştırmada kendi veri klasörünü ve
arşivini oluşturur. GitHub Actions testleri her yüklemede çalıştırır.

## Başlatma

Bu klasörde:

```powershell
python -m pip install -r requirements.txt
python bulucu.py
```

Tarayıcı: http://127.0.0.1:8765. Alternatif: Baslat.cmd dosyasına çift tıklayın.
İlk tarama başlar, terminal açıkken 6 saatte bir tekrar eder. Bilgisayar kapalıyken
çalışmaz. Ctrl+C ile durdurun. Aynı klasörü kullanan iki bot eşzamanlı çalışmamalıdır.

```powershell
python bulucu.py --scan
python bulucu.py --no-auto
python bulucu.py --port 8766
```

Tek seferlik tarama, otomatik taramasız panel ve farklı port seçenekleridir.

## Satış takibi

Panel varsayılan olarak takip edilebilecek adayları gösterir. İhalenin kapanması
bir yapım projesinin satış takibinin bittiği anlamına gelmez.

| Takip durumu | Kullanım |
| --- | --- |
| Teklif değerlendir | İhale tarihi yaklaşan işin kapsamını ve teklif yolunu kontrol et |
| Yükleniciye ulaş | Sonuç ilanındaki yüklenicinin HVAC satınalmasını ve iletişimini doğrula |
| Devam eden proje | Kaynakta devam eden olarak listelenmiş yapı projesini incele |
| Sonucu takip et | İhale tarihi geçmiş işin kazananını ve ilerleme durumunu bul |
| Araştırma gerekli | Tarih, yatırımcı veya teknik kapsam eksik; kaynak üzerinden tamamla |
| Arşiv | İptal, bitişi geçmiş sözleşme veya kapsam dışı kayıt |

Öncelik puanı basit takip sıralamasıdır; satış olasılığı veya teklif uygunluğu ölçümü
değildir. Hiçbir kayıt için HVAC satınalmasının hâlâ açık olduğu garanti edilmez.

## Kaynaklar ve kapsam

TOKİ yaklaşan/değerlendirme listeleri, Ankara ve İzmir belediyeleri, Medipol,
Ankara Medipol, TOBB ETÜ, İstinye, İPKB ve TKİ kaynakları korunur.
Kaynağa göre ilk 1–3 liste sayfası okunur; max_pages en fazla 5 olabilir.

Yeni satış kaynakları:

- EKAP resmî Kamu İhale Bülteni: Mal, Yapım, Hizmet ilanları ve sonuçları.
- Emlak Konut'un resmî proje listesi: devam eden ve hemen teslim kartları;
  hemen teslim projeleri arşivlenir. Başarılı tam listede artık görünmeyen
  eski projeler tamamlandı sayılmaz, güncelliği doğrulanması gereken aday olur.
- İstanbul, Ankara, İzmir, Antalya ve Bursa resmî ÇED/yatırım duyuruları:
  otel, hastane, konut, fabrika gibi bina/yatırım adayları. Her kaynakta ilk
  1–2 liste sayfasındaki en fazla 20 aday detay okunur.

ÇED duyurusu bir satınalma ilanı değildir. İzin aşaması, fiilî inşaatın başladığı
veya HVAC ihtiyacı olduğu anlamına gelmez. Devam eden konut projesinde de mekanik
satınalma tamamlanmış olabilir. Proje sahibi kaynaktan çıkarılamazsa boş bırakılır.
Emlak Konut proje listesi mekanik yükleniciyi veya satınalma sorumlusunu göstermez.

ilan.gov.tr ve İBB kaynakları otomatik erişimleri doğrulanmadığından kapalıdır.
Kaynak hataları panelde gösterilir; eski kayıtlar silinmez. Bütün Türkiye'deki
tesisler veya özel projelerin tamamı kapsanmaz. EKAP ülke genelini, ÇED kaynakları
belirtilen beş ilin duyurularını kapsar.

## EKAP geçmiş ve yüklenici keşfi

config.json içinde:

- bulletin_days: her taramada yeniden kontrol edilen en yeni günler; varsayılan 1.
- recheck_days: geç yayımlanan bültenler için tekrar kontrol penceresi;
  varsayılan 3, en fazla 7 gün. bulletin_days ile büyük olan pencere kullanılır.
- archive_days: geçmiş için hedef pencere; varsayılan 90, en fazla 365 gün.
- backfill_batch_days: her taramada eklenen geçmiş günler; varsayılan 30,
  en fazla 30 gün.

90 günün tamamı tek açılışta taranmış sayılmaz. Her tarama varsayılan olarak son üç
günü ve bu pencerenin dışında henüz işlenmemiş en yeni otuz geçmiş günü okur.
Panelde tamamlanan/kalan günler ve bugünün geçici kontrolü gösterilir.
Arşiv eksikken yalnızca EKAP taraması, önceki parti bittikten bir dakika sonra
devam eder. Arşiv tamamlanınca genel kaynak taraması altı saatlik düzene döner.
Terminal kapatılırsa durur; yeniden elle başlatıldığında kaldığı yerden devam eder.
Geçmişte yayın olmayan günler ancak EKAP açıkça yayın olmadığını bildirdiğinde
tamamlanır. Bugün, PDF bulunsa da bulunmasa da geçici sayılır; ertesi gün yeniden
kontrol edilir. Günlük geçici kontrol, arşiv bitince bir dakikalık sürekli tarama
başlatmaz; normal altı saatlik güncellemede tekrar bakılır.
Erişim hataları tamamlandı sayılmaz ve yeniden denenir.
İlk taramalar birkaç dakika sürebilir; her günün kayıtları kademeli kaydedilir.

PDF'ler data/ekap-bulten klasöründedir. PDF'ler ve çıkarılmış metinler tekrar
kullanılır; son yedi günün indirmeleri (boş yanıtlar dahil) 4 saat önbellektedir.
Daha eski günlerin önbelleği kalıcıdır. archive-progress.json ilerlemeyi
tutar. Dosyayı elle silmek yeniden taramayı başlatır; kayıtları silmez.

PDF metni öncelikle PyMuPDF çizim sırası korunarak okunur; desteklenmeyen çıktı
pypdf okuyucusuna döner. requirements.txt iki okuyucuyu da kurar.

Dört şirketin resmî sitesindeki merkez iletişimi, tam şirket unvanı eşleşirse
kayda eklenir (company_contacts.py). Bunlar proje satınalma yetkilisi değildir;
doğrulama tarihi ve resmî kaynak bağlantısı JSON içinde tutulur. Diğer firmaların
telefonu/e-postası tahmin edilmez. Firma rehberi şu an otomatik güncellenmez.

Paylaşım paketi: python paketle.py uygulama ve tam JSON çıktısını içeren ZIP üretir.
PDF arşivini de paylaşmak için python paketle.py --include-pdfs kullanın.
Varsayılan küçük pakette PDF dosyaları bulunmaz; announcement_text JSON içindedir.

Başlığın yanında yalnızca işin niteliği/kapsamı alanında HVAC eşleşmesi aranır.
Standart yeterlik ve benzer iş maddelerindeki klima kelimeleri kapsam eşleşmesi
sayılmaz. Teknik şartname ayrıca indirilip incelenmez. Salt yıkım, çatı, araç,
gıda veya saha işleri gibi belirgin ilgisiz işler süzülür; belirsiz bina işleri
potansiyel olarak kalabilir.

İKN ile aynı EKAP kaydı birleşir. Eski ilan yeni sonucu/iptali ezmez. Bir İKN'deki
birden fazla yüklenici saklanır. Sonuç belgesindeki ihale tarihi, yüklenici adı,
iş adresi, sözleşme tarihi/bedeli ve varsa başlangıç-bitiş tarihleri okunur.
Sözleşme süresinden tahmini bitiş tarihi üretilmez. Alanlar eksikse boş kalır.
Farklı kaynaklardaki aynı projeler henüz otomatik birleştirilmez.

Diğer ihale kaynaklarında aynı kurumun aynı yıl/numarasıyla yayımladığı ilan,
düzeltme ve iptal birleştirilir. Farklı kurumların aynı numaraları ayrı kalır;
numarası bulunmayan ilanlar başlık benzerliğiyle birleştirilmez. İptal duyurusunda
“2026/054 İKN’li” gibi yazımlar da okunur. Genel başlıklı iptal/düzeltme metni,
bilinen ilgili kaydı güncelleyebilir; tek başına satış fırsatı olarak gösterilmez.
Kaynak sayfaları related_announcements alanında korunur. EKAP düzeltmesinde yeni
ihale tarihi açıkça yazılmışsa güncellenir; yalnız teslim/yayın tarihi değişmişse
bilinen ihale tarihi korunur.

Eski veritabanı ilk açılışta bu eşleştirmeye geçirilir; önce
data/ihaleler-before-lifecycle.sqlite3 yerel yedeği alınır. Eski ilan/iptal çiftleri
birleşirken ilk görülen kaydın kimliği, ilk/son görülme tarihleri ve kaynak
duyuruları korunur. Kayıtlı EKAP düzeltme metninde okunabilen yeni tarih de onarılır.

## İletişim ve diğer bota çıktı

Kaynakta etiketli idare telefonu/adresi ve yüklenici iş adresi saklanır. Yüklenicinin
telefonu/e-postası belge içinde yoksa tahmin edilmez. İdare telefonu yükleniciye
aitmiş gibi sunulmaz. ÇED metnindeki e-posta duyuru iletişimi olarak gösterilir;
yatırımcıya ait olduğu varsayılmaz. İletişimler güncel yetkili bilgisi olarak
doğrulanmış değildir. Kurumsal iletişimi araştır bağlantısı yalnızca arama açar.
Bot kimseye mesaj göndermez ve başka bir botu otomatik çağırmaz.

JSON indir veya data/ihaleler.json dosyasını kullanın. Sözleşme:
[JSON-SOZLESMESI.md](JSON-SOZLESMESI.md), sürüm 1.3. Önceki alanlar korunur.

```text
GET /api/tenders
GET /api/tenders?compact=1
GET /api/export
GET /api/tenders?since=2026-10-12T00:00:00%2B03:00
GET /api/bulletins/BULTEN_12102026_YAPIM_SONUC.pdf
GET /api/status
POST /api/scan
```

compact=1 yalnızca panel içindir; uzun ilan metni ve kaynak geçmişini çıkarır.
Diğer bot tam export çıktısını kullanmalıdır. since saat dilimli ISO tarih alır.
id ve revision değişiklik takibi içindir. API yalnızca aynı bilgisayarda dinler.

## Test ve paylaşım

```powershell
python -m unittest discover -v
python paketle.py
```

ZIP, uygulamayı, testleri, gerçek JSON çıktısını ve resmî PDF kaynaklarını içerir.
Tarayıcı oturumu, SQLite veritabanı, araştırma dosyaları ve ilerleme durumu paylaşılmaz.
Arkadaşınız JSON'u doğrudan inceleyebilir. Botu çalıştırınca kendi veritabanı ve
tarama ilerlemesi oluşur.
