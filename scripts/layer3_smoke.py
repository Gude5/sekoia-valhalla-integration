"""
Layer 3 end-to-end smoke test for `SyncSigmaRulesCatalog`.

Spins up an in-process HTTP server that mocks the Sekoia Rules Catalog API,
points the trigger at it, and drives `_sync_once()` twice against the live
Valhalla demo feed.

What this catches that the unit tests don't:
  - Real-world feed shape (~3.6k rules, the actual content/level distribution).
  - HTTP round-tripping for every rule (auth header, body shape, response parsing).
  - First-pass POST → state persisted → second-pass PUT loop with no duplicates.

Run from the module root with the project venv active, e.g.:
    .venv/bin/python scripts/layer3_smoke.py
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import mkdtemp
from typing import ClassVar
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sekoia_valhalla_integration_modules.client import ValhallaClient  # noqa: E402
from sekoia_valhalla_integration_modules.sekoia_client import SekoiaClient  # noqa: E402
from sekoia_valhalla_integration_modules.triggers.sync_sigma_rules_catalog import (  # noqa: E402
    UUID_MAP_FILE,
    SyncSigmaRulesCatalog,
)

EXPECTED_BEARER = "fake-sekoia-token"
RULES_PATH = "/v1/sic/conf/rules-catalog/rules"


class MockSekoia(BaseHTTPRequestHandler):
    posts: ClassVar[list[dict]] = []
    puts: ClassVar[list[dict]] = []
    bad_auth: ClassVar[int] = 0

    def log_message(self, *_args):
        pass  # silence access log

    def _check_auth(self) -> bool:
        if self.headers.get("Authorization") != f"Bearer {EXPECTED_BEARER}":
            type(self).bad_auth += 1
            self._reply(401, {"message": "Authentication required"})
            return False
        return True

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self._reply(400, {"message": "Bad JSON"})
            return None

    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._check_auth():
            return
        if self.path != RULES_PATH:
            self._reply(404, {"message": "Not found"})
            return
        body = self._read_json()
        if body is None:
            return
        new_uuid = str(uuid.uuid4())
        type(self).posts.append({"uuid": new_uuid, "name": body.get("name")})
        self._reply(200, {"uuid": new_uuid})

    def do_PUT(self) -> None:
        if not self._check_auth():
            return
        prefix = f"{RULES_PATH}/"
        if not self.path.startswith(prefix):
            self._reply(404, {"message": "Not found"})
            return
        sekoia_uuid = self.path[len(prefix):]
        body = self._read_json()
        if body is None:
            return
        type(self).puts.append({"uuid": sekoia_uuid, "name": body.get("name")})
        self._reply(200, {})


def start_mock() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockSekoia)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def build_trigger(sekoia_url: str, storage: Path) -> SyncSigmaRulesCatalog:
    trigger = SyncSigmaRulesCatalog(data_path=storage)
    trigger._valhalla = ValhallaClient("https://valhalla.nextron-systems.com", "1" * 64)
    trigger._sekoia = SekoiaClient(sekoia_url, EXPECTED_BEARER)
    trigger._alert_type_uuid = "00000000-0000-0000-0000-000000000000"
    trigger._enabled = False
    trigger.send_event = MagicMock()
    trigger._send_logs_to_api = MagicMock()
    return trigger


def main() -> int:
    storage = Path(mkdtemp(prefix="valhalla-layer3-"))
    server, sekoia_url = start_mock()
    print(f"mock Sekoia: {sekoia_url}")
    print(f"storage:     {storage}")
    print()

    trigger = build_trigger(sekoia_url, storage)

    # First sync — every rule should hit the POST path.
    print("=== first sync (expect ~3,591 POSTs, 0 PUTs) ===")
    t0 = time.time()
    trigger._sync_once()
    elapsed = time.time() - t0

    posts = len(MockSekoia.posts)
    puts = len(MockSekoia.puts)
    summary = trigger.send_event.call_args.kwargs["event"]
    print(f"elapsed:       {elapsed:.1f}s")
    print(f"server saw:    POST={posts} PUT={puts} bad_auth={MockSekoia.bad_auth}")
    print(f"emit summary:  {summary}")

    assert posts > 0, "no POSTs happened"
    assert puts == 0, "PUTs happened on first sync"
    assert MockSekoia.bad_auth == 0, "auth-header rejected by mock"
    assert summary == {"created": posts, "updated": 0}

    state_path = storage / UUID_MAP_FILE
    assert state_path.is_file(), "state file not written"
    state = json.loads(state_path.read_text())
    assert len(state) == posts, f"state size {len(state)} != POST count {posts}"
    print(f"state file:    {state_path.name} with {len(state)} entries")

    # Second sync — every rule should now be PUT, no POSTs.
    print("\n=== second sync (expect 0 POSTs, all PUTs) ===")
    MockSekoia.posts.clear()
    MockSekoia.puts.clear()
    trigger.send_event.reset_mock()

    t0 = time.time()
    trigger._sync_once()
    elapsed = time.time() - t0

    posts = len(MockSekoia.posts)
    puts = len(MockSekoia.puts)
    summary = trigger.send_event.call_args.kwargs["event"]
    print(f"elapsed:       {elapsed:.1f}s")
    print(f"server saw:    POST={posts} PUT={puts} bad_auth={MockSekoia.bad_auth}")
    print(f"emit summary:  {summary}")

    assert posts == 0, "second sync POSTed; dedup broken"
    assert puts > 0, "no PUTs happened on second sync"
    assert summary == {"created": 0, "updated": puts}

    # Spot-check: every PUT targeted a UUID that's actually in our state map.
    state_uuids = set(state.values())
    put_uuids = {p["uuid"] for p in MockSekoia.puts}
    leaked = put_uuids - state_uuids
    assert not leaked, f"PUT targeted unknown UUIDs: {sorted(leaked)[:5]}..."
    print(f"all {len(put_uuids)} PUT targets present in state map")

    print("\n=== PASS — Layer 3 sync-loop verified end-to-end ===")
    server.shutdown()
    shutil.rmtree(storage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
