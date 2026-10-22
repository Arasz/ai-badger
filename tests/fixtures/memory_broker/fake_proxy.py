"""Fake `ai-raccoon` proxy that answers tools/call requests concurrently and out of order.

Each tools/call is served on its own thread after a delay, so replies leave in the order the
delays end, not the order requests arrived. A query of `slow:<seconds>:<text>` sets that
request's delay; `die` exits the process mid-request; `hang` never replies. Every start is
appended to FAKE_PROXY_LOG. The default delay comes from FAKE_PROXY_DELAY (seconds).
"""
import json
import os
import sys
import threading
import time

DELAY = float(os.environ.get("FAKE_PROXY_DELAY", "0.3"))
LOG = os.environ.get("FAKE_PROXY_LOG", "")
WRITE_LOCK = threading.Lock()


def send(obj):
    """Write one JSON line to stdout."""
    with WRITE_LOCK:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def reply_for(msg_id, query):
    """A query reply whose single hit echoes the query."""
    payload = {"data": {"results": [{"hash": "h-" + query, "path": "/echo/" + query,
                                     "snippet": "echo " + query, "ranking": 1}], "code": []}}
    return {"jsonrpc": "2.0", "id": msg_id,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def serve_call(msg):
    """Answer one tools/call after its delay."""
    query = str(msg["params"]["arguments"].get("query", ""))
    delay = DELAY
    if query.startswith("slow:"):
        _, seconds, query = query.split(":", 2)
        delay = float(seconds)
    if query == "die":
        os._exit(3)
    if query == "hang":
        return
    time.sleep(delay)
    send(reply_for(msg["id"], query))


def main():
    """Read requests until EOF."""
    if LOG:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "event": "start"}) + "\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "fake", "version": "1"}}})
        elif method == "tools/call":
            threading.Thread(target=serve_call, args=(msg,), daemon=True).start()


if __name__ == "__main__":
    main()
