"""İptal, tarih değişikliği, yayın güncelliği ve proje yaşam döngüsü regresyonları."""
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import bulucu
import ekap_bulletin as bulletin
import opportunities
import project_sources
import source_adapters as adapters
from test_bulletin import BODY, SOURCE


class Clock(datetime):
    current = datetime(2026, 10, 19, 6, tzinfo=adapters.TR)

    @classmethod
    def now(cls, tz=None):
        return cls.current


class PriorityFixTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        for name, value in [('ROOT', self.root), ('DATA', self.data), ('DB', self.data / 'test.sqlite3')]:
            patcher = patch.object(bulucu, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(bulletin, 'STORE', self.data / 'ekap-bulten')
        patcher.start()
        self.addCleanup(patcher.stop)
        Clock.current = datetime(2026, 10, 19, 6, tzinfo=adapters.TR)
        self.source = {'key':'university', 'name':'Üniversite', 'url':'https://example.org/ihaleler', 'adapter':'medipol'}

    def tender(self, path, stage, published, number='2026/054'):
        row = adapters.make_item(self.source, 'VRF Sistemleri Alımı ' + ('İptal' if stage=='iptal' else ''), path,
                                 bulucu.classify, tender_date='27.10.2026 10:30', published=published,
                                 stage=stage, tender_number=number)
        return row

    def test_number_from_cancellation_ikn_suffix_and_title(self):
        info = adapters.detail_info('<main><div class="body">2026/054 İKN’li VRF ihalesinin iptaline karar verilmiştir.</div></main>')
        self.assertEqual(info['tender_number'], '2026/054')
        info = adapters.detail_info('<main>İhale Kayıt Numarası (İKN): 2026 / 054</main>')
        self.assertEqual(info['tender_number'], '2026/054')
        self.assertEqual(adapters.extract_tender_number(title='2026/054 VRF Alımı'), '2026/054')
        self.assertEqual(adapters.extract_tender_number(title='2026/054 ve 2026/055'), '')

    def test_cancellation_merges_with_notice_and_stays_cancelled_when_old_notice_reappears(self):
        notice = self.tender('/notice', 'ilan', '31 Ağustos 2026')
        cancelled = self.tender('/cancel', 'iptal', '07 Eylül 2026')
        with bulucu.connect() as conn:
            bulucu.save_items(conn, [notice, cancelled])
            self.assertEqual(bulucu.save_items(conn, [notice, cancelled]), (0,0))
        rows = bulucu.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], notice['id'])
        self.assertEqual(rows[0]['stage'], 'iptal')
        self.assertEqual(rows[0]['opportunity']['status'], 'arsiv')
        self.assertEqual({x['url'] for x in rows[0]['related_announcements']}, {notice['url'], cancelled['url']})

    def test_cancellation_found_first_still_closes_later_notice(self):
        notice = self.tender('/notice', 'ilan', '31 Ağustos 2026')
        cancelled = self.tender('/cancel', 'iptal', '07 Eylül 2026')
        with bulucu.connect() as conn:
            bulucu.save_items(conn, [cancelled, notice])
        self.assertEqual(len(bulucu.records()), 1)
        self.assertEqual(bulucu.records()[0]['stage'], 'iptal')

    def test_missing_cancel_date_does_not_rewrite_history_on_each_scan(self):
        notice=self.tender('/notice','ilan','31.08.2026')
        cancel=dict(self.tender('/cancel','iptal','07.09.2026'),tender_date_raw='')
        with bulucu.connect() as conn:
            bulucu.save_items(conn,[cancel,notice])
            self.assertEqual(bulucu.save_items(conn,[cancel,notice]),(0,0))
        row=bulucu.records()[0]
        event=next(x for x in row['related_announcements'] if x['stage']=='iptal')
        self.assertEqual(event['tender_date_raw'],'')
        self.assertEqual(row['tender_date_raw'],notice['tender_date_raw'])

    def test_existing_correction_text_repairs_stored_old_deadline(self):
        text=BODY.replace('İhale Kayıt','DÜZELTME İLANI\nİhale Kayıt').replace('27.10.2026','30.10.2026')
        row=bulletin.parse_text(text,SOURCE,bulucu.classify,'BULTEN_20102026_MAL.pdf','20.10.2026')[0][0]
        row['tender_date_raw']='27.10.2026 10:30'
        repaired=bulucu.identified_item(row)[0]
        self.assertEqual(repaired['tender_date_iso'],'2026-10-30T10:30:00+03:00')

    def test_numbers_are_scoped_to_authority_and_missing_numbers_do_not_merge(self):
        one = self.tender('/one', 'ilan', '01.10.2026')
        other = dict(self.tender('/two', 'ilan', '01.10.2026'), source_key='other', id='other')
        missing = self.tender('/three', 'ilan', '', number='')
        another = self.tender('/four', 'ilan', '', number='')
        with bulucu.connect() as conn:
            bulucu.save_items(conn, [one,other,missing,another])
        self.assertEqual(len(bulucu.records()), 4)

    def test_undated_notice_cannot_reopen_cancellation(self):
        with bulucu.connect() as conn:
            bulucu.save_items(conn, [self.tender('/cancel','iptal','07.09.2026'), self.tender('/notice','ilan','')])
        self.assertEqual(bulucu.records()[0]['stage'], 'iptal')

    def test_existing_legacy_database_is_backed_up_and_duplicates_repaired(self):
        notice = self.tender('/notice','ilan','31.08.2026')
        cancelled = self.tender('/cancel','iptal','07.09.2026')
        cancelled.pop('tender_number')
        cancelled['title'] = '2026/054 İKN’li VRF Sistemleri Alımı İhalesi İptal Kararı'
        with contextlib.closing(sqlite3.connect(bulucu.DB)) as conn, conn:
            conn.execute('CREATE TABLE tenders (id TEXT PRIMARY KEY,payload TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,updated_at TEXT NOT NULL,revision INTEGER NOT NULL)')
            for i, row in enumerate([notice,cancelled]):
                stamp = f'2026-10-1{i+1}T12:00:00+03:00'
                conn.execute('INSERT INTO tenders VALUES (?,?,?,?,?,?)',(row['id'],json.dumps(row),stamp,stamp,stamp,i+2))
        rows = bulucu.records()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],notice['id'])
        self.assertEqual(rows[0]['stage'],'iptal')
        self.assertEqual(rows[0]['first_seen_at'],'2026-10-11T12:00:00+03:00')
        self.assertEqual(rows[0]['last_seen_at'],'2026-10-12T12:00:00+03:00')
        self.assertGreater(rows[0]['revision'],3)
        backup = bulucu.DB.with_name('test-before-lifecycle.sqlite3')
        self.assertTrue(backup.exists())
        with contextlib.closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tenders').fetchone()[0],2)
        self.assertEqual(bulucu.records(),rows)

    def test_number_discovered_after_both_urls_were_saved(self):
        notice = self.tender('/notice','ilan','31.08.2026',number='')
        cancelled = self.tender('/cancel','iptal','07.09.2026')
        with bulucu.connect() as conn:
            bulucu.save_items(conn, [notice,cancelled])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tenders').fetchone()[0],2)
            notice['tender_number']='2026/054'
            bulucu.save_items(conn,[notice])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tenders').fetchone()[0],1)
        self.assertEqual(bulucu.records()[0]['stage'],'iptal')

    def test_failed_migration_rolls_back_schema_and_keeps_backup(self):
        with contextlib.closing(sqlite3.connect(bulucu.DB)) as conn, conn:
            conn.execute('CREATE TABLE tenders (id TEXT PRIMARY KEY,payload TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,updated_at TEXT NOT NULL,revision INTEGER NOT NULL)')
            conn.execute('INSERT INTO tenders VALUES (?,?,?,?,?,?)',('broken','{bad json','first','last','updated',1))
        with self.assertRaises(json.JSONDecodeError):
            with bulucu.connect():
                pass
        with contextlib.closing(sqlite3.connect(bulucu.DB)) as conn:
            self.assertNotIn('source_key',{row[1] for row in conn.execute('PRAGMA table_info(tenders)')})
            self.assertEqual(conn.execute('SELECT payload FROM tenders').fetchone()[0],'{bad json')
        self.assertTrue(bulucu.DB.with_name('test-before-lifecycle.sqlite3').exists())

    def test_corrected_explicit_deadline_replaces_old_date(self):
        notice = bulletin.parse_text(BODY,SOURCE,bulucu.classify,'BULTEN_19102026_MAL.pdf','19.10.2026')[0][0]
        text = BODY.replace('İhale Kayıt','DÜZELTME İLANI\nİhale Kayıt').replace('27.10.2026','30.10.2026')
        corrected = bulletin.parse_text(text,SOURCE,bulucu.classify,'BULTEN_20102026_MAL.pdf','20.10.2026')[0][0]
        with bulucu.connect() as conn:
            bulucu.save_items(conn,[notice,corrected,notice])
        row = bulucu.records()[0]
        self.assertEqual(row['stage'],'duzeltme')
        self.assertEqual(row['tender_date_iso'],'2026-10-30T10:30:00+03:00')

    def test_repeated_ekap_bulletin_does_not_create_revisions(self):
        row=bulletin.parse_text(BODY,SOURCE,bulucu.classify,'BULTEN_19102026_MAL.pdf','19.10.2026')[0][0]
        with bulucu.connect() as conn:
            self.assertEqual(bulucu.save_items(conn,[row]),(1,0))
            self.assertEqual(bulucu.save_items(conn,[row]),(0,0))

    def test_correction_uses_replacement_not_original_publication_or_delivery_date(self):
        text = 'İlan tarihi: 19.10.2026\nDüzeltilen hususlar:\nİhale tarihi ve saati: 27.10.2026 10:30 yerine 30.10.2026 14:00 olarak değiştirilmiştir. Teslim tarihi: 01.12.2026'
        self.assertEqual(bulletin.correction_date(text),'30.10.2026 14:00')
        self.assertEqual(bulletin.correction_date('Düzeltilen hususlar: İhale tarihi: 30.10.2026'), '30.10.2026')
        self.assertEqual(bulletin.correction_date('İhale tarihi: 30 Ekim 2026 14:00'), '30 ekim 2026 14:00')
        self.assertEqual(bulletin.correction_date('İhale tarihi: 30.10.2026 14:00. Teslim tarihi: 01.12.2026 yerine 02.12.2026'), '30.10.2026 14:00')

    def test_generic_cancel_closes_known_notice_but_is_not_an_unrelated_lead(self):
        cancel = adapters.make_item(self.source,'2026/054 İptal Kararı','/cancel',bulucu.classify,published='07.09.2026')
        unrelated = adapters.make_item(self.source,'2026/999 İptal Kararı','/other',bulucu.classify,published='07.09.2026')
        with bulucu.connect() as conn:
            bulucu.save_items(conn,[cancel,unrelated,self.tender('/notice','ilan','31.08.2026')])
        rows=bulucu.records()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['stage'],'iptal')
        self.assertEqual(rows[0]['relevance'],'dogrudan')

    def test_generic_pdf_cancel_can_close_old_hvac_record(self):
        notice=bulletin.parse_text(BODY,SOURCE,bulucu.classify,'BULTEN_19102026_MAL.pdf','19.10.2026')[0][0]
        for title in ['Mal Alımı','Akaryakıt Alımı']:
            with self.subTest(title=title):
                text=BODY.replace('KLİMA ALINACAKTIR','İPTAL İLANI').replace('VRF Klima\nSistemleri Alımı',title).replace('İhale Kayıt','İhale iptal edilmiştir.\nİhale Kayıt')
                cancel=bulletin.parse_text(text,SOURCE,bulucu.classify,'BULTEN_20102026_MAL.pdf','20.10.2026')[0][0]
                self.assertTrue(cancel['lifecycle_only'])
                with bulucu.connect() as conn:
                    bulucu.save_items(conn,[notice,cancel])
                self.assertEqual(bulucu.records()[0]['opportunity']['status'],'arsiv')

    def test_correction_without_deadline_keeps_known_date(self):
        notice = bulletin.parse_text(BODY,SOURCE,bulucu.classify,'BULTEN_19102026_MAL.pdf','19.10.2026')[0][0]
        text = BODY.replace('İhale Kayıt','DÜZELTME İLANI\nİhale Kayıt') + '\nDüzeltilen hususlar: Teslim tarihi: 01.12.2026 olarak değiştirilmiştir.'
        corrected = bulletin.parse_text(text,SOURCE,bulucu.classify,'BULTEN_20102026_MAL.pdf','20.10.2026')[0][0]
        self.assertFalse(corrected['tender_date_raw'])
        merged=bulletin.merge_record(notice,corrected)
        self.assertEqual(merged['tender_date_iso'],notice['tender_date_iso'])

    def collect_empty(self, config):
        with patch.object(bulletin,'download',return_value=[]),contextlib.redirect_stdout(io.StringIO()):
            return bulletin.collect(config,bulucu.classify)

    def test_today_is_provisional_and_not_counted_as_remaining_backfill(self):
        config={'archive_days':3,'backfill_batch_days':1}
        with patch.object(bulletin,'datetime',Clock):
            self.collect_empty(config)
            progress=json.loads((bulletin.STORE/'archive-progress.json').read_text())
            self.assertNotIn('2026-10-19',progress['completed_dates'])
            self.assertIn('2026-10-19',progress['provisional_dates'])
            self.assertEqual(bulletin.progress_summary(config),{'target_days':3,'completed_days':2,'provisional_days':1,'remaining_days':0})

    def test_yesterday_is_rechecked_after_starting_before_publication(self):
        config={'archive_days':4,'bulletin_days':1,'backfill_batch_days':1}
        with patch.object(bulletin,'datetime',Clock):
            self.collect_empty(config)
            Clock.current += timedelta(days=1)
            with patch.object(bulletin,'download',return_value=[]) as download, contextlib.redirect_stdout(io.StringIO()):
                bulletin.collect(config,bulucu.classify)
            requested={call.args[1].isoformat() for call in download.call_args_list}
            self.assertIn('2026-10-19',requested)
            self.assertIn('2026-10-18',requested)

    def test_legacy_completed_today_is_not_trusted_as_final(self):
        bulletin.STORE.mkdir()
        path=bulletin.STORE/'archive-progress.json'
        path.write_text(json.dumps({'completed_dates':['2026-10-19']}))
        with patch.object(bulletin,'datetime',Clock):
            self.assertEqual(bulletin.progress_summary({'archive_days':1})['remaining_days'],1)
            self.collect_empty({'archive_days':1})
            self.assertEqual(json.loads(path.read_text())['completed_dates'],[])

    def test_failed_day_is_not_completed_and_backfill_resumes(self):
        config={'archive_days':6,'backfill_batch_days':1}
        def fail(kind,date):
            if date.isoformat()=='2026-10-17':
                raise OSError('ağ yok')
            return []
        with patch.object(bulletin,'datetime',Clock):
            with patch.object(bulletin,'download',side_effect=fail),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):
                bulletin.collect(config,bulucu.classify)
            self.assertNotIn('2026-10-17',json.loads((bulletin.STORE/'archive-progress.json').read_text())['completed_dates'])
            self.collect_empty(config)
            first=bulletin.progress_summary(config)['completed_days']
            self.collect_empty(config)
            self.assertGreater(bulletin.progress_summary(config)['completed_days'],first)

    def test_recent_negative_cache_expires_but_old_nonpublication_is_reused(self):
        bulletin.STORE.mkdir()
        def fake_curl(args):
            target=Path(args[args.index('-o')+1])
            html='<p>Kamu İhale Bülteni yayımlanmamıştır!</p>' if '--data-binary' in args else '<input type="hidden" name="__VIEWSTATE" value="x"><select name="kind"><option value="2">Yapım</option></select>'
            target.write_text(html)
        for age,expected in [(1,2),(20,0)]:
            day=Clock.current.date()-timedelta(days=age)
            cache=bulletin.STORE/f'{day:%Y%m%d}_Yapim.json'
            cache.write_text('[]')
            old=Clock.current.timestamp()-5*3600
            os.utime(cache,(old,old))
            with self.subTest(age=age),patch.object(bulletin,'datetime',Clock),patch.object(bulletin,'curl',side_effect=fake_curl) as download:
                self.assertEqual(bulletin.download('Yapim',day),[])
                self.assertEqual(download.call_count,expected)

    def project_scan(self, html=None, failure=False, warnings=None):
        source={'key':'emlak_projects','name':'Projeler','url':'https://example.org','adapter':'emlak_projects'}
        (self.root/'config.json').write_text(json.dumps({'sources':[source]}))
        if failure:
            mocked=patch.object(bulucu,'collect_source',side_effect=OSError('ağ yok'))
        else:
            rows,count=project_sources.emlak_projects(html,source)
            mocked=patch.object(bulucu,'collect_source',return_value=(rows,count,1,warnings or []))
        with mocked,contextlib.redirect_stdout(io.StringIO()):
            return bulucu.scan()

    def card(self, title='Proje A', status='devam-eden'):
        return f'<div class="single-p durum-{status}"><span class="sing-title">{title}</span></div>'

    def test_project_changes_to_delivery_and_archive_then_can_reopen(self):
        self.project_scan(self.card())
        self.assertEqual(bulucu.records()[0]['opportunity']['status'],'proje')
        self.project_scan(self.card(status='hemen-teslim'))
        self.assertEqual(bulucu.records()[0]['opportunity']['status'],'arsiv')
        self.project_scan(self.card())
        self.assertEqual(bulucu.records()[0]['opportunity']['status'],'proje')

    def test_missing_project_requires_verification_and_preserves_last_seen(self):
        self.project_scan(self.card())
        before=bulucu.records()[0]
        self.project_scan(self.card('Proje B'))
        row=next(r for r in bulucu.records() if r['title']=='Proje A')
        self.assertEqual(row['opportunity']['status'],'kontrol')
        self.assertEqual(row['source_presence'],'missing')
        self.assertEqual(row['last_seen_at'],before['last_seen_at'])
        revision=row['revision']
        self.project_scan(self.card('Proje B'))
        row=next(r for r in bulucu.records() if r['title']=='Proje A')
        self.assertEqual(row['revision'],revision)
        self.project_scan(self.card())
        row=next(r for r in bulucu.records() if r['title']=='Proje A')
        self.assertEqual(row['source_presence'],'present')
        self.assertEqual(row['opportunity']['status'],'proje')
        self.assertNotIn('missing_since_at',row)

    def test_error_or_partial_project_scan_does_not_mark_projects_missing(self):
        self.project_scan(self.card())
        self.project_scan(failure=True)
        self.assertEqual(bulucu.records()[0]['source_presence'],'present')
        self.project_scan(self.card('Proje B'),warnings=['Eksik liste'])
        row=next(r for r in bulucu.records() if r['title']=='Proje A')
        self.assertEqual(row['source_presence'],'present')

    def test_project_markup_without_title_is_rejected(self):
        with self.assertRaises(ValueError):
            project_sources.emlak_projects(self.card()+'<div class="single-p"></div>',{'key':'emlak_projects','name':'Projeler','url':'https://example.org'})


if __name__=='__main__':
    unittest.main()
