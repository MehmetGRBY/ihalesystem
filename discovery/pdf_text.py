"""PDF çizim sırasını koruyarak bülten tablo alanlarını hızlı okur."""
def trace_page(page):
    parts=[]
    previous=None
    for span in sorted(page.get_texttrace(),key=lambda s:s['seqno']):
        if not span['chars']:
            continue
        value=''.join(chr(c[0]) for c in span['chars'] if c[0]>=0)
        origin=span['chars'][0][2]
        if previous:
            if abs(origin[1]-previous[1])>3:
                parts.append('\n')
            elif span['bbox'][0]-previous[2]>1.5:
                parts.append(' ')
        parts.append(value)
        previous=(origin[0],origin[1],span['bbox'][2])
    return ''.join(parts)


def read_pdf(path,fast=True):
    if fast:
        try:
            import pymupdf
            with pymupdf.open(path) as doc:
                text='\f'.join(trace_page(page) for page in doc)
                if text.strip():
                    return text,len(doc),'pymupdf-trace'
        except ImportError:
            pass
    from pypdf import PdfReader
    reader=PdfReader(path)
    return '\f'.join(page.extract_text() or '' for page in reader.pages),len(reader.pages),'pypdf'
