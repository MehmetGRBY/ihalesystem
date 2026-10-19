# Collector sözleşmesi

Collector yalnızca gözlem üretir: `Collection(sources, winner_claims, candidates,
issues)`. Karar, eşleştirme ve confidence business logic'e aittir. URL keşif sonucu
tek başına `WinnerClaim` olamaz. Her claim ve alan `Evidence` taşır.

## PublicAwardCollector

`collectors/ekap/award.py` açık kaynak URL'lerini okur; ismi EKAP desteğinin
canlı portalda doğrulandığı anlamına gelmez. MVP parser:

* İki sütunlu `tr` içindeki etiket/değer, `dt`/`dd` ve `p`/`li` içindeki
  `Etiket: değer` biçimini destekler.
* Sayfada tek bir etiketli tam ihale numarası (`İKN`, `İhale Kayıt Numarası`,
  `İhale Numarası`) ve tek bir açık kazanan (`Yüklenici`, `İhaleyi Kazanan`,
  `Kazanan Firma`) bulunmalıdır.
* Birden fazla ihale numarası bulunan toplu sonuçları güvenli biçimde ayırmaz;
  bu sayfaları desteklenmeyen format olarak kaydeder.
* Firma şehir/adres/kimlik bilgisi sadece `#winner-details` veya
  `#yuklenici-bilgileri` bölümünde açıkça yazılmışsa alınır. Sayfanın genel `İl`
  alanı projeye veya kuruma ait olabilir.
* İptal/iş ortaklığı/konsorsiyum veya farklı kazananları incelemeye ayırır.

Örnek desteklenen belge:

```html
<p>İKN: 2026/123456</p>
<p>Yüklenici: ABC İnşaat A.Ş.</p>
<section id="winner-details">
  <p>Web Sitesi: https://firma.example/</p>
  <p>Firma İli: İstanbul</p>
</section>
```

Yeni resmi DOM için ayrı provider yazın; örnekten alınan selector'ları genel
business logic'e taşımayın. Gerçek belge fixture'ında tam ihale bağlantısını,
sonuç/iptal durumunu, tarihini ve kazanan rolünü test edin.

## CompanyWebsiteCollector ve PublicRegistryCollector

Organization/Corporation/LocalBusiness/GeneralContractor JSON-LD, dizi ve `@graph`
desteklenir. `legalName` öncelikli, `name` fallback'tir. telephone/email/url,
PostalAddress ve açık taxID/MERSİS PropertyValue okunur. Kimlikler sayı değil
string olmalıdır; geçersiz uzunluk veya 11 haneli kişisel vergi kimliği alınmaz.

PostalAddress'in addressRegion değeri il, addressLocality değeri ilçe olarak
**yalnız region da varsa** alınır. Kaynak bu alanları farklı anlamda kullanıyorsa
özel provider gerekir; eksik bölge ihale lokasyonundan tamamlanmaz.

Sicil collector aynı saf HTML parser'ı kullanır; login veya varsayılan registry
arama endpoint'i kullanmaz. Trust yalnızca ayarlardaki exact hostname üzerinden
gelir. Şirket URL'sini belirten üçüncü taraf dizin firma sitesi sayılmaz.

MVP sadece verilen, kazanan belgesinde açıkça yayımlanan veya arama API'sinde
bulunan URL'leri ziyaret eder. Otomatik bütün siteyi/iletişim linklerini taramaz.
İletişim sayfasını `company_urls` ile vermek desteklenir. Bir kaynakta farklı
telefon değerleri varsa hepsi korunur; verification seçmek yerine çelişki döner.

## Yeni provider eklemek

1. Kaynağın public/izinli erişim biçimini ve parser kapsamını belgeleyin.
2. `PageFetcher` veya kaynağa özel yasal API kullanın; scraping kodu core'a girmesin.
3. URL, retrieval zamanı ve içerik hash'ini `Source` ile kaydedin.
4. Her dolu alan için gözlenen değeri, locator ve excerpt'i `Evidence` ile döndürün.
5. Parser belirsizse iddia üretmeyin; issue ile incelemeye gönderin.
6. Fixture ile başarılı sonuç, yanlış firma/ihale, erişim hatası ve format
   değişimini test edin; CLI composition'da provider'ı ekleyin.

`TE_OFFICIAL_AWARD_HOSTS`/`TE_REGISTRY_HOSTS` işletmeci ayarıdır; sadece bilinen
resmi yayıncıları ekleyin. Herhangi bir input kaydı resmi güven etiketi veremez.
