"""Task-scoped browser proxy. Resolve and pin public addresses on every connection."""
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .network import Network

class ProxyHandler(BaseHTTPRequestHandler):
    timeout = 15
    def log_message(self, *args): pass

    def connect_public(self, host, port):
        if port not in (80, 443):
            raise ValueError('Only ports 80 and 443 are allowed')
        address = Network().addresses(host, port)[0]
        return socket.create_connection((address, port), timeout=15)

    def relay(self, remote):
        with remote:
            for _ in range(20000):
                ready, _, _ = select.select([remote, self.connection], [], [], 20)
                if not ready: break
                for source in ready:
                    data = source.recv(65536)
                    if not data: return
                    (self.connection if source is remote else remote).sendall(data)

    def do_CONNECT(self):
        try:
            parsed = urlsplit('https://' + self.path)
            remote = self.connect_public(parsed.hostname, parsed.port or 443)
            self.send_response(200)
            self.end_headers()
            self.relay(remote)
        except (OSError, ValueError):
            self.close_connection = True

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            if parsed.scheme != 'http' or parsed.username or parsed.password:
                raise ValueError('Invalid proxy URL')
            remote = self.connect_public(parsed.hostname, parsed.port or 80)
            path = parsed.path or '/'
            if parsed.query: path += '?' + parsed.query
            headers = ''.join(f'{k}: {v}\r\n' for k,v in self.headers.items() if k.lower() not in {'connection','proxy-connection','proxy-authorization','host'})
            remote.sendall(f'{self.command} {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nConnection: close\r\n{headers}\r\n'.encode('latin-1'))
            self.relay(remote)
        except (OSError, ValueError):
            self.send_error(403, 'Public destinations only')

class SafeProxy:
    def __enter__(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ProxyHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_port
    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
