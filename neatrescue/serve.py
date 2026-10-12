"""Read-only local presentation of recorded NeatRescue runs. No model calls on GET."""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]

def run_data(requested=None):
    root = ROOT / 'runs'
    dirs = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime) if root.exists() else []
    if requested:
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', requested):
            raise ValueError('Invalid run identifier')
        dirs = [p for p in dirs if p.name == requested]
    if not dirs:
        return {'state': 'NOT_RUN', 'events': [], 'runs': []}
    selected = dirs[-1]
    data = {'run_id': selected.name, 'state': 'RUNNING', 'runs': [p.name for p in dirs], 'events': []}
    for name in ('manifest', 'baseline', 'incoming_shortcut', 'report', 'telemetry_status', 'misleading_patch_challenge', 'source_before'):
        p = selected / (name + '.json')
        if p.exists():
            try: data[name] = json.loads(p.read_text())
            except json.JSONDecodeError: pass
    p = selected / 'events.jsonl'
    if p.exists():
        for line in p.read_text().splitlines():
            try: data['events'].append(json.loads(line))
            except json.JSONDecodeError: pass
    patches = sorted(selected.glob('patch_[0-9].json'))
    if patches:
        try: data['source_patch'] = json.loads(patches[-1].read_text())
        except json.JSONDecodeError: pass
    if 'report' in data: data['state'] = data['report']['status']
    return data

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == '/':
                body = (ROOT/'web/index.html').read_bytes(); ct = 'text/html; charset=utf-8'
            elif parsed.path == '/api/state':
                name = parse_qs(parsed.query).get('run', [None])[0]
                body = json.dumps(run_data(name)).encode(); ct = 'application/json; charset=utf-8'
            else:
                self.send_error(404); return
        except (ValueError, OSError) as exc:
            self.send_error(400, 'Invalid local request'); return
        self.send_response(200)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers(); self.wfile.write(body)
    def log_message(self, fmt, *args): pass

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--port', type=int, default=8731)
    args = ap.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print('NeatRescue evidence viewer on 127.0.0.1:' + str(args.port), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
