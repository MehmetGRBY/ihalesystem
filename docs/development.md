# Geliştirme rehberi

## Modül sınırları

* `models.py` ve `ports.py`: iki geliştiricinin ortak sözleşmesi. Değişiklikte
  schema'yı üretin, örnekleri ve acceptance testini güncelleyin.
* A: input/output adapter, normalization, CLI composition, SQLAlchemy/Alembic.
* B: collector, kaynak erişimi, resolver, matching, verification.
* Provider'lar sadece gözlem üretir; resolver/verifier network çağırmaz. Core
  dosya/DB/HTML kütüphanelerine bağlı değildir.

Küçük PR'larda tek modül/iş davranışı değişsin. Contract değişikliği önce ortak
incelensin. Anahtar veya gerçek şirket verisini fixture'a koymayın. CI'daki
testler network kullanmaz. Canlı pilot ayrı ve açık URL'lerle yapılmalıdır.

## Yerel görev sırası

1. `tender-enricher demo` ile veri akışını gözlemleyin.
2. `models.py`, `ports.py`, `tests/test_adapters_pipeline_db.py` okuyun.
3. [Issue taslaklarından](issues.md) bir modülü seçin; fixture/test ile ilerleyin.
4. `pytest`, `ruff check .`, `ruff format --check .`, `mypy` çalıştırın.
5. Contract değiştiyse `tender-enricher schema`; üretilen dosyaları PR'a ekleyin.

## Migration

```bash
alembic revision --autogenerate -m "describe the schema change"
alembic upgrade head
```

Veritabanı URL'si `.env`/`TE_DATABASE_URL` üzerinden okunur. Migration dosyasını
inceleyin: mevcut ORM modellerinden dinamik tablo üretmeyin; migration kendi
sabit şemasını taşısın. SQLite'a özel SQL gerekirse PostgreSQL farkı açıkça
test edilsin. Run/profile/evidence tek transaction içinde kaydedilir.

## Hata davranışı

Beklenen erişim hataları `CollectionError(code, safe_message)` üretir. Koruma
sayfaları tekrar denenmez; retry yalnız geçici network/429/5xx içindir. Anahtar,
connection string veya response header'larını loglamayın. Provider istisnası
diğer provider'ları durdurmaz. DB hatası sonucu `failed` yapar ama JSON'da toplanan
gözlemler korunur. CLI failed kayıt varsa exit 2; partial/review/unresolved
normal araştırma sonucu olarak exit 0 döner.

Yapısal olarak bozuk JSON dosyası komutu durdurur. Geçerli JSON içindeki bozuk
tek kayıt ise failed output kaydı olur; diğer kayıtlar işlenir. Geçersiz ihale
kimliği relational tender tablosuna yazılmaz, çıktı hata kaydı korunur.

## Gerçek entegrasyon

Mevcut sisteme erişim geldiğinde `InputAdapter.read()` implementasyonu kayıtları
`TenderInput` modeline dönüştürür. `OutputAdapter.write()` implementasyonu aynı
`EnrichmentResult` sözleşmesini mevcut sisteme aktarır. Dosya adapter'larının
CLI'daki bağlanması değiştirilir; core karar kuralları değişmez.

## Bilinen doğrulama sınırları

Yerel demo/testler gerçek ihale sonucunun doğruluğunu kanıtlamaz. Canlı EKAP,
Brave hesabı, Playwright/Chromium ile gerçek site render'ı ve gerçek PostgreSQL
sunucusu ayrı pilot testleridir. Browser erişim politikası birim testleriyle,
PostgreSQL şema uyumu dialect üzerinden SQL üretimiyle kontrol edilir.
