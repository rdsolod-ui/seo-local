import argparse
import json
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .crawler import Engine
from .network import normalize_url, Network
from .reports import export_csv, export_html, parse_search_console
from .storage import Store
from .schema import validate as validate_schema
from .lighthouse import Lighthouse

ROOT = Path(__file__).resolve().parent.parent


def make_server(port, data_dir, allow_loopback=False, public_origin=None):
    store = Store(Path(data_dir) / "seo.sqlite3")
    engine = Engine(store, allow_loopback)
    token = secrets.token_urlsafe(32)
    lighthouse = Lighthouse(data_dir)

    class Handler(BaseHTTPRequestHandler):
        server_version = "SEOLocal/0.2"
        timeout = 20

        def log_message(self, fmt, *args):
            pass

        def send(self, value, code=200, content_type="application/json; charset=utf-8", filename=None):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str):
                value = value.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(value)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(value)

        def safe_request(self, write=False):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host", "")
            if host not in allowed:
                self.send({"error": "Недопустимый Host"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in allowed} | ({public_origin} if public_origin else set()):
                self.send({"error": "Запрос с другого сайта запрещён"}, 403)
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send({"error": "Межсайтовый запрос запрещён"}, 403)
                return False
            if write and not secrets.compare_digest(self.headers.get("X-SEO-Token", ""), token):
                self.send({"error": "Обновите страницу приложения: сессия устарела"}, 403)
                return False
            return True

        def do_GET(self):
            if not self.safe_request():
                return
            path = urlsplit(self.path).path
            query = parse_qs(urlsplit(self.path).query)
            try:
                if path == "/api/health":
                    self.send({"app": "SEO Local", "version": "0.2.0", "paid_services": False})
                elif path == "/api/session":
                    self.send({"token": token, "hosted": bool(public_origin), "lighthouse": lighthouse.capability()})
                elif path == "/api/lighthouse":
                    result = lighthouse.read(query.get('id', [''])[0])
                    result.pop('report', None)
                    self.send(result)
                elif path == "/api/lighthouse/export":
                    result = lighthouse.read(query.get('id', [''])[0])
                    self.send(result.get('report', result), filename='lighthouse.json')
                elif path == "/api/projects":
                    self.send(store.projects())
                elif path == "/api/runs":
                    runs = store.runs(query.get("project", [""])[0])
                    self.send([{k: r[k] for k in ("id", "created", "status", "message")} | {"checked": len(r["pages"])} for r in runs])
                elif path == "/api/run":
                    self.send(engine.result(query.get("id", [""])[0]))
                elif path == "/api/imports":
                    self.send(store.imports(query.get("project", [""])[0]))
                elif path == "/api/export":
                    run = engine.result(query.get("id", [""])[0])
                    fmt = query.get("format", ["html"])[0]
                    if fmt == "csv":
                        self.send(export_csv(run), content_type="text/csv; charset=utf-8", filename=f"seo-{run['id'][:8]}.csv")
                    elif fmt == "json":
                        self.send(run, filename=f"seo-{run['id'][:8]}.json")
                    else:
                        self.send(export_html(run, store.project(run["project_id"])), content_type="text/html; charset=utf-8", filename=f"seo-{run['id'][:8]}.html")
                elif path in ("/", "/app.js", "/style.css"):
                    file = ROOT / "web" / ("index.html" if path == "/" else path[1:])
                    self.send(file.read_bytes(), content_type=(mimetypes.guess_type(file)[0] or "text/plain") + "; charset=utf-8")
                else:
                    self.send({"error": "Не найдено"}, 404)
            except (ValueError, KeyError) as exc:
                self.send({"error": str(exc)}, 400)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            if not self.safe_request(write=True):
                return
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Нужен Content-Type application/json")
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 6_000_000:
                    raise ValueError("Размер запроса должен быть от 1 байта до 6 МБ")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Нужен JSON-объект")
                path = urlsplit(self.path).path
                if path == '/api/schema':
                    self.send(validate_schema(data['text']))
                elif path == '/api/lighthouse/start':
                    self.send({'id': lighthouse.start(data['url'], data.get('mode', 'mobile'))}, 201)
                elif path == '/api/lighthouse/import':
                    self.send({'id': lighthouse.import_report(data['report'])}, 201)
                elif path == "/api/projects":
                    url = normalize_url(data["url"])
                    parts = urlsplit(url)
                    Network(allow_loopback).addresses(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
                    self.send(store.add_project(data["name"], url), 201)
                elif path == "/api/start":
                    self.send({"id": engine.start(data["project"], data.get("limit", 50), data.get("delay", 0.7))}, 201)
                elif path == "/api/pause":
                    self.send(engine.pause(data["id"]))
                elif path == "/api/resume":
                    self.send({"id": engine.resume(data["id"])})
                elif path == "/api/import":
                    parsed = parse_search_console(data["csv"], data["start"], data["end"])
                    self.send({"id": store.add_import(data["project"], parsed), "summary": parsed["summary"]}, 201)
                elif path == "/api/backup":
                    self.send({"path": str(store.backup(Path(data_dir) / "backups"))})
                elif path == "/api/shutdown":
                    if public_origin:
                        raise ValueError('Остановка серверной версии доступна только администратору VPS')
                    for key in list(engine.jobs):
                        engine.pause(key)
                    self.send({"message": "Приложение останавливается"})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.send({"error": "Не найдено"}, 404)
            except (ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
                self.send({"error": str(exc)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.store = store
    server.engine = engine
    return server


def main():
    parser = argparse.ArgumentParser(description="Бесплатный локальный SEO-аудит")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument('--public-origin', help='HTTPS origin behind an authenticated reverse proxy; upstream Host remains loopback')
    parser.add_argument("--allow-loopback-fixture", action="store_true", help="Только для локальных тестов, не для обычного использования")
    args = parser.parse_args()
    server = make_server(args.port, args.data_dir, args.allow_loopback_fixture, args.public_origin)
    server.store.recover()
    print(f"SEO Local: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for _, event in server.engine.jobs.values():
            event.set()
        for thread, _ in server.engine.jobs.values():
            thread.join(timeout=20)
        server.server_close()


if __name__ == "__main__":
    main()
