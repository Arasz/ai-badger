"""Fake `ai-raccoon` proxy for the memory-context tests: newline-delimited JSON-RPC on stdio.

Behaviour comes from FAKE_RACCOON_MODE; every event is appended to the JSONL log named by
FAKE_RACCOON_LOG. The whole process ends by FAKE_RACCOON_CEILING seconds (default 20).
"""
import json
import os
import select
import signal
import subprocess
import sys
import time

MODE = os.environ.get("FAKE_RACCOON_MODE", "hits")
LOG = os.environ.get("FAKE_RACCOON_LOG", "")
CEILING = float(os.environ.get("FAKE_RACCOON_CEILING", "20"))
HITS_FILE = os.environ.get("FAKE_RACCOON_HITS", "")

DEFAULT_HITS = {
    "results": [
        {"hash": "m-one", "ranking": 1, "path": "/repo/docs/one.md", "snippet": "first memory"},
        {"hash": "m-two", "ranking": 0.5, "path": "/repo/docs/two.md", "snippet": "second memory"},
    ],
    "code": [
        {"hash": "c-one", "ranking": 0.75, "path": "/repo/src/one.py", "snippet": "def one(): pass",
         "lineStart": 1, "lineEnd": 2},
    ],
}


def log(event, **fields):
    """Append one event for this pid to the log."""
    if not LOG:
        return
    record = {"pid": os.getpid(), "event": event, **fields}
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


class Stdin:
    """Line reader over fd 0 that logs every line and EOF."""

    def __init__(self):
        self.buffer = b""
        self.eof = False

    def ready(self, timeout):
        """True when a byte (or EOF) can be read within *timeout* seconds."""
        if b"\n" in self.buffer or self.eof:
            return True
        readable, _, _ = select.select([0], [], [], timeout)
        return bool(readable)

    def line(self):
        """The next line, or None at EOF."""
        while b"\n" not in self.buffer:
            if self.eof:
                return None
            chunk = os.read(0, 65536)
            if not chunk:
                self.eof = True
                log("eof")
                return None
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b"\n", 1)
        text = raw.decode("utf-8", errors="replace")
        log("line", line=text)
        return text


def send(obj):
    """Write one JSON line to stdout."""
    os.write(1, (json.dumps(obj) + "\n").encode("utf-8"))


def text_result(msg_id, payload, is_error=False):
    """A tools/call reply whose content is one text part."""
    result = {"content": [{"type": "text", "text": payload}]}
    if is_error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def hits_reply(msg_id, hits):
    """A memory_search reply carrying *hits* ({results, code}) under data."""
    return text_result(msg_id, json.dumps({"data": hits, "meta": {}}))


def hits_for(request):
    """Hits for a tools/call request: per-query map in perquery/latereply modes."""
    if MODE not in ("perquery", "latereply"):
        return DEFAULT_HITS
    with open(HITS_FILE, encoding="utf-8") as handle:
        table = json.load(handle)
    query = request.get("params", {}).get("arguments", {}).get("query")
    return table.get(query, {"results": [], "code": []})


def sleep_out():
    """Block until the ceiling ends the process."""
    while True:
        time.sleep(1)


def handshake(stdin):
    """Answer initialize; return False when stdin closed first."""
    while True:
        line = stdin.line()
        if line is None:
            return False
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("method") == "initialize":
            if MODE == "slowinit":
                time.sleep(0.3)
                early = stdin.ready(0)
                log("slowinit", early_write=early)
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "serverInfo": {"name": "fake", "version": "1"}}})
            return True


def next_call(stdin):
    """The next tools/call request, or None at EOF."""
    while True:
        line = stdin.line()
        if line is None:
            return None
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("method") == "tools/call":
            return msg


def answer(msg):
    """Reply to one tools/call as the mode dictates."""
    msg_id = msg["id"]
    if MODE == "iserror":
        # A well-formed hits body, so only the isError flag tells it apart from a success.
        send(text_result(msg_id, json.dumps({"data": DEFAULT_HITS}), is_error=True))
    elif MODE == "rpcerror":
        send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "no"}})
    elif MODE == "empty":
        send(hits_reply(msg_id, {"results": [], "code": []}))
    elif MODE == "malformed":
        os.write(1, b"\n   \nnot json at all\n[1, 2]\n")
        send({"jsonrpc": "2.0", "id": 999, "result": {}})
        send({"jsonrpc": "2.0", "id": str(msg_id), "result": {}})
        send(hits_reply(msg_id, DEFAULT_HITS))
    else:
        send(hits_reply(msg_id, hits_for(msg)))


def serve(stdin):
    """Loop over tools/call requests until EOF, per mode."""
    if MODE in ("hang", "grandchild"):
        while stdin.line() is not None:
            pass
        sleep_out()
    if MODE == "nostdin":
        sleep_out()
    if MODE == "oversize":
        next_call(stdin)
        chunk = b"x" * 65536
        for _ in range(80):
            os.write(1, chunk)
        sleep_out()
    if MODE == "drip":
        msg = next_call(stdin)
        data = (json.dumps(hits_reply(msg["id"], DEFAULT_HITS)) + "\n").encode("utf-8")
        for byte in data:
            os.write(1, bytes([byte]))
            time.sleep(0.1)
        sleep_out()
    if MODE == "crash":
        next_call(stdin)
        os._exit(3)
    if MODE == "latereply":
        first = next_call(stdin)
        second = next_call(stdin)
        if first is None or second is None:
            return
        answer(first)
        answer(second)
    while True:
        msg = next_call(stdin)
        if msg is None:
            return
        answer(msg)


def main():
    """Run the fake until stdin closes or the ceiling hits."""
    signal.setitimer(signal.ITIMER_REAL, CEILING)
    log("start", argv=sys.argv, mode=MODE)
    if MODE == "grandchild":
        child = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, "-c", f"import time; time.sleep({CEILING})"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("grandchild", grandchild=child.pid)
    stdin = Stdin()
    if not handshake(stdin):
        return
    serve(stdin)


if __name__ == "__main__":
    main()
