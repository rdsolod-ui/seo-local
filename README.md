# SEO Local

Self-hosted SEO audits without paid APIs, cloud credits or mandatory AI.
Russian interface. Python 3.10+ and SQLite; optional Node.js/Chrome for Lighthouse.

## Start

```sh
git clone https://github.com/rdsolod-ui/seo-local.git
cd seo-local
python -m seo_local.server
```

Open http://127.0.0.1:8765/. On Windows, `start.cmd` also opens the browser.
There are no Python package dependencies. Data is stored in `data/`, excluded
from version control. Use `--data-dir` for a different location.

## Lighthouse (optional, free)

Install Node.js 22.19 or newer and Chrome, then run `npm ci --ignore-scripts`.
Use the Lighthouse panel to audit a public HTTP/HTTPS URL in mobile or desktop
mode. Set `CHROME_PATH` if Chrome is not detected automatically.
One audit runs at a time with a 185-second limit. It uses a fresh temporary
browser profile and a public-IP-only proxy, without user cookies. Nonstandard
ports and private addresses are blocked. No API key is needed. Browser loading
can contact third-party public resources used by the audited page.

Scores are laboratory measurements, affected by machine load and network.
LCP, CLS, FCP, TBT and Speed Index are not field Core Web Vitals; TBT is not INP.
The full JSON can be downloaded or imported into another instance. Audits are
stored under `data/lighthouse`; monitor disk usage and back up that directory
separately from SQLite. Interrupted audits are marked failed on restart.

## Features

- Projects, SQLite, crawl history, pause/resume and scope limits (up to 500 URLs).
- robots.txt, sitemap discovery, metadata, headings, links, duplicate content.
- Canonical targets, chains/cycles; hreflang return links and conflicts; Sitemap
  duplicate, redirect, HTTP-error, noindex and noncanonical URL checks. Unvisited
  targets remain explicitly unchecked. Source HTML only, same-origin crawl.
- Bounded retries for 429/502/503/504 and transport failures, Retry-After support,
  retained queue and resumable pause when the site requires a longer wait.
- Bold local Cyrillic fonts, GSAP entrance/section motion, live reduced-motion
  support. All interface assets are bundled; no CDN or analytics requests.
- Offline Schema.org 30.1: 939 types, 1538 properties; nested JSON-LD and @graph,
  multiple types, inherited property domains, object ranges, duplicate keys,
  syntax and structural checks, precise JSON paths.
- Standalone JSON-LD editor and integration with each HTML crawl.
- HTML/CSV/JSON exports, CSV Search Console import, SQLite backup/restore.
- Optional stdio MCP adapter: `python -m seo_local.mcp_bridge` while server runs.

The crawler reads source HTML, not JavaScript-rendered DOM. Schema checks are
not a full JSON-LD processor: external contexts are never fetched and complex
contexts are explicitly marked unchecked. Domain/range findings are advisory;
Schema.org has no universal required properties. Rich results and indexing
are not guaranteed. No ranking/backlink database or paid provider is included.

## Google Search Console and Yandex Webmaster

Open **Подключения поисковых кабинетов** in the app. Enter your own OAuth Web
application Client ID and Client Secret, then authorize in the provider's page.
Credentials are never returned to the browser after saving. Use only these scopes:

- Google: `https://www.googleapis.com/auth/webmasters.readonly`; enable Search
  Console API and configure the consent audience/test users in Google Cloud.
- Yandex: `webmaster:hostinfo`; configure a Web services OAuth application.

Copy the exact Redirect URI shown in each card into the corresponding provider's
application settings. The default local URLs use `http://127.0.0.1:8765/` and
`api/oauth/google/callback` or `api/oauth/yandex/callback`. Open the app at the same
host as its callback. For a reverse proxy, set `--public-base-url` to the complete
HTTPS URL including its subdirectory (e.g. `https://example.org/seo-local/`).
With `--public-origin` alone, the backwards-compatible default prefix is `/seo-local/`.
Use separate OAuth clients for separate installations where appropriate.

After authorization: select your project, fetch the site list, explicitly choose
the matching verified property and dates, then load data. Google domain properties
and URL-prefix properties are supported. One request stores up to 1000 Google query
rows or 500 Yandex popular queries. Dates may be adjusted by Yandex; both requested
and actual periods are saved. Google uses final web data and PT date boundaries.
No pagination claim: these are bounded top-query samples, not complete site totals.
Missing metrics stay null. Reports persist in project history and download as JSON.
No background schedule or automatic account writes are performed.

This is still one shared owner workspace, with one account per provider. All users
who know the reverse-proxy password can manage these connections. OAuth uses PKCE,
one-use expiring state and a browser-bound HttpOnly/SameSite=Lax cookie. Provider
requests use fixed HTTPS hosts, reject redirects and have bounded time/size limits.
Refresh tokens are updated server-side. If consent is revoked or a Google Testing
refresh token expires (typically seven days), reconnect in the app.

Secrets live in `data/connections-private/`, separate from SQLite/report backups.
Windows uses current-user DPAPI; Linux uses directory 0700/file 0600 permissions,
not application-level encryption. Administrators/root can access server secrets.
Keep this directory out of source archives. Disconnect removes local settings and
tokens and retains reports; revoke the provider-side grant separately in your account.

**Reverse proxy:** protect callbacks with the same authentication as the rest of
the app. Disable access logging and request-bearing error logging for the two exact
callback paths to avoid logging authorization codes. Do not log POST bodies. Keep
all other app/API routes protected. No credentials are needed for unit tests:
provider responses are fixtures, clearly distinct from real account authorization.

Sources: [Google pricing](https://developers.google.com/webmaster-tools/pricing),
[Google OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[Search Analytics](https://developers.google.com/webmaster-tools/v1/searchanalytics/query),
[Yandex OAuth](https://yandex.ru/dev/id/doc/ru/codes/code-url),
[Yandex popular queries](https://yandex.com/dev/webmaster/doc/ru/reference/host-search-queries-popular).
The app has no paid SEO API or credit system; provider quotas and your hosting costs remain.

## Self-hosting

Run as an unprivileged user, bound to loopback, behind an authenticated HTTPS
reverse proxy. **This is a single-owner workspace, not a multi-tenant service.**
All authenticated users share project data. Never expose the upstream publicly.

```sh
python -m seo_local.server --port 8765 --data-dir /var/lib/seo-local \
  --public-origin https://your-domain.example
```

Proxy `/seo-local/` to `http://127.0.0.1:8765/` (strip the prefix), set upstream
Host to `127.0.0.1:8765`, and enforce authentication on **all** routes. Static
assets and API links support a subdirectory. The configured public origin is
accepted for CSRF checks; a per-process token remains required for writes.
The shutdown API is disabled when `--public-origin` is set.

Keep Chrome sandbox enabled. Do not run Chrome as root or pass `--no-sandbox`.
On Linux, install Chrome's system libraries and configure the official Chrome
sandbox according to the distribution. Limit worker resources using systemd.
Compute, internet and hosting may have costs; the application does not bill
for API calls or require a subscription.

## Test

```sh
python -m unittest discover -s tests -v
npm audit --omit=dev
```

Tests cover real fixture HTTP requests, crawl controls, private-IP/redirect
protection, Host/Origin/CSRF, reports, backups, schema and Lighthouse imports.
Real Lighthouse runs require Chrome and internet; lab scores are not asserted
as constants in unit tests.

Application code: MIT. Derived Schema.org vocabulary: CC BY-SA 3.0.
See [THIRD_PARTY.md](THIRD_PARTY.md).
