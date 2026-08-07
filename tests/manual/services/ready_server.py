from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import signal
import socket
import sys


running = True


def stop(signum: int, _frame: object) -> None:
    global running
    print(f"ready server received signal {signum}", flush=True)
    running = False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status = 200 if self.path == "/health" else 404
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"ok" if status == 200 else b"not found")

    def log_message(self, _format: str, *_args: object) -> None:
        return


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

protocol = sys.argv[1]
port = int(sys.argv[2])
print(f"{protocol} server started pid={os.getpid()} port={port}", flush=True)

if protocol == "http":
    server = HTTPServer(("127.0.0.1", port), HealthHandler)
    server.timeout = 0.2
    while running:
        server.handle_request()
    server.server_close()
elif protocol == "tcp":
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen()
        server.settimeout(0.2)
        while running:
            try:
                connection, _address = server.accept()
            except socket.timeout:
                continue
            connection.close()
else:
    raise SystemExit(f"Unsupported protocol: {protocol}")

print(f"{protocol} server stopped cleanly", flush=True)
