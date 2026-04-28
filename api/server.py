#!/usr/bin/env python3
"""
MYO Dashboard Server
Serve o dashboard em tempo real, regenerando a cada acesso.

Uso:
  python3 server.py              → porta 8080
  python3 server.py --port 3000  → porta customizada
  python3 server.py --watch      → modo watch (regenera a cada 60s em background)

Acesso:
  Mesmo computador : http://localhost:8080
  Celular/tablet   : http://[SEU-IP]:8080  (mesma rede Wi-Fi)
  Internet (ngrok) : ngrok http 8080
"""

import argparse
import http.server
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASH_FILE = os.path.join(BASE_DIR, "dashboard.html")
GEN_FILE = os.path.join(BASE_DIR, "generate_dashboard.py")


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def regenerate(silent=False):
    if not silent:
        print("  ↻ Regenerando dashboard...", end=" ", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, GEN_FILE], capture_output=True, text=True, cwd=BASE_DIR
        )
        if result.returncode == 0:
            if not silent:
                print("✓")
        else:
            if not silent:
                print("✗ (erro):")
                print(result.stderr[:300])
    except Exception as e:
        if not silent:
            print(f"✗ ({e})")


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Regenera antes de servir o dashboard principal
        if self.path in ("/", "/dashboard.html", "/index.html"):
            regenerate()
            self.path = "/dashboard.html"
        # Serve manifest e ícones PWA com headers corretos
        elif self.path == "/manifest.json":
            self._serve_file("manifest.json", "application/manifest+json")
            return
        elif self.path in ("/icon-192.png", "/icon-512.png"):
            self._serve_file(self.path.lstrip("/"), "image/png")
            return
        elif self.path == "/chart.umd.min.js":
            self._serve_file("chart.umd.min.js", "application/javascript")
            return
        super().do_GET()

    def _serve_file(self, filename, content_type):
        path = os.path.join(BASE_DIR, filename)
        if not os.path.exists(path):
            self.send_error(404)
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        code = args[1] if len(args) > 1 else "?"
        path = args[0].split(" ")[1] if args else "?"
        if path in ("/", "/dashboard.html"):
            print(f"  [{time.strftime('%H:%M:%S')}] Dashboard acessado → HTTP {code}")


def watch_loop(interval=60):
    """Regenera em background a cada N segundos."""
    while True:
        time.sleep(interval)
        regenerate(silent=True)


def main():
    parser = argparse.ArgumentParser(description="MYO Dashboard Server")
    parser.add_argument("--port", type=int, default=PORT, help="Porta HTTP (padrão: 8080)")
    parser.add_argument("--watch", action="store_true", help="Auto-regenerar a cada 60s")
    parser.add_argument("--interval", type=int, default=60, help="Intervalo watch em segundos")
    args = parser.parse_args()

    os.chdir(BASE_DIR)

    # Primeira geração
    print("\n  MYO Dashboard Server")
    print("  " + "─" * 38)
    regenerate()

    # Watch mode
    if args.watch:
        t = threading.Thread(target=watch_loop, args=(args.interval,), daemon=True)
        t.start()
        print(f"  ⏱  Watch mode ativo: regenera a cada {args.interval}s")

    local_ip = get_local_ip()
    print("\n  📡 Servidor rodando:")
    print(f"     Localhost  → http://localhost:{args.port}")
    print(f"     Rede local → http://{local_ip}:{args.port}  ← use no celular")
    print("\n  Para acessar de qualquer lugar (internet):")
    print("     1. Instale ngrok: brew install ngrok")
    print(f"     2. Execute:  ngrok http {args.port}")
    print("     3. Use a URL https://xxxx.ngrok.io no celular/tablet")
    print("\n  Pressione Ctrl+C para parar\n")

    with socketserver.TCPServer(("", args.port), DashboardHandler) as httpd:
        httpd.allow_reuse_address = True
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n  Servidor encerrado.")


if __name__ == "__main__":
    main()
