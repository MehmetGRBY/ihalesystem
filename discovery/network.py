"""Geçici DNS/bağlantı hatalarında sınırlı tekrar; TLS doğrulaması korunur."""
import time
import urllib.request
import urllib.error


def fetch_html(url,attempts=3):
    request=urllib.request.Request(url,headers={'User-Agent':'EFA-Ihale-Bulucu/1.0','Accept':'text/html'})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request,timeout=30) as response:
                raw=response.read(5*1024*1024+1)
                if len(raw)>5*1024*1024:
                    raise ValueError('HTML yanıtı 5 MB sınırını aşıyor')
                charset=response.headers.get_content_charset() or 'utf-8'
                return raw.decode(charset,errors='replace')
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt+1==attempts:
                raise
        except (urllib.error.URLError,TimeoutError,ConnectionError):
            if attempt+1==attempts:
                raise
        time.sleep(2**attempt)
