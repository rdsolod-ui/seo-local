import unittest, threading, tempfile, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from seo_local.network import Network
from seo_local.technical import relationship_findings
from seo_local.crawler import Engine
from seo_local.storage import Store

class Fixture(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  b=f'http://127.0.0.1:{self.server.server_port}'
  self.server.hits[self.path]=self.server.hits.get(self.path,0)+1
  code=200;kind='text/html';extra={}
  if self.path=='/robots.txt': body='User-agent: *\nSitemap: '+b+'/sitemap.xml';kind='text/plain'
  elif self.path=='/sitemap.xml': body=f'<urlset><url><loc>{b}/a</loc></url><url><loc>{b}/a</loc></url><url><loc>{b}/missing</loc></url></urlset>';kind='application/xml'
  elif self.path=='/': body=f'<html><link rel="canonical" href="{b}/a"><link rel="alternate" hreflang="en" href="{b}/a"><h1>Home</h1></html>'
  elif self.path=='/a': body=f'<html><meta name="robots" content="noindex"><link rel="canonical" href="{b}/"><h1>A</h1></html>'
  elif self.path=='/retry':
   code=503 if self.server.hits[self.path]<2 else 200;extra={'Retry-After':'0'};body='retry'
  elif self.path=='/busy': code=429;extra={'Retry-After':'120'};body='busy'
  elif self.path=='/always': code=503;extra={'Retry-After':'0'};body='busy'
  else: code=404;body='missing'
  raw=body.encode();self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
  for k,v in extra.items():self.send_header(k,v)
  self.end_headers();self.wfile.write(raw)

class TechnicalTests(unittest.TestCase):
 def setUp(self):
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);self.server.hits={};threading.Thread(target=self.server.serve_forever,daemon=True).start();self.base=f'http://127.0.0.1:{self.server.server_port}'
 def tearDown(self):self.server.shutdown();self.server.server_close()
 def test_real_relations_crawl(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'test.db');p=store.add_project('test',self.base+'/');e=Engine(store,True);key=e.start(p['id'],10,.5);e.jobs[key][0].join(20)
   r=e.result(key);codes={i['code'] for i in r['issues']}
   self.assertTrue({'canonical_cycle','canonical_chain','canonical_target_noindex','hreflang_return','sitemap_duplicate','sitemap_noindex','sitemap_http_error'}<=codes,codes)
   self.assertEqual(r['status'],'completed')
 def test_retry_recovers(self):
  r=Network(True,delay=0).fetch(self.base+'/retry',self.base);self.assertEqual((r['status'],r['attempts']),(200,2))
 def test_retry_is_bounded(self):
  r=Network(True,delay=0).fetch(self.base+'/always',self.base);self.assertEqual(r['attempts'],3);self.assertGreater(r['retry_at'],time.time());self.assertEqual(self.server.hits['/always'],3)
 def test_long_retry_keeps_queue(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'test.db');p=store.add_project('test',self.base+'/busy');e=Engine(store,True);key=e.start(p['id'],10,.5);e.jobs[key][0].join(20);r=e.result(key)
   self.assertEqual(r['status'],'paused');self.assertIn(self.base+'/busy',r['pending']);self.assertEqual(len(r['pages']),0)
   with self.assertRaises(ValueError):e.resume(key)
 def test_private_address_not_retried(self):
  r=Network(delay=0).fetch('http://127.0.0.1/','http://127.0.0.1');self.assertEqual(r['attempts'],1);self.assertNotIn('retry_at',r)
 def test_retry_date(self):
  value=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=60));self.assertTrue(58<=Network.retry_delay(value,2)<=60);self.assertEqual(Network.retry_delay('bad',2),2)
 def test_unknown_is_not_healthy(self):
  p={'url':'https://example.com/','status':200,'html':True,'canonical':['https://elsewhere.com/'],'hreflang':[{'lang':'en','url':'https://elsewhere.com/'}]}
  codes={i['code'] for i in relationship_findings({'pages':[p],'url':p['url'],'sitemap_urls':['https://unknown.com/']})}
  self.assertTrue({'canonical_target_unchecked','hreflang_target_unchecked','sitemap_unchecked'}<=codes);self.assertNotIn('hreflang_return',codes)

if __name__=='__main__':unittest.main()
