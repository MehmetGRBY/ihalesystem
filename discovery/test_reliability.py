import unittest
from unittest.mock import patch
from urllib.error import URLError, HTTPError
import company_contacts
import network
import ekap_bulletin
from types import SimpleNamespace
import tempfile
import json
from pathlib import Path
import bulucu
import pdf_text


class ReliabilityTests(unittest.TestCase):
    def test_archive_scan_keeps_other_source_status(self):
        with tempfile.TemporaryDirectory(dir=bulucu.ROOT) as directory:
            root=Path(directory)
            config={'sources':[{'key':'ekap','name':'EKAP','url':'https://ekap.kik.gov.tr','adapter':'ekap_bulletin'}, {'key':'city','name':'Belediye','url':'https://example.org'}]}
            (root/'config.json').write_text(json.dumps(config),encoding='utf-8')
            with patch.object(bulucu,'ROOT',root),patch.object(bulucu,'DATA',root),patch.object(bulucu,'DB',root/'test.sqlite3'),patch.object(bulucu,'collect_source',return_value=([],0,0,[])) as collect,patch('ekap_bulletin.progress_summary',return_value={'remaining_days':1}):
                with bulucu.connect() as conn:
                    previous={'finished_at':'2026-10-13T08:00:00+03:00','sources':[{'name':'Belediye','url':'https://example.org','status':'ok','found':5}]}
                    conn.execute('INSERT INTO scans(payload) VALUES (?)',(json.dumps(previous),))
                result=bulucu.scan(only_sources={'ekap'})
                self.assertEqual(collect.call_count,1)
                city=next(s for s in result['sources'] if s['name']=='Belediye')
                self.assertEqual(city['found'],5)
                self.assertEqual(city['last_checked_at'],previous['finished_at'])

    def test_pdf_draw_order_does_not_mix_columns(self):
        def span(word,x,y,seq):
            return {'seqno':seq,'bbox':(x,y,x+len(word)*5,y+10),'chars':[(ord(c),0,(x+i*5,y),()) for i,c in enumerate(word)]}
        page=SimpleNamespace(get_texttrace=lambda:[span('Sonuc',0,20,2),span('2026/123',60,0,1),span('IKN:',0,0,0)])
        self.assertEqual(pdf_text.trace_page(page),'IKN: 2026/123\nSonuc')

    def test_bulletin_dns_failure_retries(self):
        failed=SimpleNamespace(returncode=6,stderr=b'dns')
        success=SimpleNamespace(returncode=0,stderr=b'')
        with patch('ekap_bulletin.subprocess.run',side_effect=[failed,success]) as request, patch('ekap_bulletin.time.sleep'):
            ekap_bulletin.curl(['https://example.org'])
            self.assertEqual(request.call_count,2)

    def test_temporary_dns_failure_retries(self):
        with patch('network.urllib.request.urlopen', side_effect=URLError('dns')) as request, patch('network.time.sleep'):
            with self.assertRaises(URLError):
                network.fetch_html('https://example.org')
            self.assertEqual(request.call_count, 3)

    def test_forbidden_does_not_retry(self):
        with patch('network.urllib.request.urlopen', side_effect=HTTPError('https://example.org',403,'Forbidden',{},None)) as request:
            with self.assertRaises(HTTPError):
                network.fetch_html('https://example.org')
            self.assertEqual(request.call_count, 1)

    def test_short_company_name_is_not_matched(self):
        row=company_contacts.enrich({'contractors':[{'name':'Akar İnşaat'}]})
        self.assertEqual(row['contacts'], [])

    def test_joint_venture_member_and_idempotence(self):
        row={'contractors':[{'name':company_contacts.DIRECTORY[1][0]+' , Veysi Özer İş Ortaklığı'}]}
        enriched=company_contacts.enrich(row)
        self.assertEqual(enriched['contacts'][0]['contact_scope'], 'grup merkezi')
        self.assertEqual(company_contacts.enrich(enriched), enriched)

if __name__=='__main__':
    unittest.main()
