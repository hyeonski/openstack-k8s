#!/usr/bin/env python3
"""Large API responses and durable, idempotent upload chunks for S2."""
import argparse
import concurrent.futures
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.request

CHUNK = 1024 * 1024

def payload(index):
    return hashlib.sha256(str(index).encode()).digest() * (CHUNK // 32)


def request(url, data=None, timeout=45):
    with urllib.request.urlopen(urllib.request.Request(url, data=data,
                                method='PUT' if data is not None else 'GET'), timeout=timeout) as response:
        return response.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/bulk':
            self.reply(b'a' * (256 * 1024))
        elif self.path == '/healthz':
            self.reply(b'ok')
        elif self.path == '/progress' and hasattr(self.server, 'root'):
            with sqlite3.connect(self.server.root / 'progress.db') as db:
                rows = db.execute('select id, size, sha from chunks order by id').fetchall()
            next_index = 0
            for row in rows:
                if row[0] != next_index:
                    break
                next_index += 1
            self.reply(json.dumps({'next': next_index, 'chunks': len(rows),
                                   'bytes': sum(r[1] for r in rows),
                                   'manifest_sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest()}).encode())
        else:
            self.reply(b'not found', 404)

    def do_PUT(self):
        try:
            index = int(self.path.removeprefix('/chunk/'))
            if not self.path.startswith('/chunk/') or not 0 <= index < 4096 or int(self.headers['Content-Length']) != CHUNK:
                raise ValueError('bad chunk')
            body = self.rfile.read(CHUNK)
            digest = hashlib.sha256(body).hexdigest()
            if digest != hashlib.sha256(payload(index)).hexdigest():
                raise ValueError('checksum mismatch')
            root = self.server.root
            # A chunk is acknowledged only after its bytes and manifest are durable.
            target = root / f'{index:06d}.chunk'
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError('conflicting chunk')
            else:
                temporary = root / f'{index:06d}.{os.getpid()}.{time.time_ns()}.tmp'
                with temporary.open('wb') as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                fd = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            with sqlite3.connect(root / 'progress.db', timeout=30) as db:
                db.execute('pragma synchronous=FULL')
                db.execute('insert or ignore into chunks values (?, ?, ?)', (index, CHUNK, digest))
            self.reply(json.dumps({'index': index, 'sha256': digest}).encode())
        except (ValueError, KeyError):
            self.reply(b'invalid chunk', 400)


def upload(url, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            index = json.loads(request(url + '/progress'))['next']
            if index >= 4096:
                return
            result = json.loads(request(url + '/chunk/' + str(index), payload(index)))
            print(json.dumps({'time': time.time(), 'index': index, 'bytes': CHUNK,
                              'sha256': result['sha256']}), flush=True)
        except Exception as exc:
            print(json.dumps({'time': time.time(), 'error': type(exc).__name__}), flush=True)
            time.sleep(1)


def probe(url, seconds, rate):
    started = time.monotonic()
    def one(index):
        stamp, begin = time.time(), time.monotonic()
        result = {'time': stamp, 'index': index}
        try:
            body = request(url + '/bulk', timeout=5)
            result.update(ok=body == b'a' * (256 * 1024), bytes=len(body))
        except Exception as exc:
            result.update(ok=False, bytes=0, error=type(exc).__name__)
        result['latency_ms'] = (time.monotonic() - begin) * 1000
        print(json.dumps(result), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for index in range(int(seconds * rate)):
            time.sleep(max(0, started + index / rate - time.monotonic()))
            pool.submit(one, index)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=('api', 'sink', 'upload', 'probe'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--rate', type=float, default=2)
    args = parser.parse_args()
    if args.role == 'upload':
        upload(args.url, args.seconds)
    elif args.role == 'probe':
        probe(args.url, args.seconds, args.rate)
    else:
        server = ThreadingHTTPServer(('0.0.0.0', 8080 if args.role == 'api' else 8090), Handler)
        if args.role == 'sink':
            args.root.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(args.root / 'progress.db') as db:
                db.execute('create table if not exists chunks(id integer primary key, size integer, sha text)')
            server.root = args.root
        server.serve_forever()


if __name__ == '__main__':
    main()
