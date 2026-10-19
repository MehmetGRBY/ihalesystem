# TenderEnricher

Yerelde çalışan, mevcut ihale/proje kayıtlarının **kazanan firma bilgilerini**
açık kaynak kanıtlarıyla tamamlayan Python MVP. Yeni ihale keşfetmez.

## Başlangıç

Python 3.11+ gerekir. Bu repository'de geliştirme için editable install kullanın.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

Anahtar, browser veya internet gerektirmeyen sentetik demo:

```bash
tender-enricher demo
```

Demo `data/demo.db` ve `data/outbox/demo-results.json` üretir. İki örnekten biri
kanıtlarıyla tamamlanır, diğeri `unresolved` döner. Bütün demo çıktıları ve
kaynakları `is_demo: true` taşır. Demo firma, adres ve telefon **gerçek değildir**.

Normal JSON giriş yolu:

```bash
cp data/inbox/tenders.example.json data/inbox/tenders.json
tender-enricher run
```

Bu dört alanlı örnekte kazananı doğrulayacak kaynak yoktur: anahtar olmadan
sonuç `winner: null`, `status: unresolved` olur. Gerçek kaynak URL'leri ekleyin
veya isteğe bağlı `TE_BRAVE_API_KEY` ayarlayın. Arama API'si kendi hesabınızı ve
planınızı kullanır; anahtar yoksa arama yapılmaz. Arama snippet'i kanıt sayılmaz;
bulunan sayfalar erişim politikası üzerinden ayrıca indirilir.

```json
{
  "tender_id": "2026/123456",
  "title": "150 Yataklı Devlet Hastanesi Yapım İşi",
  "authority": "Sağlık Bakanlığı",
  "location": "Van",
  "award_urls": ["https://kurumun-gercek-adresi.gov.tr/ihale-sonucu"],
  "company_urls": ["https://firmanin-gercek-adresi.com.tr/iletisim"],
  "registry_urls": []
}
```

Yukarıdaki domainler yalnızca formatı anlatan yer tutuculardır. Tek JSON nesnesi
veya nesne dizisi desteklenir. Başka alanlar sessizce atılmaz: şema hatası oluşur.
Mevcut sistemdeki ekstra alanları ileride input adapter dönüştürür.

## Komutlar

```bash
tender-enricher init-db
tender-enricher run --input data/inbox/tenders.json --output data/outbox/results.json
tender-enricher export --tender-id 2026/123456 --output data/outbox/latest.json
tender-enricher schema
```

`run` ve `demo` Alembic migration'larını önce uygular. Aynı ihalenin her yeniden
işlenmesi ayrı run oluşturur; geçmiş silinmez. `export` veritabanındaki son run'ı
çıkarır. `--database-url` her veri komutunda desteklenir.

Browser yalnızca açıkça etkinleştirilirse kullanılır:

```bash
python -m playwright install chromium
tender-enricher run --browser
```

Browser aynı origin'deki sınırlı GET document/script/xhr/fetch isteklerini yükler;
üçüncü taraflar, WebSocket, form POST, servis worker ve medya istekleri engellenir.
HTTP preflight robots/erişim korumasında durursa browser açılmaz. Bu renderer
giriş, CAPTCHA çözümü veya EKAP portalında otomatik navigasyon yapmaz.

## Çıktı ve kararlar

`schemas/` altındaki JSON Schema dosyaları **tek kayıt** sözleşmesidir; dosya
adapter'ı sonuçları dizi olarak yazar. Her sonuç:

* `winner`: doğrulanmış kazananın alanları; alan bilinmiyorsa `null`.
  Kazanan tespit edilemiyor/çelişiyorsa nesnenin tamamı `null`.
* `sources`: URL, redirect sonrası URL, yayıncı grubu, UTC alım zamanı, içerik
  SHA-256 hash'i ve kaynak sınıfı.
* `evidence`: alan/değer, source_id, kısa alıntı ve parser konumu. Reddedilen
  adayın gözlemleri de denetim için tutulur; nihai alanları desteklemez.
* `field_verification`: her alanın skoru, durum, evidence_id referansları ve
  çelişki alternatifleri. İki farklı değer varsa nihai alan `null` olur.
* `winner_confidence`: kazanan kararının kural skoru.
* `confidence`: dolu alanların ortalama skorunun kazanan skoru ile sınırlanması.
* `completeness`: 12 firma alanının dolu olan oranı. Güven skorundan ayrıdır.
* `issues`: kaynak arızası, eşleşme reddi ve inceleme nedenleri.

Durumlar: `resolved` = kazanan kabul edildi ve unvan/telefon/e-posta/web/adres/il
bağımsız kaynaklarla doğrulandı; `partial` = kazanan kabul edildi ama bu alanlar
eksik veya tek kaynaklı; `review_required` = kazanan/alan çelişkisi veya yetersiz
kazanan doğrulaması; `unresolved` = kazanan kanıtı yok; `failed` = giriş/DB hatası.

Skorlar istatistiksel olasılık veya doğruluk garantisi değildir. Tek resmi sonuç
kazanan için 0.90, iki bağımsız haber 0.85 verir; tek haber onaylanmaz. Alanların
temel skorları resmi sonuç/açık resmi sicil 0.95, şirket sitesi 0.75, diğer açık
sayfa 0.60; bağımsız destek +0.15, tavan 0.98. Aynı yayıncı veya aynı içerik hash'i
bağımsız destek sayılmaz. Parafraz edilmiş kopya haberler otomatik saptanmaz.

## Desteklenen kaynak biçimleri ve sınırlar

Detaylar: [collector sözleşmesi](docs/collectors.md).

MVP etiketli HTML sonuçlarını ve firma Organization JSON-LD/açık etiketli HTML
sayfalarını okur. Otomatik site çapında crawling, PDF/OCR, login gerektiren sicil
ve MERSİS servisleri, konsorsiyum ortaklarını ayrıştırma kapsam dışıdır.
EKAP/KİK alan adları kaynak sınıfı için tanımlıdır; güncel EKAP portal DOM'u ve
izinli gerçek ihale örnekleriyle canlı doğrulama henüz yapılmadı.

Firma adı tek başına otomatik eşleştirme sağlamaz. Domain, açık adres veya aynı
resmi kimlik gibi destek aranır; kimlik/şehir/domain çelişkisi aday reddidir.
İhale lokasyonu şirketin ili yerine geçirilmez. Eksik kimlik alanları üretilmez.

Web katmanı robots, crawl-delay, host rate limit, redirect hedef kontrolleri,
timeout, sayfa/boyut bütçesi ve sınırlı retry uygular. 401/403 veya koruma sayfası
algılanırsa durur. Bu yerel araştırma aracının DNS kontrolleri ayrı bir ağ egress
izolasyonunun yerini tutmaz; halka açık bir URL-fetch servisi olarak dağıtımı MVP
kapsamında değildir.

## Geliştirme ve iki kişilik iş bölümü

[Mimari ve görev dağılımı](docs/architecture.md), [ilk issue taslakları](docs/issues.md),
[geliştirme rehberi](docs/development.md). GitHub deposu:
[1Phaser1/TenderEnricher](https://github.com/1Phaser1/TenderEnricher).
Issue'lar yerel taslaklardır; GitHub issue/PR henüz açılmamıştır.

```bash
pytest --cov=tender_enricher --cov-report=term-missing
ruff check .
ruff format --check .
mypy
```

Testler canlı internete çıkmaz. Fixture/MockTransport ve geçici SQLite kullanır.
CI Python 3.11 ve 3.14 için aynı kontrolleri çalıştıracak şekilde hazırlanmıştır.
`.env`, DB dosyaları ve çalışma çıktıları Git'e dahil edilmez.

PostgreSQL için `pip install -e '.[postgres]'`, sonra
`TE_DATABASE_URL=postgresql+psycopg://...` ayarlayın. Migration SQL'i PostgreSQL
dialect'iyle test edilir; gerçek PostgreSQL sunucusunda çalışma henüz test edilmedi.

Kullanılan API sözleşmeleri için resmi belgeler:
[Pydantic](https://docs.pydantic.dev/latest/concepts/models/),
[SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/quickstart.html),
[Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[Playwright network](https://playwright.dev/python/docs/network),
[Brave Search](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started).
