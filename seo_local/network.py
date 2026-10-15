"""Bounded HTTP fetches. No cookies/proxies. Resolve and pin public IPs per request."""
import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

AGENT = "SEOLocal/0.1"
MAX_BYTES = 2_000_000


def normalize_url(value):
    value = str(value).strip()
    if not value or len(value) > 4096 or re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("Нужен корректный HTTP/HTTPS-адрес без пробелов")
    if "://" not in value:
        value = "https://" + value
    p = urlsplit(value)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("Разрешены только HTTP/HTTPS-адреса без логина и пароля")
    host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    port = p.port
    if ":" in host:
        host = "[" + host + "]"
    netloc = host + (":" + str(port) if port and port != (443 if p.scheme == "https" else 80) else "")
    return urlunsplit((p.scheme, netloc, quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~"), quote(p.query, safe="%=&?/:;+,$@!()*'-._~"), ""))


def origin(url):
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


class Network:
    def __init__(self, allow_loopback=False, timeout=12, delay=0.7):
        self.allow_loopback = allow_loopback
        self.timeout = timeout
        self.delay = delay
        self.last = 0.0
        self.guard = None

    def addresses(self, host, port):
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(a[4][0] for a in answers))
        if not ips:
            raise ValueError("Не удалось разрешить адрес сайта")
        for raw in ips:
            ip = ipaddress.ip_address(raw)
            if not ip.is_global and not (self.allow_loopback and ip.is_loopback):
                raise ValueError("Локальные, служебные и частные IP запрещены для обхода")
        return ips

    def fetch(self, url, allowed_origin, max_redirects=5):
        current = normalize_url(url)
        chain = []
        start = time.monotonic()
        for _ in range(max_redirects + 1):
            if origin(current) != allowed_origin:
                return {"url": url, "final_url": current, "status": chain[-1]["status"] if chain else 0,
                        "redirects": chain, "error": "Редирект за пределы выбранного origin: добавьте конечный адрес отдельным проектом", "body": "", "headers": {}}
            if self.guard and not self.guard(current):
                return {"url": url, "final_url": current, "status": 0, "redirects": chain, "blocked": True,
                        "error": "Переход запрещён robots.txt", "body": "", "headers": {}}
            p = urlsplit(current)
            port = p.port or (443 if p.scheme == "https" else 80)
            conn = None
            try:
                ips = self.addresses(p.hostname, port)
                time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
                self.last = time.monotonic()
                conn = http.client.HTTPConnection(p.hostname, port, timeout=self.timeout)
                sock = socket.create_connection((ips[0], port), timeout=self.timeout)
                if p.scheme == "https":
                    try:
                        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
                    except Exception:
                        sock.close()
                        raise
                conn.sock = sock
                path = urlunsplit(("", "", p.path, p.query, ""))
                conn.request("GET", path, headers={"User-Agent": AGENT, "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*;q=0.1", "Accept-Encoding": "identity"})
                response = conn.getresponse()
                headers = {k.lower(): v for k, v in response.getheaders()}
                if response.status in (301, 302, 303, 307, 308) and headers.get("location"):
                    next_url = normalize_url(urljoin(current, headers["location"]))
                    chain.append({"url": current, "status": response.status, "to": next_url})
                    if next_url in [c["url"] for c in chain]:
                        raise ValueError("Циклический редирект")
                    current = next_url
                    continue
                raw = response.read(MAX_BYTES + 1)
                too_large = len(raw) > MAX_BYTES
                content_type = headers.get("content-type", "").lower()
                match = re.search(r"charset=[\"']?([^;\s\"']+)", content_type)
                encoding = match.group(1) if match else "utf-8"
                try:
                    body = raw[:MAX_BYTES].decode(encoding, errors="replace")
                except LookupError:
                    body = raw[:MAX_BYTES].decode("utf-8", errors="replace")
                return {"url": url, "final_url": current, "status": response.status, "headers": headers,
                        "redirects": chain, "body": body, "bytes": len(raw), "truncated": too_large,
                        "elapsed_ms": round((time.monotonic() - start) * 1000), "error": ""}
            except (OSError, ValueError, http.client.HTTPException) as exc:
                return {"url": url, "final_url": current, "status": 0, "headers": {}, "redirects": chain, "body": "", "error": str(exc)}
            finally:
                if conn:
                    conn.close()
        return {"url": url, "final_url": current, "status": 0, "headers": {}, "redirects": chain, "body": "", "error": "Более 5 редиректов"}


class Robots:
    """RFC-style longest match, wildcard and end anchor, case-insensitive UA groups."""
    def __init__(self, text):
        groups = []
        agents, rules, delay = [], [], 0
        self.sitemaps = []
        seen_directive = False
        for line in text.splitlines() + ["User-agent: __end__"]:
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = [s.strip() for s in line.split(":", 1)]
            key = key.lower()
            if key == "sitemap":
                self.sitemaps.append(value)
            elif key == "user-agent":
                if seen_directive:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, seen_directive = [], [], 0, False
                agents.append(value.lower())
            elif agents:
                seen_directive = True
                if key in ("allow", "disallow") and value:
                    rules.append((key == "allow", value))
                elif key == "crawl-delay":
                    try:
                        delay = max(delay, float(value))
                    except ValueError:
                        pass
        specific = [g for g in groups if any(a != "*" and a in AGENT.lower() for a in g[0])]
        chosen = specific or [g for g in groups if "*" in g[0]]
        self.rules = [r for g in chosen for r in g[1]]
        self.delay = max([g[2] for g in chosen] + [0])

    def allowed(self, url):
        p = urlsplit(url)
        path = p.path + ("?" + p.query if p.query else "")
        matches = []
        for allow, rule in self.rules:
            ending = rule.endswith("$")
            raw = rule[:-1] if ending else rule
            pattern = "^" + ".*".join(re.escape(part) for part in raw.split("*")) + ("$" if ending else "")
            if re.search(pattern, path):
                matches.append((len(raw.replace("*", "")), allow))
        return max(matches)[1] if matches else True
