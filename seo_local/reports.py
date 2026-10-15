import csv
import html
import io
import math
from datetime import date

LABELS = {"error": "Ошибка", "warning": "Внимание", "info": "Проверить контекст"}


def safe_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def export_csv(run):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["severity", "code", "url", "title", "evidence", "action"])
    for i in run["issues"]:
        writer.writerow([safe_cell(i[k]) for k in ("severity", "code", "url", "title", "evidence", "action")])
    return "\ufeff" + buffer.getvalue()


def export_html(run, project):
    e = lambda v: html.escape(str(v), quote=True)
    rows = "".join(f"<tr><td>{e(LABELS[i['severity']])}</td><td><strong>{e(i['title'])}</strong><p>{e(i['url'])}</p></td><td>{e(i['evidence'])}</td><td>{e(i['action'])}</td></tr>" for i in run["issues"])
    summary = run["summary"]
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>SEO Local — {e(project['name'])}</title><style>body{{font:16px/1.55 system-ui,sans-serif;margin:32px auto;max-width:1200px;padding:0 20px;color:#18352d;background:#fff}}h1{{font-size:32px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border:1px solid #d7dfda;text-align:left;vertical-align:top;overflow-wrap:anywhere}}td p{{font-size:14px}}@media print{{body{{margin:0;font-size:11px}}}}@media(max-width:700px){{table,tbody,tr,td{{display:block}}thead{{display:none}}}}</style>
    <h1>SEO-проверка: {e(project['name'])}</h1><p>{e(run['url'])} · {e(run['created'])} · {e(run['status'])}</p>
    <p>{e(run['message'])}</p><p>Проверено адресов: {summary['checked']}; HTML: {summary['html']}; недоступно: {summary['unavailable']}; в очереди: {summary['pending']}.</p>
    <p>Ошибки: {summary['error']} · предупреждения: {summary['warning']} · контекстные замечания: {summary['info']}</p>
    <p>Проверяется исходный HTML без JavaScript, только выбранный origin. Максимум 5 XML sitemap, 5000 обнаруженных URL, 2 МБ на документ. Внешние ссылки, изображения и JS-отрисовка не проверяются. Это не подтверждение индексации или рейтинга сайта.</p>
    <table><thead><tr><th>Приоритет</th><th>Наблюдение / URL</th><th>Доказательство</th><th>Действие</th></tr></thead><tbody>{rows}</tbody></table>
    <p>Создано локально. Нет платных API, внешних шрифтов и скриптов.</p></html>"""


ALIASES = {
    "clicks": {"clicks", "клики"}, "impressions": {"impressions", "показы"},
    "position": {"position", "average position", "позиция", "средняя позиция"},
    "query": {"query", "top queries", "запрос", "запросы", "популярные запросы", "самые популярные запросы"},
    "page": {"page", "top pages", "страница", "страницы", "популярные страницы", "самые популярные страницы"},
    "date": {"date", "дата"},
}


def parse_search_console(text, start, end):
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except (ValueError, TypeError):
        raise ValueError("Укажите начало и конец периода в формате ГГГГ-ММ-ДД") from None
    if start_date > end_date:
        raise ValueError("Начало периода позже окончания")
    text = text.lstrip("\ufeff")
    if len(text) > 5_000_000:
        raise ValueError("CSV должен быть меньше 5 МБ")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        raise ValueError("Не удалось определить разделитель CSV") from None
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fields = {name: key for key in (reader.fieldnames or []) for name, aliases in ALIASES.items() if key.strip().lower() in aliases}
    if not {"clicks", "impressions", "position"} <= fields.keys() or not ({"query", "page", "date"} & fields.keys()):
        raise ValueError("Нужны столбцы Query/Page/Date, Clicks, Impressions, Position (или русские названия из Search Console)")
    dimension = next(k for k in ("query", "page", "date") if k in fields)
    rows = []

    def number(value):
        value = (value or "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
        n = float(value)
        if not math.isfinite(n) or n < 0:
            raise ValueError()
        return n

    try:
        for index, row in enumerate(reader):
            if index >= 25000:
                raise ValueError("Максимум 25 000 строк в одном импорте")
            clicks, impressions, position = [number(row[fields[k]]) for k in ("clicks", "impressions", "position")]
            if not clicks.is_integer() or not impressions.is_integer() or clicks > impressions or (impressions > 0 and position < 1):
                raise ValueError()
            label = str(row[fields[dimension]] or "").strip()
            if not label:
                raise ValueError()
            if dimension == "date" and not start_date <= date.fromisoformat(label) <= end_date:
                raise ValueError("Дата в CSV выходит за выбранный период")
            rows.append({"label": label[:2000], "clicks": int(clicks), "impressions": int(impressions), "position": position})
    except (ValueError, KeyError, TypeError, csv.Error) as exc:
        raise ValueError(f"Некорректные данные CSV: строка {len(rows) + 2}. {str(exc) or 'Проверьте числа и обязательные поля.'}") from None
    if not rows:
        raise ValueError("CSV не содержит строк данных")
    clicks, impressions = sum(r["clicks"] for r in rows), sum(r["impressions"] for r in rows)
    return {"source": "Search Console CSV (пользовательский импорт)", "start": start, "end": end, "dimension": dimension,
            "rows": rows, "summary": {"rows": len(rows), "clicks": clicks, "impressions": impressions,
            "ctr": clicks / impressions if impressions else None,
            "position": sum(r["position"] * r["impressions"] for r in rows) / impressions if impressions else None},
            "note": "Показатели только по строкам выгрузки, не полный итог сайта. Средняя позиция взвешена по показам, не является текущей позицией в выдаче. Период указан пользователем."}
