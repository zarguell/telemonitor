#!/usr/bin/env python3
"""Local webhook receiver for E2E tests.

Listens on 0.0.0.0:9899, appends each received JSON payload to
scripts/.webhook_payloads.log as a JSON line.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".webhook_payloads.log")


class Handler(BaseHTTPRequestHandler):
    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        record = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "path": self.path,
            "body": json.loads(body) if body else None,
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    do_POST = _handle
    do_GET = _handle

    def log_message(self, *args) -> None:  # silence
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9899
    print(f"webhook receiver listening on :{port}, logging to {LOG_PATH}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
