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
import datetime as dt
import uuid
import threading
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


def probe(url, seconds, rate, stop_file=None, progress_file=None):
    started, wall = time.monotonic(), time.time()
    clock = 's2:' + uuid.uuid4().hex
    def stamp(t):
        return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()
    def one(index):
        at, begin = time.time(), time.monotonic()
        result = {'time': at, 'index': index, 'request_id': str(index),
                  'scheduled_utc': stamp(wall + index / rate), 'started_utc': stamp(at),
                  'started_monotonic': begin, 'clock_id': clock, 'deadline_seconds': 5,
                  'generator_rejection': False}
        try:
            body = request(url + '/bulk', timeout=5)
            result.update(ok=body == b'a' * (256 * 1024), bytes=len(body))
        except Exception as exc:
            result.update(ok=False, bytes=0, error=type(exc).__name__)
        result.update(latency_ms=(time.monotonic() - begin) * 1000,
                      completed_utc=stamp(time.time()), completed_monotonic=time.monotonic(),
                      correct=result['ok'])
        return result
    stop = threading.Event()
    def monitor_progress():
        with Path(progress_file).open('a') as stream:
            while True:
                row={'utc':stamp(time.time()),'monotonic':time.monotonic(),'clock_id':clock}
                try:
                    row['progress']=json.loads(request('http://198.18.0.2:8090/progress',timeout=5))
                except Exception as exc:
                    row['error']=type(exc).__name__
                stream.write(json.dumps(row)+'\n');stream.flush();os.fsync(stream.fileno())
                if stop.wait(1):break
    monitor=None
    if progress_file:
        monitor=threading.Thread(target=monitor_progress,daemon=True);monitor.start()
    try:
        pending = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            for index in range(int(seconds * rate)):
                time.sleep(max(0, started + index / rate - time.monotonic()))
                if stop_file and Path(stop_file).exists():
                    break
                for task in [t for t in pending if t.done()]:
                    print(json.dumps(task.result()), flush=True)
                    pending.remove(task)
                if len(pending) >= 16:
                    print(json.dumps(dict(time=time.time(),index=index,request_id=str(index),
                        scheduled_utc=stamp(wall+index/rate),started_utc=None,completed_utc=None,
                        ok=False,correct=False,bytes=0,latency_ms=0,error='inflight_limit',
                        generator_rejection=True,clock_id=clock,deadline_seconds=5)),flush=True)
                else:
                    pending.add(pool.submit(one,index))
            for task in concurrent.futures.as_completed(pending):
                print(json.dumps(task.result()),flush=True)
    finally:
        stop.set()
        if monitor:
            monitor.join(timeout=7)
            if monitor.is_alive():raise RuntimeError('uploader progress observer did not finish')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=('api', 'sink', 'upload', 'probe'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--progress-file', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--rate', type=float, default=2)
    args = parser.parse_args()
    if args.role == 'upload':
        upload(args.url, args.seconds)
    elif args.role == 'probe':
        probe(args.url, args.seconds, args.rate, args.stop_file, args.progress_file)
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
