"""Interactive launcher; reuses an existing server, never installs startup tasks."""
import json
import sys
import threading
import webbrowser
from urllib.request import urlopen
from urllib.error import URLError

from seo_local.server import main

URL = "http://127.0.0.1:8765"
try:
    with urlopen(URL + "/api/health", timeout=2) as response:
        health = json.load(response)
    if health.get("app") != "SEO Local":
        raise SystemExit("Port 8765 belongs to another application.")
except (URLError, OSError):
    # Server binds first. Browser waits for a confirmed identity, not a timer guess.
    def open_when_ready():
        import time
        for _ in range(25):
            try:
                with urlopen(URL + "/api/health", timeout=1) as response:
                    if json.load(response).get("app") == "SEO Local":
                        webbrowser.open(URL)
                        return
            except (URLError, OSError, ValueError):
                time.sleep(.2)
    threading.Thread(target=open_when_ready, daemon=True).start()
    main()
else:
    webbrowser.open(URL)
