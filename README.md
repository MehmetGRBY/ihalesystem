# IhaleSystem

EFA İhale Bulucu ile TenderEnricher’ın birleşik yerel uygulaması: ihale/projeleri bulur, resmî sonuçtan yükleniciyi çıkarır, firma bilgilerini kaynak kanıtlarıyla araştırır ve aynı panelde gösterir.

## Kurulum ve başlatma

Python 3.11+, curl gerekir. İki motor aynı Python ortamında kurulur:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python app.py
```

Windows’ta sanal ortam: `.venv\Scripts\activate`. Kurulumdan sonra `Baslat.cmd`, Mac’te `Baslat.command` kullanılabilir. Başlatıcı uygulamayı arka planda çalıştırır ve panel hazır olunca varsayılan tarayıcıda açar: http://127.0.0.1:8765. Uygulama zaten açıksa mevcut panel açılır; ikinci bir sunucu başlatılmaz. Terminali açık tutmak gerekmez.

### Masaüstünden çift tıklayarak açma

- **Mac:** `Masaustu_Kisayolu.command` dosyasına bir kez çift tıklayın. Masaüstünde **İhale Bulucu.app** oluşur.
- **Windows:** `Masaustu_Kisayolu.cmd` dosyasına bir kez çift tıklayın. Masaüstünde **İhale Bulucu.lnk** oluşur; OneDrive'a yönlendirilmiş masaüstü de desteklenir.

Bundan sonra masaüstündeki **İhale Bulucu** simgesine çift tıklamak yeterlidir. Kısayol kurucusu, Python 3.11+ kuruluysa eksik sanal ortamı ve proje bağımlılıklarını ilk çalıştırmada hazırlar; ilk kurulum internet gerektirebilir. Windows Python yükleyicisinde Python erişiminin etkin olması gerekir. Yerel çoklu arama seçilmişse kurulu Docker Desktop önce hazır edilir.

Proje klasörünü taşırsanız kısayol kurucusunu yeni klasörden tekrar çalıştırın. Başlatma günlükleri `data/runtime/desktop-launcher.log` dosyasındadır; başlatılamazsa açıklama tarayıcıda gösterilir. Doğrudan `python app.py` komutu terminalde çalışmaya devam eder.

Otomatik tarama, web araştırması ve yedeklemeyi kapatarak panel açmak:

```bash
python app.py --no-auto
```

İnternet/API anahtarı gerektirmeyen, gerçek veriden ayrı demo:

```bash
python app.py --demo
```

Demo firmalar ve iletişimler sentetiktir; panelde ve JSON’da açıkça işaretlenir. Demo canlı tarama veya gerçek internet araştırması yapmaz.

## Paneli kullanma

**Fırsatlar** bölümünde proje, şehir veya firma arayın; satış aşaması ve kaynağa göre filtreleyin. Ek iş alanı, tarih ve araştırma filtreleri **Diğer filtreler** menüsündedir. Bir satıra tıkladığınızda ihale, sonraki adım, kaynaklar ve firma bilgileri sağ panelde açılır. Küçük ekranlarda ayrıntı kapatılabilir bir pencere olarak görünür. Tarih ve öncelik başlıkları sıralamayı değiştirir.

**EFA kapsamı**: Panel yalnızca başlıkta veya işin niteliği bölümünde klima/iklimlendirme, havalandırma, ısıtma, soğutma veya mekanik tesisat işi açıkça bulunan kayıtları gösterir. Genel bina/okul inşaatı tek başına yeterli değildir. Çim/kök havalandırma makinesi, süt soğutma tankı, salt yakıt ve araç parçası gibi eşsesli işler elenir. Her satırda iş alanı ve gerçek ihale durumu; ayrıca önerilen takip adımı gösterilir. Teknik şartnamenin incelendiği veya satınalmanın açık olduğu varsayılmaz. Geniş keşif geçmişi veritabanında ve JSON çıktısında korunur; `efa_scope.matched=false` kayıtları panel ve firma araştırmasından dışlanır.

**Araştırmalar**, araştırmaya uygun kayıtları ve firma araştırmalarının durumunu gösterir. **Kaynaklar ve ayarlar**, otomatik takip, yedekler, arama motorları ve tarama geçmişini bir araya getirir; birleşik JSON çıktısı buradan indirilebilir. Takip simgesi bu tarayıcıda saklanır. Yazı tipi ve simgeler yerel dosyalardır; arayüz dış bir CDN'ye bağımlı değildir.

## Birleşik çalışma akışı

1. EFA motoru TOKİ, belediye/üniversite listeleri, EKAP resmî PDF bültenleri, Emlak Konut ve ÇED duyurularını tarar. İptal/düzeltme eşleştirmesi, tarih güncellemeleri ve proje güncelliği düzeltmeleri korunur.
2. Tarama sonunda en fazla 10 uygun EKAP sonuç kaydı otomatik olarak yerel resmî PDF kanıtıyla işlenir. Bu PDF adımına ek olarak, uygulama açıkken saatte 5 güncel/aktif sonuç kaydı webde araştırılır; günlük üst sınır 20 kayıttır. Telefon veya e-postası eksik kayıtlar önceliklenir. Bugünün kayıtları da değerlendirilir; tarihi belirsiz ve arşiv kayıtları otomatik web araştırmasına girmez. Aynı firma bir parti içinde tekrarlanmaz. Günlük sayaç ve kuyruk yeniden başlatmalarda korunur.
3. PDF’deki ihale numarası ve yüklenici alanı TenderEnricher’a kanıt olur. JSON’daki `contractors` veya `official` etiketi tek başına kazanan kanıtı sayılmaz; arşivdeki PDF tekrar doğrulanır.
4. Sağ paneldeki **Firmayı araştır** / **Araştırmayı yenile** düğmesi ek şirket araştırmasını başlatır. İstenirse firma sitesi ve sonuç ilanı bağlantısı girilebilir. **Araştırmalar** bölümündeki **Firmaları araştır** düğmesi en fazla 10 sonuç kaydını işler.
5. Kazanan, telefon/e-posta/adres, eksikler, skorlar, çelişkiler ve kaynaklar seçilen kaydın **İletişim ve firma bilgileri** kartlarında görünür. İdare telefonu yüklenicinin telefonu yapılmaz; ihale şehri şirketin ili sayılmaz.
6. Kabul edilen kazanan fırsatın hedef yüklenicisini ve kurumsal iletişim arama bağlantısını günceller. İptal, kapanmış sözleşme veya eskimiş araştırma sonucu aktif satış adayı olarak yeniden açılmaz.

İnternette URL keşfi birden fazla sağlayıcıyla çalışır. `.env.example` → `.env` kopyalanarak istenen bağlantılar yapılandırılır:

| Sağlayıcı | Ayar |
| --- | --- |
| [Brave Search](https://api-dashboard.search.brave.com/) | `TE_BRAVE_API_KEY` |
| [Google sonuçları / Serper](https://serper.dev/) | `TE_SERPER_API_KEY` |
| [Tavily](https://app.tavily.com/) | `TE_TAVILY_API_KEY` |
| Kendi SearXNG sunucunuz | `TE_SEARXNG_URL` (ör. `http://127.0.0.1:8080`) |

Birden fazla anahtar/sunucu tanımlandığında **hepsi aynı sorguya paralel katılır**; sonuçlar sağlayıcılar arasında dönüşümlü alınır. Bir sağlayıcının hata vermesi diğerlerini durdurmaz. Tekrarlanan bağlantılar ve takip etiketleri ayıklanır; kısa süreli başarılı sorgu önbelleği gereksiz tekrarları azaltır. Sağlayıcı hataları araştırma kaynak notlarında görünür. Aynı bağlantıyı iki arama motorunun bulması bağımsız ikinci kanıt sayılmaz.

Varsayılan seçim `TE_SEARCH_PROVIDERS=["brave","serper","tavily","searxng"]`. Yalnızca seçilen ve ayarı bulunan sağlayıcılar kullanılır; örneğin `["serper","tavily"]` Brave’i devre dışı bırakır. Yeni sağlayıcı eklenince elle araştırmanın eski önbelleği kullanılmaz. Panel ve `/api/status`, yapılandırılan sağlayıcıların yanında her sağlayıcı/motorun son denemesini, son başarılı yanıtını ve son hata zamanını gösterir. Henüz denenmeyen motorlar açıkça belirtilir; boş sonuç ile erişim hatası ayrıdır. Kayıtlar gerçek araştırma isteklerinden gelir; durum sorgulamak yeni arama başlatmaz. Sorgular ve anahtarlar bu sağlık kaydına yazılmaz.

SearXNG birden fazla motoru kendi sunucusunda birleştirir. `TE_SEARXNG_ENGINES` isteğe bağlı motor listesidir; boşsa sunucunun varsayılanları kullanılır. Motor listesi/adres değişince elle araştırmanın önbelleği yenilenir. Motorlardan biri hata verirse kalan sonuçlar işlenir ve hata kaynak notuna eklenir. Bütün motorlar erişim hatası verirse boş sonuç başarı sayılmaz. [SearXNG API rehberi](https://docs.searxng.org/dev/search_api.html).

### API anahtarı olmadan yerel çoklu arama

Kurulu Docker Desktop çalışırken proje klasöründe:

```bash
.venv/bin/python scripts/local_search.py start
.venv/bin/python scripts/local_search.py check
```

Windows’ta Python yolu `.venv\Scripts\python.exe`. `start`, resmî ve sürümü sabitlenmiş SearXNG/Valkey görüntülerini başlatır; yerel bir rastgele sunucu sırrı üretir ve `.env` içine `http://127.0.0.1:8080` ile `["brave","duckduckgo","yahoo"]` motorlarını yazar. Mevcut API anahtarları korunur; başka SearXNG adresi varsa değiştirilmez. Docker kurulu değilse kurulum yönergesiyle durur. Rastgele herkese açık SearXNG sunucusu kullanılmaz. [Resmî container kurulum rehberi](https://docs.searxng.org/admin/installation-docker.html).

Arama yalnızca bu bilgisayardan erişilir; Valkey dışarıya port açmaz. Yerel servis/önbellek `data/runtime/search/` ve Docker birimlerinde kalır, GitHub’a gönderilmez. `.env` ve sunucu sırrı da dışlanır. `Baslat.command` / `Baslat.cmd`, yalnızca bu yerel adres seçilmişse önce arama servisini hazırlar. Docker Desktop kapalıysa başlatmayı dener. Doğrudan `python app.py` kullanımında arama servisini önce yukarıdaki komutla başlatın.

`check` gerçek bir genel sorgu gönderir ve en az iki motorun sonuç verdiğini denetler. Motorların erişilebilirliği sorguya ve o anki erişim sınırlamalarına bağlıdır; CAPTCHA veya erişim engeli aşılmaz. Motor adlarının panelde görünmesi tek başına canlı kontrol değildir.

```bash
.venv/bin/python scripts/local_search.py status
.venv/bin/python scripts/local_search.py stop
```

`stop` yalnızca projeye ait iki container’ı durdurur; uygulamanın ihale verilerini silmez. Docker başka projeler için de çalışıyorsa onlar etkilenmez.

Hiçbir sağlayıcı yapılandırılmasa da verilen/önceden bilinen kaynak URL’leri, ihale toplama ve yerel resmî PDF araştırması çalışır. Etkin her arama API’si aynı sorgu için ayrı istek alır ve kendi hesabınızın planını kullanır. Tarayıcı desteği isteğe bağlıdır ve mevcut robots/erişim politikalarını korur. Arama özeti ve yapay zekâ cevabı, yüklenici veya iletişim kanıtı olarak alınmaz.

Elle başlatılan EKAP araştırmasında yerel PDF eksik veya okunamıyorsa yapılandırılmış web araması kullanılır. Yerel PDF bir kazanan ya da ortak girişim kararı veriyorsa ek sonuç araması yapılmaz; verilen sonuç bağlantıları ayrıca kontrol edilir.

İKN’si veya idaresi eksik kayıt ile İKN’siz yatırım projesi panelde tutulur; desteklenmeyen araştırma nedeni gösterilir. Bir sonuç bulunamaması keşif kaydını silmez. Ortak girişim, farklı kazanan veya çelişkili alanlar elle incelemeye ayrılır; bilgi tahmin edilmez. `partial` araştırmanın bazı alanları eksik/tek kaynaklı olduğunu, `resolved` temel alanların bağımsız kaynaklarla desteklendiğini belirtir. Skorlar istatistiksel olasılık değildir.

Firma sitelerinde Organization JSON-LD, microdata, hCard ve açık şirket kimliğiyle yayımlanan HTML iletişim alanları okunur. Telefon/e-posta bağlantıları, adres başlıkları ve kurumsal sayfa bilgileri kaynak konumlarıyla saklanır. Form verileri, gizli alanlar ve kişilere ait kartlar şirket bilgisi sayılmaz. İletişim formundaki CAPTCHA, çevresindeki açık iletişim metninin okunmasını engellemez; gerçek erişim doğrulaması varsa işlem durur.

Bir sayfanın okunabilmesi şirketin ihale yüklenicisi olduğunu tek başına kanıtlamaz. Unvan ile ek kimlik/adres/site eşleşmesi kontrolleri korunur. Çelişkili telefonlar ayrı kanıt olarak kalır. Her site tasarımı desteklenmez; tanınmayan veya eşleşmeyen bilgiler kaynak notuyla belirtilir.

İletişim sayfası yalnızca marka adı içeriyorsa, aynı sunucudaki gözlenen KVKK/künye/Hakkımızda bağlantılarından en fazla ikisi mevcut sayfa bütçesi içinde kontrol edilir. Görünür veri sorumlusu beyanındaki tam ticari unvan kaynak konumuyla okunur. Başka sunucuya yönlenen kimlik bağlantıları kullanılmaz; robots ve erişim kontrolleri her sayfada geçerlidir. Kısa marka sayfasındaki iletişim, doğrudan bağlı kimlik sayfasıyla aynı marka ve ayrıntılı posta adresini yayımlıyorsa ve tek bir işletmeci unvanı resmî yükleniciyle eşleşiyorsa kabul edilebilir. Çelişkili işletmeci/unvan/adres zinciri reddedilir. E-posta/telefon kanıtı iletişim sayfasında, unvan kanıtı kimlik sayfasında kalır; aynı site bağımsız iki yayıncı sayılmaz.

Adreslerde Sk./Sokak ve Cad./Caddesi gibi yazımlar, açık sokak adı, kapı numarası, ilçe ve il birlikte uyuşuyorsa karşılaştırılır. Farklı daire, kat, blok veya yayımlanmış mahalle bilgisi çelişkili kalır. Eksik mahalle alanı, iki farklı mahalleyi aynı adres yapmaz. Kaynak adres metinleri değiştirilmez; en güçlü kaynaktaki gösterim korunur. Aynı şirketin farklı sayfaları bağımsız ikinci iletişim kaynağı sayılmaz. Eski kayıtta bu adımı uygulamak için **Araştırmayı yenile** kullanılabilir.

EKAP yapım/hizmet sonuçlarında kullanılan `Yüklenici` ve `Yüklenicisi` alanları desteklenir. Eski bir sürümle işlenmiş arşivde bu alanlar eksikse yerel bültenlerin yeniden işlenmesi gerekir; PDF’leri tekrar indirmek gerekmez.

## İçe aktarma ve komutlar

EFA’nın mevcut JSON çıktısı (şema 1.3) veya birleşik çıktı içe alınabilir. Kimlikler korunur; eski araştırma iddiaları doğrudan doğrulanmış bilgi olarak alınmaz. JSON ile aynı klasördeki `ekap-bulten/` PDF arşivi varsa taşınır:

İletişim, yüklenici, bülten, tarih, belge ve araştırma bağlantıları içe aktarmadan önce doğrulanır. Tarih alanları metin veya boş değer kabul eder; liste/nesne gibi bozuk türler reddedilir. Ayrıca birleştirilen kayıtlar aynı veritabanı işlemi içinde okunabilirlik kontrolünden geçer; hata varsa aktarım geri alınır. Boş isteğe bağlı listeler desteklenir.

```bash
python app.py --import /tam/yol/data/ihaleler.json
python app.py --scan
python app.py --enrich KAYIT_KIMLIGI
python app.py --enrich-all
python app.py --data-dir /tam/yol/calisma-verileri --no-auto
```

`--import`, `--scan`, `--enrich` ve `--enrich-all` tek işlem yapıp çıkar. Araştırma kayıt kimliği kartın JSON çıktısındaki `id` alanıdır; ihale numarasından ayrıdır. Aynı numaralı farklı kaynak/kurumların kayıt ve araştırma geçmişleri karışmaz.

## Otomasyon ve yedekleme

Normal `python app.py` ve başlatıcılar otomasyonu açar. Bilgisayar ile uygulama açık olmalıdır; kapalıyken zamanlanmış iş çalışmaz. Kaynak taraması varsayılan 6 saatte bir, EKAP geçmişi eksikse 1 dakika arayla sürer. Sonraki tarama ve firma araştırması panelin **Otomatik takip, yedek ve arama motorları** bölümündedir. `--no-auto` ve demo bütün zamanlanmış işleri kapatır.

`.env` ayarları: `TE_RESEARCH_BATCH_SIZE=5`, `TE_RESEARCH_INTERVAL_MINUTES=60`, `TE_RESEARCH_DAILY_LIMIT=20`, `TE_RESEARCH_REFRESH_DAYS=7`. Tamamlanmış web araştırması bu süre dolmadan otomatik tekrarlanmaz; yerel PDF sonucu web araştırmasına yükseltilebilir. Elle verilmiş kaynak bağlantıları korunur. Eski sonuç yenisi sıradayken gösterilmeye devam eder; ihale girdisi değişmişse eskisi gizlenir. Elle araştırma düğmeleri günlük otomatik kotadan bağımsızdır. Yapılandırılmış ücretli API varsa otomatik araştırma o planı da kullanır.

Her 24 saatte iki yerel SQLite veritabanı ve resmî PDF'ler `data/backups/live/snapshot-.../` içine alınır; en son 7 doğrulanmış kopya saklanır (`TE_BACKUP_INTERVAL_HOURS`, `TE_BACKUP_KEEP`). Veritabanları SQLite backup API ile kopyalanır; uygulamanın tarama/araştırma yazıcıları bu sırada bekler. Her dosyanın SHA-256 özeti, SQLite bütünlüğü ve ilişkileri kontrol edilir; başarısız kopya önceki yedekleri silmez. Değişmeyen PDF'ler yalnızca önceki doğrulanmış yedekle diskte paylaşılır; canlı PDF'ye bağlı değildir. `.env`, anahtarlar, Docker sırları ve geçici dosyalar yedeklenmez.

```bash
python scripts/backup.py verify data/backups/live/snapshot-TARIH
python scripts/backup.py restore data/backups/live/snapshot-TARIH /tam/yol/yeni-calisma-verileri
python app.py --data-dir /tam/yol/yeni-calisma-verileri --no-auto
```

Geri yükleme yeni ve mevcut olmayan hedef ister; canlı verinin üzerine yazmaz. Yedekler GitHub'a gönderilmez. Bunlar aynı diskte yerel kopyalardır; disk arızası için ayrıca başka diske kopyalanmalıdır. Özel PostgreSQL/harici veritabanı kullanılıyorsa bu yerel yedekleyici onu kapsamaz ve panel başarısız yedek durumunu gösterir.

## Veriler ve API

Varsayılan canlı çalışma alanı `data/runtime/live/`, demo `data/runtime/demo/`. Keşif SQLite’ı/PDF arşivi ile zenginleştirme SQLite’ı ayrı tablolama motorlarını çakıştırmamak için ayrı dosyalardadır. Uygulama ortak kayıt kimliğiyle bağlar. İlk EFA veritabanı geçişi otomatik yedek alır. Araştırma kuyruğu kalıcıdır; kapanınca kalan işler sonraki açılışta sürer. Yeniden araştırmalar TenderEnricher’ın run geçmişinde korunur.

Birleşik tam JSON: `data/runtime/live/ihalesystem.json`. Keşfin ham 1.3 çıktısı ayrıca `data/runtime/live/discovery/ihaleler.json` içinde kalır.

```text
GET  /api/tenders?compact=1
GET  /api/export
GET  /api/status
GET  /api/enrichment?id=KAYIT_KIMLIGI
POST /api/scan
POST /api/enrich
```

Tek araştırma örneği:

```json
{"id":"kesif-kaydinin-24-haneli-kimligi","company_urls":[],"award_urls":[],"force":false}
```

Boş `{}` istek en fazla 10 sonuç kaydını sıraya alır. URL veya `force` seçeneği verilirse `id` zorunludur. Birleşik çıktı sürümü **2.0**; mevcut keşif alanları korunur, her kayda `enrichment` eklenir. Tam kanıtlar `enrichment.result` içindedir. Kısa panel çıktısı uzun ilan/kanıt metinlerini çıkarır; alanların doğrulama durumunu korur. Kartta telefon/e-posta/site/adres için **Tek kaynak**, **Doğrulandı**, **Çelişkili** veya **Eksik** etiketi görünür. Araştırma tamamlanınca keşif `revision`/`updated_at` güncellenir; zaman damgaları aynı saniyedeki değişiklikleri ayırmak için mikrosaniye içerir. Sadece geçen saate bağlı ihale durumu için tüketiciler tam listeyi yeniden değerlendirmelidir. Kaynak bağlantısı/ihale değişince eski araştırma `stale` olur ve güncel sonuç gibi gösterilmez.

## Geliştirme

```bash
python -m unittest discover -s discovery -v
pytest
ruff check .
ruff format --check .
mypy
node --check discovery/panel.js
```

CI Python 3.11 ve 3.14’te her iki motoru ve birleşim testlerini çalıştırır. Testler canlı internete çıkmaz. Orijinal TenderEnricher CLI (`tender-enricher demo/run/export`) korunur; ayrıntıları [TenderEnricher rehberinde](docs/TenderEnricher.md). Kaynak kapsamı ve EFA sınırlamaları [keşif rehberinde](discovery/README.md). Upstream sürümler: [kaynak kaydı](docs/upstream-sources.md).

Uygulama kaynak checkout’undan çalıştırılır; `pip install -e .` editable kurulum desteklenir. Tek başına wheel/dağıtım paketi veya halka açık sunucu dağıtımı bu birleşimin kapsamında değildir.
