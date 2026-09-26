"""Deterministic, CPU-bound HTTP workload for the S1 experiment."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlsplit


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/healthz':
            body = b'ok\n'
            content_type = 'text/plain'
        elif parsed.path == '/work':
            try:
                raw = parse_qs(parsed.query).get('rounds', ['100000'])
                if len(raw) != 1:
                    raise ValueError('rounds must occur once')
                rounds = int(raw[0])
                if not 10000 <= rounds <= 1000000:
                    raise ValueError('rounds outside 10000..1000000')
            except ValueError:
                self.send_error(400, 'invalid rounds')
                return
            digest = hashlib.pbkdf2_hmac('sha256', b's1-fixed-input', b's1-fixed-salt', rounds)
            body = (json.dumps({'rounds': rounds, 'digest': digest.hex()}) + '\n').encode()
            content_type = 'application/json'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
