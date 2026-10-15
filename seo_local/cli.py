import argparse
import json
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .crawler import Engine
from .network import normalize_url
from .reports import export_csv, export_html, parse_search_console
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description="SEO Local CLI — без платных API")
    p.add_argument("--data-dir", default=str(ROOT / "data"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("projects")
    add = sub.add_parser("add")
    add.add_argument("name"); add.add_argument("url")
    crawl = sub.add_parser("crawl")
    crawl.add_argument("project_id"); crawl.add_argument("--limit", type=int, default=50)
    report = sub.add_parser("report")
    report.add_argument("run_id"); report.add_argument("output"); report.add_argument("--format", choices=["html", "csv", "json"], default="html")
    sub.add_parser("backup")
    restore = sub.add_parser("restore")
    restore.add_argument("backup_file"); restore.add_argument("new_directory", help="Новый каталог; существующая база не перезаписывается")
    args = p.parse_args()
    if args.cmd == "restore":
        target = Path(args.new_directory) / "seo.sqlite3"
        if target.exists():
            p.error("В целевом каталоге уже есть база; выберите новый каталог")
        source = Path(args.backup_file).resolve()
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                p.error("Резервная копия повреждена")
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"projects", "runs", "imports"} <= names:
                p.error("Это не база SEO Local")
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(target)) as dest:
                db.backup(dest)
        print(target)
        return
    store = Store(Path(args.data_dir) / "seo.sqlite3")
    if args.cmd == "projects":
        print(json.dumps(store.projects(), ensure_ascii=False, indent=2))
    elif args.cmd == "add":
        print(json.dumps(store.add_project(args.name, normalize_url(args.url)), ensure_ascii=False))
    elif args.cmd == "crawl":
        # CLI has its own run loop: do not recover or mutate other process jobs.
        engine = Engine(store)
        key = engine.start(args.project_id, args.limit)
        try:
            engine.jobs[key][0].join()
        except KeyboardInterrupt:
            engine.pause(key)
            engine.jobs[key][0].join(timeout=20)
        print(json.dumps(engine.result(key), ensure_ascii=False, indent=2))
    elif args.cmd == "backup":
        print(store.backup(Path(args.data_dir) / "backups"))
    elif args.cmd == "report":
        run = Engine(store).result(args.run_id)
        if args.format == "html":
            content = export_html(run, store.project(run["project_id"]))
        elif args.format == "csv":
            content = export_csv(run)
        else:
            content = json.dumps(run, ensure_ascii=False, indent=2)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="") as f:
            f.write(content)
        print(target.resolve())


if __name__ == "__main__":
    main()
