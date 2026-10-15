import hashlib
import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from urllib.parse import urljoin

from .network import normalize_url, origin
from .schema import validate as validate_schema


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.h1 = []
        self.description = ""
        self.canonicals = []
        self.robots = []
        self.links = []
        self.images_without_alt = []
        self.jsonld = []
        self.base = ""
        self.lang = ""
        self.viewport = ""
        self.text = []
        self.capture = None
        self.hidden = 0
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and not self.base:
            self.base = a.get("href", "")
        if tag == "html":
            self.lang = a.get("lang", "")
        if tag == "title":
            self.capture = self.title
        if tag == "h1":
            self.h1.append([])
            self.capture = self.h1[-1]
        if tag == "script":
            self.scripts += 1
            if a.get("type", "").lower() == "application/ld+json":
                self.jsonld.append([])
                self.capture = self.jsonld[-1]
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "meta":
            name = a.get("name", "").lower()
            content = a.get("content") or ""
            if name == "description":
                self.description = content
            elif name in ("robots", "googlebot"):
                self.robots.append(content)
            elif name == "viewport":
                self.viewport = content
        if tag == "link" and "canonical" in (a.get("rel") or "").lower().split():
            self.canonicals.append(a.get("href") or "")
        if tag == "a" and a.get("href"):
            self.links.append({"href": a["href"], "nofollow": "nofollow" in (a.get("rel") or "").lower().split()})
        if tag == "img" and "alt" not in a:
            self.images_without_alt.append((a.get("src") or "(без src)")[:500])

    def handle_endtag(self, tag):
        if tag in ("title", "h1", "script"):
            self.capture = None
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if self.capture is not None:
            self.capture.append(data)
        if not self.hidden:
            self.text.append(data)


def clean(s):
    return " ".join(s.split())


def analyze(response, site_origin):
    body = response.pop("body", "")
    page = {**response, "title": "", "description": "", "h1": [], "links": [], "issues": [], "html": False}

    def issue(code, severity, title, evidence, action):
        page["issues"].append({"code": code, "severity": severity, "title": title,
                               "url": page["url"], "evidence": str(evidence)[:3000], "action": action})

    if page.get("blocked"):
        issue("robots_blocked", "info", "Обход запрещён robots.txt", page.get("error"), "Проверьте, намеренно ли закрыт этот URL. Блокировка обхода не равна noindex.")
        return page
    if page.get("error"):
        issue("fetch_error", "warning", "Страница не проверена", page["error"], "Проверьте доступность адреса и повторите. Ошибка запроса не доказывает удаление страницы.")
        return page
    if page["status"] >= 400:
        issue("http_error", "error", "HTTP-ошибка", page["status"], "Проверьте ответ сервера и ссылки на этот URL; исправьте адрес или настройте нужный ответ.")
        return page
    if len(page.get("redirects", [])) > 1:
        issue("redirect_chain", "warning", "Цепочка редиректов", json.dumps(page["redirects"], ensure_ascii=False), "Обновите внутренние ссылки до конечного адреса и сократите цепочку.")
    if page.get("truncated"):
        issue("body_limit", "warning", "Документ больше лимита анализа", "Лимит 2 МБ", "Анализ HTML пропущен, чтобы не выдавать выводы по обрезанному документу.")
        return page
    if not 200 <= page["status"] < 300:
        return page
    content_type = page.get("headers", {}).get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return page
    page["html"] = True
    parser = PageParser()
    parser.feed(body)
    page["title"] = clean(" ".join(parser.title))
    page["description"] = clean(parser.description)
    page["h1"] = [clean(" ".join(h)) for h in parser.h1]
    page["canonical"] = []
    page["word_count"] = len(clean(" ".join(parser.text)).split())
    page["content_hash"] = hashlib.sha256(clean(" ".join(parser.text)).encode()).hexdigest()
    page["robots"] = ", ".join(parser.robots + [page.get("headers", {}).get("x-robots-tag", "")]).strip(", ")
    directives = set(re.split(r"[\s,]+", page["robots"].lower()))
    page["noindex"] = bool({"noindex", "none"} & directives)
    if page["noindex"]:
        issue("noindex", "info", "Указан noindex", page["robots"], "Сверьте с назначением страницы: для служебных страниц это может быть правильно.")
    if not page["title"]:
        issue("title_missing", "warning", "Нет title", "Пустой или отсутствующий <title>", "Добавьте уникальный заголовок, описывающий содержание страницы.")
    if not page["description"]:
        issue("description_missing", "warning", "Нет meta description", "Описание отсутствует в исходном HTML", "Добавьте содержательное описание; поисковик может выбрать другой сниппет.")
    if not any(page["h1"]):
        issue("h1_missing", "warning", "Нет содержательного H1", "H1 отсутствует или пуст", "Добавьте понятный основной заголовок; для JS-сайта проверьте отрисованный DOM.")
    if len(page["h1"]) > 1:
        issue("h1_multiple", "info", "Несколько H1 — проверьте структуру", " | ".join(page["h1"]), "Проверьте смысловую иерархию. Само количество H1 не доказывает SEO-ошибку.")
    if not parser.lang:
        issue("lang_missing", "info", "Не указан язык HTML", "Нет html lang", "Укажите язык документа для вспомогательных технологий.")
    if not parser.viewport:
        issue("viewport_missing", "warning", "Нет meta viewport", "Тег отсутствует", "Проверьте мобильную вёрстку и добавьте подходящий viewport.")
    base = urljoin(page["final_url"], parser.base) if parser.base else page["final_url"]
    for c in parser.canonicals:
        try:
            page["canonical"].append(normalize_url(urljoin(base, c)))
        except ValueError:
            issue("canonical_invalid", "warning", "Некорректный canonical", c, "Укажите корректный URL канонической страницы.")
    if len(parser.canonicals) > 1:
        issue("canonical_multiple", "warning", "Несколько canonical", str(page["canonical"]), "Оставьте одну согласованную каноническую ссылку.")
    if not parser.canonicals:
        issue("canonical_missing", "info", "Canonical не указан", "В HTML нет rel=canonical", "Проверьте, есть ли дубли URL; отсутствие тега само по себе не является запретом индексации.")
    if parser.images_without_alt:
        issue("alt_missing", "warning", "У изображений отсутствует alt", " | ".join(parser.images_without_alt[:20]), "Добавьте описание значимым изображениям, декоративным — пустой alt.")
    page['schema'] = []
    for number, block in enumerate(parser.jsonld):
        result = validate_schema(''.join(block))
        page['schema'].append(result)
        for finding in result['issues']:
            code = finding['code'] if finding['code'] == 'jsonld_invalid' else 'schema_' + finding['code']
            issue(code, finding['severity'], 'JSON-LD: ' + finding['code'],
                  f"Блок {number+1}, {finding['path']}: {finding['detail']}",
                  'Проверьте указанное место в разметке. Замечания по словарю не являются полной проверкой JSON-LD или гарантией расширенного результата.')
    if parser.scripts and page["word_count"] < 30:
        issue("js_review", "info", "Мало текста в исходном HTML", f"Слов: {page['word_count']}; script: {parser.scripts}", "Проверьте страницу в браузере: этот обходчик не исполняет JavaScript.")
    seen = set()
    for link in parser.links:
        try:
            href = normalize_url(urljoin(base, link["href"]))
        except ValueError:
            continue
        if href in seen:
            continue
        seen.add(href)
        page["links"].append({"url": href, "internal": origin(href) == site_origin,
                              "follow": not link["nofollow"] and not bool({"nofollow", "none"} & directives)})
    return page


def findings(run):
    pages = run["pages"]
    issues = list(run.get("site_issues", [])) + [i for p in pages for i in p["issues"]]
    by_url = {p["url"]: p for p in pages}
    for field, label in (("title", "title"), ("description", "meta description"), ("content_hash", "текста HTML")):
        groups = defaultdict(list)
        for p in pages:
            if p.get("html") and not p.get("noindex") and not p.get("redirects") and p.get(field):
                groups[p[field]].append(p["url"])
        for value, urls in groups.items():
            if len(urls) > 1:
                for url in urls:
                    issues.append({"code": f"duplicate_{field}", "severity": "warning", "title": f"Совпадение {label}", "url": url,
                                   "evidence": " | ".join(urls)[:3000], "action": "Сравните назначение страниц и канонические адреса; совпадение не всегда требует удаления."})
    for p in pages:
        for link in p.get("links", []):
            target = by_url.get(link["url"])
            if target and target["status"] >= 400:
                issues.append({"code": "broken_internal_link", "severity": "error", "title": "Внутренняя ссылка ведёт на HTTP-ошибку", "url": p["url"],
                               "evidence": f"{link['url']} → HTTP {target['status']}", "action": "Исправьте ссылку на исходной странице либо восстановите целевой URL."})
    unique = {(i["code"], i["url"], i["evidence"]): i for i in issues}
    return sorted(unique.values(), key=lambda i: ({"error": 0, "warning": 1, "info": 2}[i["severity"]], i["code"], i["url"]))


def compare(current, previous):
    """Only successful, mutually observed pages may count as resolved."""
    if not previous:
        return None
    a = {(i["url"], i["code"]): i for i in findings(previous)}
    b = {(i["url"], i["code"]): i for i in findings(current)}
    good_old = {p["url"] for p in previous["pages"] if p.get("html") and not p.get("error")}
    good_new = {p["url"] for p in current["pages"] if p.get("html") and not p.get("error")}
    common = good_old & good_new
    checked_new = {p["url"] for p in current["pages"] if 200 <= p.get("status", 0) < 300 and not p.get("error")}
    old_urls = {p["url"] for p in previous["pages"]}
    def comparable(key):
        if key[0] not in common:
            return False
        if key[1].startswith("duplicate_") or key[1] == "broken_internal_link":
            return old_urls <= checked_new
        return True
    return {"previous_id": previous["id"], "common_pages": len(common),
            "new": [i for k, i in b.items() if k not in a],
            "resolved": [i for k, i in a.items() if k not in b and comparable(k)],
            "not_rechecked": [i for k, i in a.items() if k not in b and not comparable(k)],
            "note": "Новые — впервые обнаруженные, не обязательно впервые возникшие. Исправленные — только на успешно проверенных в обоих запусках HTML-страницах."}
