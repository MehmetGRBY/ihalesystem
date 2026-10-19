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

Windows’ta sanal ortam: `.venv\Scripts\activate`. Kurulumdan sonra `Baslat.cmd`, Mac’te `Baslat.command` kullanılabilir. Panel: http://127.0.0.1:8765. Terminal açık kalmalıdır. Aynı çalışma verileriyle ikinci uygulama açılması kilitle engellenir.

Canlı taramayı başlatmadan panel açmak:

```bash
python app.py --no-auto
```

İnternet/API anahtarı gerektirmeyen, gerçek veriden ayrı demo:

```bash
python app.py --demo
```

Demo firmalar ve iletişimler sentetiktir; panelde ve JSON’da açıkça işaretlenir. Demo canlı tarama veya gerçek internet araştırması yapmaz.

## Birleşik çalışma akışı

1. EFA motoru TOKİ, belediye/üniversite listeleri, EKAP resmî PDF bültenleri, Emlak Konut ve ÇED duyurularını tarar. İptal/düzeltme eşleştirmesi, tarih güncellemeleri ve proje güncelliği düzeltmeleri korunur.
2. Tarama sonunda en fazla 10 uygun EKAP sonuç kaydı otomatik olarak yerel resmî PDF kanıtıyla işlenir. Bu otomatik adım internette ek arama veya ücretli API çağrısı yapmaz.
3. PDF’deki ihale numarası ve yüklenici alanı TenderEnricher’a kanıt olur. JSON’daki `contractors` veya `official` etiketi tek başına kazanan kanıtı sayılmaz; arşivdeki PDF tekrar doğrulanır.
4. Karttaki **Firma araştır** / **Araştırmayı yenile** düğmesi ek şirket araştırmasını başlatır. İstenirse firma sitesi ve sonuç ilanı bağlantısı girilebilir. Üstteki **Firmaları araştır** düğmesi en fazla 10 sonuç kaydını işler.
5. Kazanan, telefon/e-posta/adres, eksikler, skorlar, çelişkiler ve kaynaklar aynı kartın **Firma araştırması** bölümünde görünür. İdare telefonu yüklenicinin telefonu yapılmaz; ihale şehri şirketin ili sayılmaz.
6. Kabul edilen kazanan satış kartındaki hedef yükleniciyi ve kurumsal iletişim arama bağlantısını günceller. İptal, kapanmış sözleşme veya eskimiş araştırma sonucu aktif satış adayı olarak yeniden açılmaz.

İnternette URL keşfi birden fazla sağlayıcıyla çalışır. `.env.example` → `.env` kopyalanarak istenen bağlantılar yapılandırılır:

| Sağlayıcı | Ayar |
| --- | --- |
| [Brave Search](https://api-dashboard.search.brave.com/) | `TE_BRAVE_API_KEY` |
| [Google sonuçları / Serper](https://serper.dev/) | `TE_SERPER_API_KEY` |
| [Tavily](https://app.tavily.com/) | `TE_TAVILY_API_KEY` |
| Kendi SearXNG sunucunuz | `TE_SEARXNG_URL` (ör. `http://127.0.0.1:8080`) |

Birden fazla anahtar/sunucu tanımlandığında **hepsi aynı sorguya paralel katılır**; sonuçlar sağlayıcılar arasında dönüşümlü alınır. Bir sağlayıcının hata vermesi diğerlerini durdurmaz. Tekrarlanan bağlantılar ve takip etiketleri ayıklanır; kısa süreli başarılı sorgu önbelleği gereksiz tekrarları azaltır. Sağlayıcı hataları araştırma kaynak notlarında görünür. Aynı bağlantıyı iki arama motorunun bulması bağımsız ikinci kanıt sayılmaz.

Varsayılan seçim `TE_SEARCH_PROVIDERS=["brave","serper","tavily","searxng"]`. Yalnızca seçilen ve ayarı bulunan sağlayıcılar kullanılır; örneğin `["serper","tavily"]` Brave’i devre dışı bırakır. Yeni sağlayıcı eklenince elle araştırmanın eski önbelleği kullanılmaz. Panel ve `/api/status`, yapılandırılan sağlayıcı adlarını gösterir; bu liste API erişiminin canlı olarak test edildiği anlamına gelmez.

SearXNG birden fazla motoru kendi sunucusunda birleştirebilir. Kullanılan motorlar o sunucunun ayarlarına bağlıdır; JSON çıktı biçimi açık olmalıdır. Sunucu adresini yalnızca operatörün `.env` ayarı belirler. Rastgele bir herkese açık sunucu seçilmez, Docker veya sunucu otomatik kurulmaz. [SearXNG API rehberi](https://docs.searxng.org/dev/search_api.html).

Hiçbir sağlayıcı yapılandırılmasa da verilen/önceden bilinen kaynak URL’leri, ihale toplama ve yerel resmî PDF araştırması çalışır. Etkin her arama API’si aynı sorgu için ayrı istek alır ve kendi hesabınızın planını kullanır. Tarayıcı desteği isteğe bağlıdır ve mevcut robots/erişim politikalarını korur. Arama özeti ve yapay zekâ cevabı, yüklenici veya iletişim kanıtı olarak alınmaz.

Elle başlatılan EKAP araştırmasında yerel PDF eksik veya okunamıyorsa yapılandırılmış web araması kullanılır. Yerel PDF bir kazanan ya da ortak girişim kararı veriyorsa ek sonuç araması yapılmaz; verilen sonuç bağlantıları ayrıca kontrol edilir.

İKN’si veya idaresi eksik kayıt ile İKN’siz yatırım projesi panelde tutulur; desteklenmeyen araştırma nedeni gösterilir. Bir sonuç bulunamaması keşif kaydını silmez. Ortak girişim, farklı kazanan veya çelişkili alanlar elle incelemeye ayrılır; bilgi tahmin edilmez. `partial` araştırmanın bazı alanları eksik/tek kaynaklı olduğunu, `resolved` temel alanların bağımsız kaynaklarla desteklendiğini belirtir. Skorlar istatistiksel olasılık değildir.

Firma sitelerinde Organization JSON-LD, microdata, hCard ve açık şirket kimliğiyle yayımlanan HTML iletişim alanları okunur. Telefon/e-posta bağlantıları, adres başlıkları ve kurumsal sayfa bilgileri kaynak konumlarıyla saklanır. Form verileri, gizli alanlar ve kişilere ait kartlar şirket bilgisi sayılmaz. İletişim formundaki CAPTCHA, çevresindeki açık iletişim metninin okunmasını engellemez; gerçek erişim doğrulaması varsa işlem durur.

Bir sayfanın okunabilmesi şirketin ihale yüklenicisi olduğunu tek başına kanıtlamaz. Unvan ile ek kimlik/adres/site eşleşmesi kontrolleri korunur. Çelişkili telefonlar ayrı kanıt olarak kalır. Her site tasarımı desteklenmez; tanınmayan veya eşleşmeyen bilgiler kaynak notuyla belirtilir.

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

Boş `{}` istek en fazla 10 sonuç kaydını sıraya alır. URL veya `force` seçeneği verilirse `id` zorunludur. Birleşik çıktı sürümü **2.0**; mevcut keşif alanları korunur, her kayda `enrichment` eklenir. Tam kanıtlar `enrichment.result` içindedir. Kısa panel çıktısı uzun ilan/kanıt metinlerini çıkarır. Araştırma tamamlanınca keşif `revision`/`updated_at` güncellenir; zaman damgaları aynı saniyedeki değişiklikleri ayırmak için mikrosaniye içerir. Sadece geçen saate bağlı ihale durumu için tüketiciler tam listeyi yeniden değerlendirmelidir. Kaynak bağlantısı/ihale değişince eski araştırma `stale` olur ve güncel sonuç gibi gösterilmez.

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
