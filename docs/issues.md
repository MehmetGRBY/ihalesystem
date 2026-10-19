# Önerilen ilk GitHub issue'ları

GitHub issue'ları henüz açılmadı; bunlar açılmaya hazır yerel issue taslaklarıdır.

| # | Başlık | Sorumlu | Bağımlılık | Kabul kriteri |
| --- | --- | --- | --- | --- |
| 1 | Ortak Pydantic sözleşmeleri ve JSON Schema v1 | A+B | — | Null, UTC tarih, source/evidence referansları; fixture doğrulama |
| 2 | JSON input/output ve ihale normalizasyonu | A | 1 | Nesne/dizi, Türkçe metin, kayıt bazında hata, atomik çıktı |
| 3 | Güvenli HTTP erişimi ve hata izolasyonu | B | 1 | Robots, host rate limit, redirect kontrolü, 429/5xx retry, CAPTCHA stop |
| 4 | Kazanan collector ve resolver | B | 1,3 | İhale numarasına bağlı açık yüklenici, çelişki ve ortak girişim testleri |
| 5 | Firma sitesi ve açık sicil collector'ları | B | 1,3 | JSON-LD/etiketli HTML, her değer için evidence; bilinmeyenler null |
| 6 | Çok sinyalli company matching | B | 1,4 | İsim tek başına yetmez, kimlik/şehir çelişkisi ve domain testleri |
| 7 | Alan bazında verification ve skorlar | B | 4,5,6 | Yayıncı/kopya dedup, conflicting null, confidence/completeness ayrımı |
| 8 | SQLite repository ve Alembic migration | A | 1 | FK/transaction, tender başına run geçmişi, PostgreSQL uyumlu tipler |
| 9 | CLI composition ve çevrimdışı demo | A | 2,4,7,8 | JSON → DB → çıktı; kaynak arızası diğer kaynakları durdurmaz |
| 10 | İsteğe bağlı arama API provider'ı | B | 3,4 | Yalnız mevcut ihale/firma için keşif; snippet kazanan kanıtı olamaz |
| 11 | CI, type check ve geliştirici rehberi | A | 9 | Ağsız pytest, ruff, mypy, kurulum ve .env.example |
| 12 | İzinli gerçek kaynaklarla EKAP/sicil pilotu | A+B | 9,10 | Gerçek belge fixture'ları, selector kapsamı, yanlış eşleşme örnekleri |

İlk MVP 1–11 için temel uygulamayı içerir. 12 canlı kaynak kapsamını genişletir;
portal otomasyonunun güvenilir olduğu ancak bu pilot sonrasında söylenebilir.
