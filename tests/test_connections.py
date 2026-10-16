import json, os, tempfile, threading, time, unittest
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen, build_opener
from urllib.error import HTTPError
from seo_local.connections import Connections, ProviderError, NoRedirect, request_json, report
from seo_local.storage import Store
from seo_local.server import make_server

class FakeProvider:
 def __init__(self):self.calls=[];self.fail=None;self.token_count=0
 def __call__(self,url,**kw):
  self.calls.append((url,kw))
  if self.fail:raise ProviderError(self.fail)
  if url.endswith('/token'):
   self.token_count+=1;return {'access_token':'fixture-access-'+str(self.token_count),'refresh_token':'fixture-refresh','expires_in':3600}
  if url.endswith('/sites'):return {'siteEntry':[{'siteUrl':'sc-domain:example.com','permissionLevel':'siteOwner'}]}
  if url.endswith('/user'):return {'user_id':123}
  if url.endswith('/hosts'):return {'hosts':[{'host_id':'https:example.com:443','ascii_host_url':'https://example.com/','verified':True}]}
  if 'searchAnalytics' in url:return {'rows':[{'keys':['<script>fixture</script>'],'clicks':4,'impressions':20,'position':3},{'keys':['second'],'clicks':6,'impressions':80,'position':8}]}
  if 'search-queries/popular' in url:return {'date_from':'2026-09-02','date_to':'2026-09-06','queries':[{'query_text':'fixture','indicators':{'TOTAL_SHOWS':50,'AVG_SHOW_POSITION':4}}]}
  raise AssertionError(url)

class ConnectionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db.sqlite3');self.p=self.store.add_project('Fixture','https://example.com/');self.fake=FakeProvider();self.c=Connections(self.temp.name,self.store,'https://owner.example/seo-local/',self.fake)
 def tearDown(self):self.temp.cleanup()
 def connect(self,key='google'):
  self.c.configure(key,'fixture-id','fixture-secret');url,cookie=self.c.begin(key);q=parse_qs(urlsplit(url).query);self.c.callback(key,q['state'][0],cookie,'fixture-code');return q
 def test_pkce_scopes_and_secrets_not_exposed(self):
  for key in ['google','yandex']:
   q=self.connect(key);self.assertEqual(q['code_challenge_method'],['S256']);self.assertNotIn('client_secret',q);self.assertEqual(len(q['code_challenge'][0]),43)
  state=json.dumps(self.c.status());self.assertNotIn('fixture-secret',state);self.assertNotIn('fixture-access',state);self.assertIn('webmasters.readonly',state);self.assertNotIn('webmaster:verify',state)
 def test_callback_requires_same_browser_and_single_use(self):
  self.c.configure('google','id','secret');url,cookie=self.c.begin('google');state=parse_qs(urlsplit(url).query)['state'][0]
  for key,binding in [('google','wrong'),('yandex',cookie)]:
   with self.assertRaises(ValueError):self.c.callback(key,state,binding,'code')
  self.assertEqual(self.fake.calls,[]);self.c.callback('google',state,cookie,'code')
  with self.assertRaises(ValueError):self.c.callback('google',state,cookie,'code')
  self.assertEqual(len(self.fake.calls),1)
 def test_expired_state_and_denied_consent(self):
  self.c.configure('google','id','secret');url,cookie=self.c.begin('google');state=parse_qs(urlsplit(url).query)['state'][0];self.c.pending[state]['expires']=0
  with self.assertRaises(ValueError):self.c.callback('google',state,cookie,'code')
  url,cookie=self.c.begin('google');state=parse_qs(urlsplit(url).query)['state'][0]
  with self.assertRaises(ValueError):self.c.callback('google',state,cookie,'',True)
  self.assertEqual(self.fake.calls,[])
 def test_refresh_and_report_persistence(self):
  self.connect();data=self.c.secrets.read();data['google']['token']['expires_at']=0;self.c.secrets.write(data);sites=self.c.sites('google');self.assertEqual(self.fake.token_count,2)
  r=self.c.sync('google',self.p['id'],sites[0]['id'],'2026-09-01','2026-09-07');self.assertEqual(r['summary']['position'],7);self.assertEqual(r['summary']['ctr'],.1);self.assertEqual(self.store.imports(self.p['id'])[0]['source'],'google');self.assertIn('sc-domain%3Aexample.com',self.fake.calls[-1][0]);self.assertEqual(self.fake.calls[-1][1]['payload']['dataState'],'final')
 def test_manual_yandex_binding_pkce_single_use(self):
  self.c.configure('yandex','id','secret');url,cookie=self.c.begin('yandex',manual=True);q=parse_qs(urlsplit(url).query);state=q['state'][0]
  self.assertEqual(q['redirect_uri'],['https://oauth.yandex.ru/verification_code'])
  for binding,manual in [('wrong',True),(cookie,False)]:
   with self.assertRaises(ValueError):self.c.callback('yandex',state,binding,'code',manual=manual)
  self.assertEqual(self.fake.calls,[])
  self.c.callback('yandex',state,cookie,'code',manual=True)
  form=self.fake.calls[-1][1]['form'];self.assertEqual(form['redirect_uri'],q['redirect_uri'][0]);self.assertTrue(form['code_verifier'])
  with self.assertRaises(ValueError):self.c.callback('yandex',state,cookie,'code',manual=True)
  with self.assertRaises(ValueError):self.c.begin('google',manual=True)
 def test_manual_yandex_expiry(self):
  self.c.configure('yandex','id','secret');url,cookie=self.c.begin('yandex',manual=True);state=parse_qs(urlsplit(url).query)['state'][0];self.c.pending[state]['expires']=0
  with self.assertRaises(ValueError):self.c.callback('yandex',state,cookie,'code',manual=True)
  self.assertEqual(self.fake.calls,[])
 def test_yandex_actual_dates_missing_not_zero(self):
  self.connect('yandex');sites=self.c.sites('yandex');r=self.c.sync('yandex',self.p['id'],sites[0]['id'],'2026-09-01','2026-09-07');self.assertEqual(r['start'],'2026-09-02');self.assertEqual(r['requested_start'],'2026-09-01');self.assertIsNone(r['summary']['clicks']);self.assertIsNone(r['summary']['ctr']);self.assertEqual(r['summary']['impressions'],50)
  self.assertEqual(parse_qs(urlsplit(self.fake.calls[-1][0]).query)['query_indicator'],['TOTAL_SHOWS','TOTAL_CLICKS','AVG_SHOW_POSITION'])
 def test_error_does_not_persist_fake_zero_report(self):
  self.connect();self.c.sites('google');self.fake.fail=429
  with self.assertRaises(ProviderError):self.c.sync('google',self.p['id'],'sc-domain:example.com','2026-09-01','2026-09-07')
  self.assertEqual(self.store.imports(self.p['id']),[])
 def test_disconnect_preserves_reports_removes_credentials(self):
  self.connect();self.c.sites('google');self.c.sync('google',self.p['id'],'sc-domain:example.com','2026-09-01','2026-09-07');self.c.disconnect('google');self.assertEqual(self.c.secrets.read(),{});self.assertEqual(len(self.store.imports(self.p['id'])),1)
 def test_secret_storage_and_backup_separation(self):
  self.connect();raw=self.c.secrets.path.read_bytes()
  if os.name=='nt':self.assertNotIn(b'fixture-secret',raw)
  else:self.assertEqual(self.c.secrets.path.stat().st_mode&0o777,0o600)
  backup=self.store.backup(Path(self.temp.name)/'backups');self.assertNotIn(b'fixture-secret',backup.read_bytes());self.assertNotIn(b'fixture-access',backup.read_bytes())
 def test_scope_selection_and_dates_rejected_before_network(self):
  self.connect();self.c.sites('google');count=len(self.fake.calls)
  for site,start,end in [('https://evil.example/','2026-09-01','2026-09-07'),('sc-domain:example.com','bad','2026-09-07'),('sc-domain:example.com','2026-01-01','2026-09-07')]:
   with self.assertRaises(ValueError):self.c.sync('google',self.p['id'],site,start,end)
  self.assertEqual(len(self.fake.calls),count)
 def test_api_endpoint_allowlist(self):
  for u in ['http://www.googleapis.com/','https://evil.example/','https://www.googleapis.com@evil.example/','https://www.googleapis.com:444/']:
   with self.assertRaises(ValueError):request_json(u,token='fixture')
 def test_empty_data_unknown_total(self):
  r=report([],'google','site','a','b','a','b',1000);self.assertEqual(r['summary']['rows'],0);self.assertIsNone(r['summary']['clicks'])
 def test_http_callback_cross_site_exception_is_narrow(self):
  server=make_server(0,Path(self.temp.name)/'http');server.connections.transport=self.fake;thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
  def get(path):return json.load(urlopen(base+path))
  token=get('/api/session')['token']
  def post(path,data,auth=token):
   return urlopen(Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-SEO-Token':auth}))
  try:
   with self.assertRaises(HTTPError):post('/api/connections/configure',{'provider':'google','client_id':'id','client_secret':'secret'},'bad')
   post('/api/connections/configure',{'provider':'google','client_id':'id','client_secret':'secret'}).close()
   with post('/api/connections/start',{'provider':'google'}) as r:
    cookie=r.headers['Set-Cookie'];u=json.load(r)['url']
   self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie);q=parse_qs(urlsplit(u).query);self.assertEqual(q['redirect_uri'],[base+'/api/oauth/google/callback'])
   callback='/api/oauth/google/callback?state='+q['state'][0]+'&code=fixture-code'
   try:build_opener(NoRedirect()).open(Request(base+callback,headers={'Cookie':cookie.split(';')[0],'Sec-Fetch-Site':'cross-site'}))
   except HTTPError as e:self.assertEqual(e.code,303);self.assertIn('result=connected',e.headers['Location']);self.assertNotIn('code=',e.headers['Location'])
   self.assertTrue(get('/api/connections')[0]['connected'])
   with self.assertRaises(HTTPError):urlopen(Request(base+'/api/connections',headers={'Sec-Fetch-Site':'cross-site'}))
   navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
   with urlopen(Request(base+'/?connection=google&result=connected',headers=navigation)) as r:self.assertEqual(r.status,200)
   for path in ['/api/session','/api/connections']:
    with self.assertRaises(HTTPError):urlopen(Request(base+path,headers=navigation))
   with self.assertRaises(HTTPError):urlopen(Request(base+'/',headers={**navigation,'Sec-Fetch-Dest':'iframe'}))
   post('/api/connections/configure',{'provider':'yandex','client_id':'id','client_secret':'secret'}).close()
   with post('/api/connections/yandex/code/start',{}) as r:
    manual_cookie=r.headers['Set-Cookie'].split(';')[0];manual=json.load(r)
   data={'state':manual['state'],'code':'fixture-code'}
   with self.assertRaises(HTTPError):post('/api/connections/yandex/code/complete',data)
   headers={'Content-Type':'application/json','X-SEO-Token':token,'Cookie':manual_cookie}
   with urlopen(Request(base+'/api/connections/yandex/code/complete',data=json.dumps(data).encode(),headers=headers)) as r:
    self.assertIn('Max-Age=0',r.headers['Set-Cookie'])
   self.assertTrue(get('/api/connections')[1]['connected'])
  finally:server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
