"""Evidence-bound relationship checks. Unvisited targets are never called healthy."""
from collections import Counter

def relationship_findings(run):
    result = []
    pages = run['pages']
    by_url = {p['url']: p for p in pages}
    def add(page, code, title, evidence, severity='warning', action='Проверьте указанные адреса и согласуйте настройки страницы.'):
        result.append({'url': page['url'], 'code': code, 'title': title, 'evidence': evidence, 'severity': severity, 'action': action})
    def target(source, url, kind):
        p = by_url.get(url)
        if not p or p.get('error') or p.get('blocked') or p.get('truncated'):
            add(source, kind+'_unchecked', 'Целевой адрес не проверен', url, 'info', 'Добавьте адрес в охват следующей проверки. Внешние origin автоматически не обходятся.')
            return None
        if p.get('redirects'):
            add(source, kind+'_redirect', 'Целевой адрес перенаправляет', url+' → '+p.get('final_url', ''), action='Укажите конечный согласованный адрес без цепочки редиректов.')
        if p['status'] >= 400:
            add(source, kind+'_http_error', 'Целевой адрес возвращает HTTP-ошибку', f"{url}: HTTP {p['status']}", 'error')
        elif not p.get('html'):
            add(source, kind+'_not_html', 'HTML целевого адреса не проверен', url, 'info')
        elif p.get('noindex'):
            add(source, kind+'_noindex', 'Целевой адрес содержит noindex', url)
        return p
    for page in pages:
        if not page.get('html'): continue
        for url in dict.fromkeys(page.get('canonical', [])):
            destination = target(page, url, 'canonical_target')
            if destination and destination.get('html') and len(destination.get('canonical', [])) == 1:
                next_url = destination['canonical'][0]
                if next_url not in (url, destination.get('final_url')):
                    add(page, 'canonical_chain', 'Canonical указывает на другую неканоническую страницу', f'{url} → {next_url}')
            seen, cursor = {page['url']}, url
            for _ in range(len(pages)+1):
                if cursor == page['url'] and url != page['url']:
                    add(page, 'canonical_cycle', 'Цикл canonical', ' → '.join([page['url'], url, '…', cursor]))
                    break
                if cursor in seen: break
                seen.add(cursor)
                options = by_url.get(cursor, {}).get('canonical', [])
                if len(options) != 1: break
                cursor = options[0]
        alternates = page.get('hreflang', [])
        if alternates:
            if not any(a['url'] in (page['url'], page.get('final_url')) for a in alternates):
                add(page, 'hreflang_self', 'В наборе hreflang нет ссылки на эту страницу', page['url'])
            for language in {a['lang'] for a in alternates}:
                urls = {a['url'] for a in alternates if a['lang'] == language}
                if len(urls) > 1:
                    add(page, 'hreflang_conflict', 'Один hreflang ведёт на разные адреса', language+': '+' | '.join(sorted(urls)))
            for alternate in alternates:
                url = alternate['url']
                p = target(page, url, 'hreflang_target')
                if not p or not p.get('html') or url == page['url']: continue
                if not any(a['url'] in (page['url'], page.get('final_url')) for a in p.get('hreflang', [])):
                    add(page, 'hreflang_return', 'Нет обратной ссылки hreflang', url+' не ссылается на '+page['url'])
                if p.get('canonical') and url not in p['canonical'] and p.get('final_url') not in p['canonical']:
                    add(page, 'hreflang_canonical', 'Языковая версия указывает canonical на другой адрес', url+' → '+' | '.join(p['canonical']))
    counts = Counter(run.get('sitemap_urls', []))
    site = {'url': run.get('url', '')}
    unchecked = []
    for url, count in counts.items():
        if count > 1:
            add(site, 'sitemap_duplicate', 'URL повторяется в прочитанных Sitemap', f'{url}: {count} вхождений', 'info')
        p = by_url.get(url)
        if p and p.get('blocked'):
            add(site, 'sitemap_robots', 'Адрес Sitemap закрыт robots.txt', url)
            continue
        if not p or p.get('error') or p.get('truncated'):
            unchecked.append(url); continue
        if p['status'] >= 400:
            add(site, 'sitemap_http_error', 'Адрес Sitemap возвращает HTTP-ошибку', f"{url}: {p['status']}", 'error')
        elif p.get('redirects'):
            add(site, 'sitemap_redirect', 'Адрес Sitemap перенаправляет', url+' → '+p.get('final_url',''))
        if p.get('noindex'):
            add(site, 'sitemap_noindex', 'Адрес Sitemap содержит noindex', url)
        if p.get('canonical') and url not in p['canonical']:
            add(site, 'sitemap_noncanonical', 'В Sitemap включён неканонический адрес', url+' → '+' | '.join(p['canonical']))
    if unchecked:
        add(site, 'sitemap_unchecked', 'Часть адресов Sitemap не проверена', f'{len(unchecked)} адресов; '+ ' | '.join(unchecked[:12]), 'info', 'Увеличьте охват. Отсутствие замечаний вне проверенной выборки не доказывает исправность.')
    return result
