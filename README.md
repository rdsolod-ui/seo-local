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
