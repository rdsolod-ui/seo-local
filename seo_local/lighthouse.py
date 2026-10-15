"""Single bounded Lighthouse worker; no API key, cloud service or credits."""
import json
import os
import shutil
import signal
import subprocess
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from .network import Network, normalize_url
from .safe_proxy import SafeProxy

ROOT = Path(__file__).resolve().parent.parent

def summarize(report):
    if not isinstance(report, dict) or not isinstance(report.get('categories'), dict) or not isinstance(report.get('audits'), dict):
        raise ValueError('Нужен JSON-отчёт Lighthouse с categories и audits')
    if not isinstance(report.get('configSettings', {}), dict) or any(not isinstance(value, dict) for value in report['categories'].values()):
        raise ValueError('Некорректная структура отчёта Lighthouse')
    if report.get('runtimeError'):
        raise ValueError(str(report['runtimeError'])[:500])
    url = normalize_url(report.get('finalDisplayedUrl') or report.get('finalUrl') or report.get('requestedUrl', ''))
    scores = {}
    for key in ('performance','accessibility','best-practices','seo'):
        score = report['categories'].get(key, {}).get('score')
        if score is not None and (isinstance(score, bool) or not isinstance(score,(int,float)) or not 0 <= score <= 1):
            raise ValueError('Некорректная оценка Lighthouse')
        scores[key] = round(score*100) if score is not None else None
    metrics = {k: {'value':report['audits'][k].get('numericValue'), 'display':str(report['audits'][k].get('displayValue',''))[:200]} for k in ('first-contentful-paint','largest-contentful-paint','total-blocking-time','cumulative-layout-shift','speed-index') if isinstance(report['audits'].get(k),dict)}
    return {'url':url,'version':str(report.get('lighthouseVersion',''))[:40], 'date':str(report.get('fetchTime',''))[:80], 'mode':str(report.get('configSettings',{}).get('formFactor','unknown'))[:30], 'scores':scores,'metrics':metrics,'note':'Лабораторная проверка на этом компьютере/сервере. Результат зависит от нагрузки и сети; это не полевые Core Web Vitals и не INP.'}

class Lighthouse:
    def __init__(self, data_dir):
        self.directory = Path(data_dir) / 'lighthouse'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        for file in self.directory.glob('*.json'):
            if len(file.stem) == 32:
                try:
                    saved=json.loads(file.read_text(encoding='utf-8'))
                    if saved.get('status') == 'running':
                        self.save(file.stem, {'id': file.stem, 'status': 'failed', 'error': 'Проверка прервана перезапуском приложения; запустите повторно.'})
                except (ValueError, OSError):
                    pass
    def capability(self):
        ready = bool(shutil.which('node') and (ROOT/'node_modules/lighthouse/package.json').exists())
        return {'available':ready,'message':'Локальный Lighthouse; Chrome необходим для запуска.' if ready else 'Установите Node.js 22.19+ и Chrome, затем выполните npm ci в каталоге приложения. Импорт JSON доступен без установки.'}
    def read(self, identifier):
        if not isinstance(identifier,str) or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier): raise ValueError('Некорректный ID')
        file=self.directory/(identifier+'.json')
        if not file.exists(): raise ValueError('Проверка не найдена')
        return json.loads(file.read_text(encoding='utf-8'))
    def save(self, identifier, payload):
        target=self.directory/(identifier+'.json')
        temp=target.with_suffix('.tmp')
        temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        temp.replace(target)
    def import_report(self, report):
        summary=summarize(report)
        identifier=uuid.uuid4().hex
        self.save(identifier,{'id':identifier,'status':'completed','source':'import','summary':summary,'report':report})
        return identifier
    def start(self,url,mode):
        if mode not in ('mobile','desktop'): raise ValueError('Выберите mobile или desktop')
        url=normalize_url(url)
        p=urlsplit(url)
        if (p.port or (443 if p.scheme=='https' else 80)) not in (80,443): raise ValueError('Только порты 80 и 443')
        Network().addresses(p.hostname,p.port or 443)
        if not self.capability()['available']: raise ValueError(self.capability()['message'])
        if not self.lock.acquire(blocking=False): raise ValueError('Дождитесь текущей проверки Lighthouse')
        identifier=uuid.uuid4().hex
        try:
            self.save(identifier,{'id':identifier,'status':'running','url':url,'mode':mode})
            threading.Thread(target=self.worker,args=(identifier,url,mode),daemon=True).start()
        except Exception:
            self.lock.release()
            raise
        return identifier
    def worker(self,identifier,url,mode):
        output=self.directory/(identifier+'.raw.json')
        try:
            with SafeProxy() as proxy:
                proc=subprocess.Popen([shutil.which('node'),str(ROOT/'scripts/lighthouse.mjs'),url,mode,str(proxy),str(output)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
                try:
                    _, stderr=proc.communicate(timeout=185)
                except subprocess.TimeoutExpired:
                    if os.name=='nt':
                        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        os.killpg(proc.pid,signal.SIGKILL)
                    proc.communicate(timeout=10)
                    raise ValueError('Lighthouse превысил лимит 185 секунд')
                if proc.returncode: raise ValueError('Lighthouse: '+stderr[-1200:])
            report=json.loads(output.read_text(encoding='utf-8'))
            self.save(identifier,{'id':identifier,'status':'completed','source':'local','summary':summarize(report),'report':report})
        except Exception as exc:
            self.save(identifier,{'id':identifier,'status':'failed','error':str(exc)[:1500]})
        finally:
            output.unlink(missing_ok=True)
            self.lock.release()
