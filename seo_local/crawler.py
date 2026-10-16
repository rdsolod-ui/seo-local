import threading
import time
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from .audit import analyze, findings, compare
from .network import Network, Robots, normalize_url, origin
from .storage import now

SKIP = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".css", ".js", ".mp4", ".zip", ".mp3")


class Engine:
    def __init__(self, store, allow_loopback=False):
        self.store = store
        self.allow_loopback = allow_loopback
        self.lock = threading.Lock()
        self.jobs = {}

    def start(self, project_id, limit=50, delay=0.7):
        limit, delay = int(limit), float(delay)
        if not 1 <= limit <= 500 or not 0.5 <= delay <= 10:
            raise ValueError("Лимит: 1–500 адресов, интервал: 0,5–10 секунд")
        p = self.store.project(project_id)
        run = {"id": uuid.uuid4().hex, "project_id": p["id"], "url": p["url"], "created": now(),
               "status": "running", "limit": limit, "delay": delay, "pages": [], "pending": [p["url"]],
               "discovered": [p["url"]], "site_issues": [], "prepared": False, "message": "Подготовка обхода"}
        self._launch(run)
        return run["id"]

    def _launch(self, run):
        with self.lock:
            if any(t.is_alive() for t, _ in self.jobs.values()):
                raise ValueError("Уже идёт проверка. Дождитесь завершения или поставьте её на паузу.")
            event = threading.Event()
            thread = threading.Thread(target=self._work, args=(run, event), daemon=True)
            self.jobs[run["id"]] = (thread, event)
            run["status"] = "running"
            self.store.save_run(run)
            thread.start()

    def pause(self, key):
        self.store.run(key)
        with self.lock:
            job = self.jobs.get(key)
            if job:
                job[1].set()
        return {"message": "Пауза запрошена; текущий HTTP-запрос будет завершён."}

    def resume(self, key):
        run = self.store.run(key)
        if run["status"] != "paused":
            raise ValueError("Продолжить можно только приостановленную проверку")
        if run.get('retry_at', 0) > time.time():
            raise ValueError(f"Сайт просит подождать ещё {int(run['retry_at']-time.time())+1} сек. (Retry-After)")
        self._launch(run)
        return key

    def _work(self, run, stop):
        net = Network(self.allow_loopback, delay=run["delay"])
        net.stop = stop
        site = origin(run["url"])
        started = time.monotonic()

        def add(url):
            try:
                url = normalize_url(url)
            except ValueError:
                return
            if origin(url) == site and url not in run["discovered"] and len(run["discovered"]) < 5000 and not urlsplit(url).path.lower().endswith(SKIP):
                run["discovered"].append(url)
                run["pending"].append(url)

        def site_issue(code, title, evidence):
            run["site_issues"] = [i for i in run["site_issues"] if (i["code"], i['evidence']) != (code, evidence)][-199:]
            run["site_issues"].append({"code": code, "severity": "info", "title": title, "url": site,
                                       "evidence": evidence, "action": "Проверьте вручную. Отсутствие данных не считается успешной проверкой."})

        def deferred(response):
            if response.get('retry_at') or response.get('retry_interrupted'):
                run['status'] = 'paused'
                run['retry_at'] = response.get('retry_at', 0)
                run['message'] = f"Пауза: HTTP {response['status']}, попыток {response.get('attempts', 1)}. Адрес сохранён в очереди; учитывается Retry-After."
                return True
            return False

        try:
            rob = net.fetch(site + "/robots.txt", site)
            if deferred(rob): return
            run["robots_status"] = rob["status"]
            if rob.get("error") or rob["status"] >= 500 or rob["status"] in (401, 403, 429) or rob.get("truncated"):
                raise ValueError("robots.txt недоступен; обход остановлен: " + (rob.get("error") or str(rob["status"])))
            robots = Robots(rob["body"] if rob["status"] == 200 else "")
            if robots.delay > 60:
                raise ValueError("robots.txt требует интервал более 60 секунд. Этот выпуск не запускает такой обход.")
            net.delay = max(net.delay, robots.delay)
            net.guard = robots.allowed
            if not run["prepared"]:
                if rob["status"] != 200:
                    site_issue("robots_absent", "robots.txt не найден", f"HTTP {rob['status']}; это не обязательный SEO-дефект.")
                sitemap_queue = (robots.sitemaps or [site + "/sitemap.xml"])[:5]
                visited_maps = set()
                run["sitemap_urls"] = []
                run['sitemaps'] = []
                while sitemap_queue and len(visited_maps) < 5 and not stop.is_set():
                    raw_sm = sitemap_queue.pop(0)
                    try:
                        sm_url = normalize_url(raw_sm)
                    except ValueError:
                        site_issue('sitemap_url_invalid', 'Некорректный адрес Sitemap', raw_sm)
                        continue
                    if origin(sm_url) != site or sm_url in visited_maps:
                        continue
                    visited_maps.add(sm_url)
                    sm = net.fetch(sm_url, site)
                    if deferred(sm): return
                    run['sitemaps'].append({'url': sm_url, 'status': sm['status'], 'error': sm.get('error', '')})
                    if sm["status"] != 200 or sm.get("error") or sm.get("truncated"):
                        site_issue("sitemap_unavailable", "Sitemap не прочитан полностью", sm_url + ": " + (sm.get("error") or str(sm["status"])))
                        continue
                    try:
                        root = ET.fromstring(sm["body"])
                        locs = [e.text.strip() for child in root for e in child if e.tag.split("}")[-1] == "loc" and e.text]
                        if len(locs) > 5000:
                            site_issue('sitemap_limit', 'Sitemap прочитан частично', sm_url + ': первые 5000 адресов')
                        locs = locs[:5000]
                        if root.tag.split("}")[-1] == "sitemapindex":
                            sitemap_queue.extend(locs[:5])
                        elif root.tag.split("}")[-1] == "urlset":
                            for loc in locs:
                                try:
                                    if not loc.startswith(('https://', 'http://')):
                                        raise ValueError('Absolute URL required')
                                    normalized = normalize_url(loc)
                                    add(normalized)
                                    run["sitemap_urls"].append(normalized)
                                    if origin(normalized) != site:
                                        site_issue('sitemap_external', 'Адрес Sitemap за пределами origin', normalized)
                                except ValueError:
                                    site_issue('sitemap_invalid_loc', 'Некорректный loc в Sitemap', loc)
                        else:
                            site_issue("sitemap_format", "Ответ не является XML Sitemap", sm_url)
                    except ET.ParseError as exc:
                        site_issue("sitemap_parse", "Ошибка XML Sitemap", str(exc))
                if sitemap_queue:
                    site_issue('sitemap_maps_limit', 'Проверены не все Sitemap', 'Лимит: 5 файлов; оставшиеся карты не проверены.')
                run["prepared"] = not stop.is_set()
                self.store.save_run(run)
            while run["pending"] and len(run["pages"]) < run["limit"]:
                if stop.is_set() or time.monotonic() - started > 1800:
                    run["status"] = "paused"
                    run["message"] = "Приостановлено. Очередь сохранена."
                    break
                url = run["pending"][0]
                response = net.fetch(url, site)
                if deferred(response): break
                page = analyze(response, site)
                run["pages"].append(page)
                run["pending"].pop(0)
                for target in page.get('canonical', []) + [a['url'] for a in page.get('hreflang', [])]:
                    add(target)
                for link in page.get("links", []):
                    if link["internal"] and link["follow"]:
                        add(link["url"])
                run["message"] = f"Проверено {len(run['pages'])} из максимум {run['limit']} адресов"
                self.store.save_run(run)
                if page["status"] == 429:
                    run["status"] = "paused"
                    run["message"] = "Сайт вернул 429. Обход приостановлен, повторите позже."
                    break
            if run["status"] == "running":
                run["status"] = "limited" if run["pending"] else "completed"
                run["message"] = "Достигнут лимит адресов; охват частичный." if run["pending"] else "Очередь обхода обработана. Проверьте ошибки загрузки и ограничения охвата."
            run["finished"] = now() if run["status"] in ("completed", "limited") else None
        except Exception as exc:
            run["status"] = "failed"
            run["message"] = str(exc)
        finally:
            self.store.save_run(run)

    def result(self, key):
        run = self.store.run(key)
        history = self.store.runs(run["project_id"])
        index = next(i for i, r in enumerate(history) if r["id"] == key)
        older = [r for r in history[index + 1:] if r["status"] in ("completed", "limited")]
        issues = findings(run)
        return {**run, "issues": issues, "comparison": compare(run, older[0]) if older else None,
                "summary": {"checked": len(run["pages"]), "pending": len(run["pending"]),
                            "html": sum(bool(p.get("html")) for p in run["pages"]),
                            "unavailable": sum(bool(p.get("error")) for p in run["pages"]),
                            **{s: sum(i["severity"] == s for i in issues) for s in ("error", "warning", "info")}}}
