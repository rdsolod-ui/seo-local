import json
import sqlite3
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), created TEXT,
                updated TEXT, status TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS imports (
                id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), created TEXT, payload TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def projects(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM projects ORDER BY created,id")]

    def project(self, key):
        with self.db() as db:
            r = db.execute("SELECT * FROM projects WHERE id=?", (key,)).fetchone()
        if not r:
            raise ValueError("Проект не найден")
        return dict(r)

    def add_project(self, name, url):
        name = str(name).strip()
        if not 1 <= len(name) <= 120:
            raise ValueError("Название должно содержать от 1 до 120 символов")
        key = uuid.uuid4().hex
        try:
            with self.db() as db:
                db.execute("INSERT INTO projects VALUES (?,?,?,?)", (key, name, url, now()))
        except sqlite3.IntegrityError:
            raise ValueError("Этот адрес уже есть в проектах") from None
        return self.project(key)

    def save_run(self, run):
        run["updated"] = now()
        with self.db() as db:
            db.execute("""INSERT INTO runs VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                updated=excluded.updated,status=excluded.status,payload=excluded.payload""",
                (run["id"], run["project_id"], run["created"], run["updated"], run["status"], json.dumps(run, ensure_ascii=False)))

    def run(self, key):
        with self.db() as db:
            r = db.execute("SELECT payload FROM runs WHERE id=?", (key,)).fetchone()
        if not r:
            raise ValueError("Проверка не найдена")
        return json.loads(r[0])

    def runs(self, project_id):
        self.project(project_id)
        with self.db() as db:
            rows = db.execute("SELECT payload FROM runs WHERE project_id=? ORDER BY created DESC,rowid DESC", (project_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def recover(self):
        with self.db() as db:
            rows = db.execute("SELECT payload FROM runs WHERE status='running'").fetchall()
        for row in rows:
            run = json.loads(row[0])
            run["status"] = "paused"
            run["message"] = "Сервер был остановлен. Обход можно продолжить."
            self.save_run(run)

    def add_import(self, project_id, payload):
        self.project(project_id)
        key = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO imports VALUES (?,?,?,?)", (key, project_id, now(), json.dumps(payload, ensure_ascii=False)))
        return key

    def imports(self, project_id):
        self.project(project_id)
        with self.db() as db:
            rows = db.execute("SELECT id,created,payload FROM imports WHERE project_id=? ORDER BY created DESC,rowid DESC", (project_id,)).fetchall()
        return [{"id": r[0], "created": r[1], **json.loads(r[2])} for r in rows]

    def backup(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ("seo-local-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6] + ".sqlite3")
        with self.db() as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        return target
