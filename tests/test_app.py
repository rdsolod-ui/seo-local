import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from seo_local.audit import analyze, compare, findings
from seo_local.crawler import Engine
from seo_local.network import Network, Robots, normalize_url
from seo_local.reports import export_csv, export_html, parse_search_console
from seo_local.server import make_server
from seo_local.storage import Store


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        title = "<title>Тест</title><meta name='description' content='Тестовое описание'><meta name='viewport' content='width=device-width'>"
        html = f"<html lang='ru'><head>{title}</head><body><h1>Проверка</h1><a href='/missing'>Ошибка</a><a href='/duplicate'>Дубль</a><a href='/blocked'>Закрыто</a><a href='/redirect'>Редирект</a><img src='/x.png'><script type='application/ld+json'>{{bad}}</script></body></html>"
        paths = {"/": html, "/duplicate": f"<html lang='ru'><head>{title}</head><body><h1>Другая</h1></body></html>", "/robots.txt": "User-agent: *\nDisallow: /blocked\nSitemap: " + base + "/sitemap.xml", "/sitemap.xml": f"<urlset><url><loc>{base}/</loc></url><url><loc>{base}/duplicate</loc></url></urlset>"}
        if self.path == "/redirect":
            self.send_response(302); self.send_header("Location", "/duplicate"); self.end_headers(); return
        if self.path == "/external":
            self.send_response(302); self.send_header("Location", "http://192.168.1.1/"); self.end_headers(); return
        if self.path == "/blocked":
            self.server.blocked_hits += 1
        content = paths.get(self.path, "Not found").encode()
        self.send_response(200 if self.path in paths else 404)
        self.send_header("Content-Type", "text/plain; charset=utf-8" if self.path == "/robots.txt" else "application/xml" if self.path == "/sitemap.xml" else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        cls.site.blocked_hits = 0
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.site.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown(); cls.site.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "seo.sqlite3")
        self.project = self.store.add_project("Тест", self.base + "/")

    def tearDown(self):
        self.temp.cleanup()

    def test_url_normalization_and_secrets(self):
        self.assertEqual(normalize_url("https://EXAMPLE.com:443/a#x"), "https://example.com/a")
        self.assertEqual(normalize_url("https://example.com/Тест"), "https://example.com/%D0%A2%D0%B5%D1%81%D1%82")
        for u in ("file:///a", "https://u:p@example.com/", "https://x/a\nB", "https://x\\a"):
            with self.assertRaises(ValueError): normalize_url(u)

    def test_private_addresses_blocked(self):
        for host in ("127.0.0.1", "169.254.169.254", "10.0.0.1", "::1"):
            with self.assertRaises(ValueError): Network().addresses(host, 80)

    def test_robots_longest_match_and_agents(self):
        r = Robots("User-agent: *\nDisallow: /a\nAllow: /a/yes\nDisallow: /*?secret=$\n")
        self.assertFalse(r.allowed("https://example.com/a/no"))
        self.assertTrue(r.allowed("https://example.com/a/yes"))
        self.assertFalse(r.allowed("https://example.com/x?secret="))
        r = Robots("User-agent: *\nDisallow: /\nUser-agent: SEOLocal\nAllow: /\nCrawl-delay: 2")
        self.assertTrue(r.allowed("https://example.com/")); self.assertEqual(r.delay, 2)

    def test_external_redirect_never_fetched(self):
        r = Network(True, delay=0).fetch(self.base + "/external", self.base)
        self.assertIn("origin", r["error"]); self.assertEqual(len(r["redirects"]), 1)

    def test_crawl_real_http_evidence(self):
        engine = Engine(self.store, True)
        key = engine.start(self.project["id"], 15, .5)
        engine.jobs[key][0].join(20)
        run = engine.result(key)
        self.assertEqual(run["status"], "completed", run["message"])
        codes = {i["code"] for i in run["issues"]}
        self.assertTrue({"broken_internal_link", "duplicate_title", "alt_missing", "jsonld_invalid", "robots_blocked"} <= codes, codes)
        self.assertEqual(self.site.blocked_hits, 0)
        redirect = next(p for p in run["pages"] if p["url"].endswith("/redirect"))
        self.assertEqual(redirect["final_url"], self.base + "/duplicate")

    def test_pause_resume_persistent(self):
        engine = Engine(self.store, True)
        key = engine.start(self.project["id"], 15, .5)
        engine.pause(key); engine.jobs[key][0].join(15)
        self.assertEqual(self.store.run(key)["status"], "paused")
        engine.resume(key); engine.jobs[key][0].join(20)
        run = self.store.run(key)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(run["pages"]), len({p["url"] for p in run["pages"]}))

    def test_limit_not_complete(self):
        engine = Engine(self.store, True)
        key = engine.start(self.project["id"], 1, .5)
        engine.jobs[key][0].join(10)
        run = engine.result(key)
        self.assertEqual(run["status"], "limited"); self.assertGreater(run["summary"]["pending"], 0)

    def test_recovery_and_backup_restore(self):
        r = {"id": "a", "project_id": self.project["id"], "created": "2026-10-15", "status": "running", "pending": ["a"]}
        self.store.save_run(r); self.store.recover()
        self.assertEqual(self.store.run("a")["status"], "paused")
        path = self.store.backup(Path(self.temp.name) / "backups")
        target = Path(self.temp.name) / "restored"
        result = subprocess.run([sys.executable, "-m", "seo_local.cli", "restore", str(path), str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Store(target / "seo.sqlite3").projects(), self.store.projects())

    def test_no_false_fixes_outside_coverage(self):
        page = {"url": "https://example.com/", "html": True, "issues": [{"code": "title_missing", "url": "https://example.com/", "severity": "warning", "evidence": "missing"}]}
        old = {"id": "old", "pages": [page]}
        diff = compare({"pages": []}, old)
        self.assertEqual(len(diff["resolved"]), 0); self.assertEqual(len(diff["not_rechecked"]), 1)

    def test_csv_locale_weighted_and_validation(self):
        data = parse_search_console('Запросы;Клики;Показы;Позиция\n"парк";2;10;"2,5"\n"колесо";3;30;"4,5"', "2026-10-01", "2026-10-14")
        self.assertEqual(data["summary"]["position"], 4)
        self.assertEqual(data["summary"]["ctr"], .125)
        for number in ("NaN", "-1", "100"):
            with self.assertRaises(ValueError): parse_search_console(f"Query,Clicks,Impressions,Position\na,{number},10,2", "2026-10-01", "2026-10-14")

    def test_duplicate_not_fixed_when_sample_shrinks(self):
        p = {"url": "https://example.com/a", "status": 200, "html": True, "title": "Same", "issues": []}
        q = {**p, "url": "https://example.com/b"}
        old = {"id": "old", "pages": [p,q]}
        diff = compare({"pages": [p]}, old)
        self.assertEqual(diff["resolved"], [])
        self.assertEqual(len(diff["not_rechecked"]), 2)

    def test_exports_escape_and_formula(self):
        run = {"id": "r", "url": "https://example.com/", "created": "2026-10-15", "status": "completed", "message": "<script>x</script>", "summary": {"checked": 1, "html": 1, "unavailable": 0, "pending": 0, "error": 0, "warning": 1, "info": 0}, "issues": [{"code": "x", "severity": "warning", "title": "=1+1", "url": "https://example.com/", "evidence": "<script>x</script>", "action": "fix"}]}
        self.assertNotIn("<script>", export_html(run, {"name": "<script>"}))
        self.assertIn("'=1+1", export_csv(run))

    def test_html_semantics(self):
        result = analyze({"url": "https://example.com/", "final_url": "https://example.com/", "status": 200, "headers": {"content-type": "text/html"}, "body": "<title>Тест</title><h1>Один</h1><h1>Два</h1><img alt=''><meta name='robots' content='none'><a href='/a'>A</a>"}, "https://example.com")
        codes = {i["code"] for i in result["issues"]}
        self.assertTrue(result["noindex"]); self.assertNotIn("alt_missing", codes)
        self.assertFalse(result["links"][0]["follow"])
        self.assertEqual(next(i for i in result["issues"] if i["code"] == "h1_multiple")["severity"], "info")

    def test_http_local_access_controls(self):
        app = make_server(0, self.temp.name, True)
        threading.Thread(target=app.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{app.server_port}"
        try:
            with urlopen(base + "/api/session") as r: token = json.load(r)["token"]
            for headers in ({"Host": "evil.test"}, {"Origin": "https://evil.test"}):
                with self.assertRaises(HTTPError) as exc: urlopen(Request(base + "/api/projects", headers=headers))
                self.assertEqual(exc.exception.code, 403)
                exc.exception.close()
            with self.assertRaises(HTTPError) as exc:
                urlopen(Request(base + "/api/backup", data=b'{}', headers={"Content-Type": "application/json"}))
            self.assertEqual(exc.exception.code, 403)
            exc.exception.close()
            with urlopen(Request(base + "/api/backup", data=b'{}', headers={"Content-Type": "application/json", "X-SEO-Token": token})) as r:
                self.assertTrue(Path(json.load(r)["path"]).exists())
        finally:
            app.shutdown(); app.server_close()

    def test_mcp_protocol(self):
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "seo_local_start", "arguments": {"project_id": "bad"}}}]
        r = subprocess.run([sys.executable, "-m", "seo_local.mcp_bridge"], input="\n".join(json.dumps(m) for m in messages) + "\n", capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        responses = [json.loads(line) for line in r.stdout.splitlines()]
        self.assertEqual(len(responses), 3); self.assertEqual(len(responses[1]["result"]["tools"]), 4)
        self.assertTrue(responses[2]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
