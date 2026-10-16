"""Direct, read-only search data adapters. No third-party SEO service or billing."""
import base64
import hashlib
import json
import math
import re
import secrets
import threading
import time
from datetime import date
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
from .secrets_store import SecretStore

PROVIDERS = {
 'google': {'name':'Google Search Console', 'auth':'https://accounts.google.com/o/oauth2/v2/auth', 'token':'https://oauth2.googleapis.com/token', 'scope':'https://www.googleapis.com/auth/webmasters.readonly'},
 'yandex': {'name':'Яндекс Вебмастер', 'auth':'https://oauth.yandex.ru/authorize', 'token':'https://oauth.yandex.ru/token', 'scope':'webmaster:hostinfo'},
}
GAPI = 'https://www.googleapis.com/webmasters/v3'
YAPI = 'https://api.webmaster.yandex.net/v4'

class ProviderError(ValueError):
    def __init__(self, status=0):
        self.status = status
        super().__init__({400:'Провайдер отклонил запрос. Проверьте настройки OAuth, период и права; при необходимости подключите аккаунт заново.',401:'Доступ истёк или отозван. Подключите аккаунт заново.',403:'Нет разрешения. Проверьте доступ к сайту, права OAuth и включение API.',404:'Сайт или отчёт недоступен. Проверьте подтверждение прав и наличие данных.',429:'Квота API временно исчерпана. Повторите позже; платные запросы не используются.'}.get(status,'Сервис не ответил корректно. Повторите позже; предыдущие отчёты сохранены.'))

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def request_json(url, *, token=None, provider=None, form=None, payload=None):
    # Never follow redirects carrying credentials; only fixed provider endpoints.
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in {'www.googleapis.com','oauth2.googleapis.com','oauth.yandex.ru','api.webmaster.yandex.net'} or p.port not in (None,443) or p.username or p.password:
        raise ValueError('Недопустимый адрес API')
    headers={'Accept':'application/json'};data=None
    if token: headers['Authorization']=('OAuth ' if provider=='yandex' else 'Bearer ')+token
    if form is not None:
        data=urlencode(form).encode();headers['Content-Type']='application/x-www-form-urlencoded'
    elif payload is not None:
        data=json.dumps(payload).encode();headers['Content-Type']='application/json'
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(Request(url,data=data,headers=headers),timeout=8) as response:
            raw=response.read(4_000_001)
            if len(raw)>4_000_000: raise ProviderError()
            result=json.loads(raw)
            if not isinstance(result,dict): raise ProviderError()
            return result
    except HTTPError as exc:
        # Do not expose provider bodies, authorization codes, secrets or token URLs.
        status=exc.code
        exc.close()
        raise ProviderError(status) from None
    except (URLError, OSError, json.JSONDecodeError, UnicodeError):
        raise ProviderError() from None


def number(value):
    if value is None: return None
    try: value=float(value)
    except (ValueError,TypeError): return None
    return value if math.isfinite(value) and value>=0 else None


def report(rows, provider, site, start, end, requested_start, requested_end, limit):
    def total(key):
        values=[r[key] for r in rows]
        return sum(values) if values and all(v is not None for v in values) else None
    clicks,impressions=total('clicks'),total('impressions')
    position=None
    if impressions and all(r['position'] is not None for r in rows):
        position=sum(r['position']*r['impressions'] for r in rows)/impressions
    return {'source':provider,'site':site,'start':start,'end':end,'requested_start':requested_start,'requested_end':requested_end,'rows':rows,
      'summary':{'rows':len(rows),'clicks':clicks,'impressions':impressions,'ctr':clicks/impressions if clicks is not None and impressions else None,'position':position},
      'limit':limit,'limit_reached':len(rows)>=limit,
      'note':('Google: первые строки поисковых запросов, web, окончательные данные; даты в часовом поясе PT. Анонимизированные запросы и часть строк API могут отсутствовать. ' if provider=='google' else 'Яндекс: выборка популярных запросов, все устройства, сортировка по показам. Доступный период может отличаться от запрошенного. ')+f'До {limit} строк за загрузку. Это итоги выборки, не всего сайта. Пропуски не заменяются нулём. Средняя позиция взвешена по показам.'}


class Connections:
    def __init__(self, directory, store, base_url, transport=request_json):
        self.secrets=SecretStore(directory);self.store=store;self.base=base_url.rstrip('/')+'/'
        p=urlsplit(self.base)
        if p.query or p.fragment or p.username or p.password or (p.scheme!='https' and not (p.scheme=='http' and p.hostname in ('127.0.0.1','localhost'))):
            raise ValueError('OAuth требует HTTPS или локальный loopback URL')
        self.transport=transport;self.lock=threading.RLock();self.pending={};self.sites_cache={}

    def provider(self, key):
        if key not in PROVIDERS: raise ValueError('Неизвестное подключение')
        return PROVIDERS[key]

    def redirect(self,key):
        self.provider(key);return self.base+'api/oauth/'+key+'/callback'

    def status(self):
        with self.lock:
            data=self.secrets.read()
            return [{'provider':key,'name':p['name'],'configured':bool(data.get(key,{}).get('client_id')),'connected':bool(data.get(key,{}).get('token')),'redirect_uri':self.redirect(key),'scope':p['scope']} for key,p in PROVIDERS.items()]

    def configure(self,key,client_id,client_secret):
        self.provider(key)
        if not all(isinstance(v,str) and 1<=len(v.strip())<=2048 and not re.search(r'[\x00-\x20\x7f]',v.strip()) for v in (client_id,client_secret)):
            raise ValueError('Введите Client ID и Client Secret без пробелов')
        with self.lock:
            data=self.secrets.read();data[key]={'client_id':client_id.strip(),'client_secret':client_secret.strip()};self.secrets.write(data)
            self.pending={s:v for s,v in self.pending.items() if v['provider']!=key};self.sites_cache.pop(key,None)
        return {'message':'Настройки сохранены. Теперь подключите аккаунт.'}

    def begin(self,key):
        p=self.provider(key)
        with self.lock:
            c=self.secrets.read().get(key,{})
            if not c.get('client_id'): raise ValueError('Сначала сохраните настройки OAuth-приложения')
            self.pending={s:v for s,v in self.pending.items() if v['expires']>time.time()}
            if len(self.pending)>=20: raise ValueError('Слишком много попыток входа. Подождите 10 минут.')
            state,cookie,verifier=secrets.token_urlsafe(32),secrets.token_urlsafe(32),secrets.token_urlsafe(48)
            self.pending[state]={'provider':key,'cookie':cookie,'verifier':verifier,'expires':time.time()+600}
            params={'client_id':c['client_id'],'redirect_uri':self.redirect(key),'response_type':'code','scope':p['scope'],'state':state,'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),'code_challenge_method':'S256'}
            params.update({'access_type':'offline','prompt':'consent'} if key=='google' else {'force_confirm':'yes'})
            return p['auth']+'?'+urlencode(params),cookie

    def callback(self,key,state,cookie,code,error=False):
        p=self.provider(key)
        with self.lock:
            pending=self.pending.get(state)
            if not pending or pending['provider']!=key or pending['expires']<time.time() or not secrets.compare_digest(pending['cookie'],cookie or ''):
                raise ValueError('Вход устарел или открыт в другом браузере. Начните подключение заново.')
            self.pending.pop(state)
            if error: raise ValueError('Доступ не предоставлен. Можно повторить подключение.')
            if not isinstance(code,str) or not 1<=len(code)<=4096: raise ValueError('Код авторизации отсутствует')
            data=self.secrets.read();c=data[key]
            form={'grant_type':'authorization_code','code':code,'client_id':c['client_id'],'client_secret':c['client_secret'],'redirect_uri':self.redirect(key),'code_verifier':pending['verifier']}
            result=self.transport(p['token'],form=form)
            # Reauthorization never reuses a different account's old refresh token.
            c['token']=self.token_value(result,{})
            self.secrets.write(data);self.sites_cache.pop(key,None)
        return {'message':'Аккаунт подключён. Загрузите список сайтов.'}

    @staticmethod
    def token_value(result,old):
        if not isinstance(result.get('access_token'),str) or not result['access_token']: raise ProviderError(400)
        expires=number(result.get('expires_in'))
        return {'access_token':result['access_token'],'refresh_token':result.get('refresh_token') or old.get('refresh_token'),'expires_at':time.time()+expires if expires is not None else None}

    def access(self,key,force=False):
        p=self.provider(key);data=self.secrets.read();c=data.get(key,{});token=c.get('token')
        if not token: raise ValueError('Сначала подключите аккаунт')
        if force or (token.get('expires_at') is not None and token['expires_at']<time.time()+60):
            if not token.get('refresh_token'): raise ProviderError(401)
            result=self.transport(p['token'],form={'grant_type':'refresh_token','refresh_token':token['refresh_token'],'client_id':c['client_id'],'client_secret':c['client_secret']})
            token=self.token_value(result,token);c['token']=token;self.secrets.write(data)
        return token['access_token']

    def api(self,key,url,payload=None):
        token=self.access(key)
        try:return self.transport(url,token=token,provider=key,payload=payload)
        except ProviderError as exc:
            if exc.status!=401:raise
            return self.transport(url,token=self.access(key,True),provider=key,payload=payload)

    def sites(self,key):
        self.provider(key)
        with self.lock:
            if key=='google':
                data=self.api(key,GAPI+'/sites')
                sites=[{'id':s['siteUrl'],'label':s['siteUrl'],'permission':s.get('permissionLevel',''),'verified':s.get('permissionLevel')!='siteUnverifiedUser'} for s in data.get('siteEntry',[]) if isinstance(s.get('siteUrl'),str)]
                uid=None
            else:
                uid=str(self.api(key,YAPI+'/user')['user_id'])
                if not uid.isdigit():raise ProviderError()
                data=self.api(key,YAPI+'/user/'+uid+'/hosts')
                sites=[{'id':s['host_id'],'label':s.get('unicode_host_url') or s.get('ascii_host_url') or s['host_id'],'verified':s.get('verified') is True} for s in data.get('hosts',[]) if isinstance(s.get('host_id'),str)]
            self.sites_cache[key]={'sites':sites,'uid':uid,'expires':time.time()+1800}
            return sites

    def disconnect(self,key):
        self.provider(key)
        with self.lock:
            data=self.secrets.read();data.pop(key,None);self.secrets.write(data);self.sites_cache.pop(key,None)
            self.pending={s:v for s,v in self.pending.items() if v['provider']!=key}
        return {'message':'Настройки и токены удалены из SEO Local. Сохранённые отчёты остались. Разрешение приложения можно отозвать в аккаунте провайдера.'}

    def sync(self,key,project,site,start,end):
        self.provider(key);self.store.project(project)
        try:a,b=date.fromisoformat(start),date.fromisoformat(end)
        except (ValueError,TypeError):raise ValueError('Укажите даты YYYY-MM-DD') from None
        if b<a or (b-a).days>92 or b>date.today():raise ValueError('Период: до 93 дней, начало не позже конца, без будущих дат')
        with self.lock:
            cached=self.sites_cache.get(key)
            if not cached or cached['expires']<time.time():raise ValueError('Обновите список сайтов перед загрузкой данных')
            if not any(s['id']==site and s['verified'] for s in cached['sites']):raise ValueError('Выберите доступный подтверждённый сайт из списка')
            if key=='google':
                limit=1000
                data=self.api(key,GAPI+'/sites/'+quote(site,safe='')+'/searchAnalytics/query',{'startDate':start,'endDate':end,'dimensions':['query'],'type':'web','dataState':'final','rowLimit':limit,'startRow':0})
                rows=[{'query':str((r.get('keys') or [''])[0]),'clicks':number(r.get('clicks')),'impressions':number(r.get('impressions')),'position':number(r.get('position'))} for r in data.get('rows',[])[:limit]]
                actual_start,actual_end=start,end
            else:
                limit=500
                query=urlencode({'order_by':'TOTAL_SHOWS','query_indicator':['TOTAL_SHOWS','TOTAL_CLICKS','AVG_SHOW_POSITION'],'device_type_indicator':'ALL','date_from':start,'date_to':end,'offset':0,'limit':limit},doseq=True)
                data=self.api(key,YAPI+'/user/'+cached['uid']+'/hosts/'+quote(site,safe='')+'/search-queries/popular?'+query)
                rows=[]
                for r in data.get('queries',[])[:limit]:
                    i=r.get('indicators',{});rows.append({'query':str(r.get('query_text','')),'clicks':number(i.get('TOTAL_CLICKS')),'impressions':number(i.get('TOTAL_SHOWS')),'position':number(i.get('AVG_SHOW_POSITION'))})
                actual_start,actual_end=data.get('date_from'),data.get('date_to')
                if not actual_start or not actual_end:raise ProviderError()
            result=report(rows,key,site,actual_start,actual_end,start,end,limit)
            result['id']=self.store.add_import(project,result)
            return result
