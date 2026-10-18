#!/usr/bin/env python3
"""A scripted stdio MCP server for the mcp_client tests. `argv[1]` picks the behaviour.

Modes:
  ok         two tools/list pages, a noise line, an interleaved notification, a server-initiated
             `ping` and an unknown request it waits on before answering, old protocolVersion
  hang       reads requests and never answers
  exit       writes a reason to stderr and exits 3 before answering
  page-error answers the first tools/list page, errors on the second
  loop       every tools/list page carries a nextCursor
  chatty     writes ~1 MiB to stderr before answering, so an undrained stderr would deadlock
"""

import json
import os
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def read():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    return json.loads(line)


def answer(request, result):
    send({"jsonrpc": "2.0", "id": request["id"], "result": result})


def ask(method, request_id):
    """Send a server-to-client request and return the client's reply."""
    send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": {}})
    while True:
        message = read()
        if message.get("id") == request_id and "method" not in message:
            return message


def fail(text):
    sys.stderr.write(text + "\n")
    sys.exit(4)


def main():
    if MODE == "exit":
        sys.stderr.write("starting\nfatal: database is locked\n")
        sys.exit(3)
    initialize = read()
    if MODE == "hang":
        while True:
            time.sleep(1)
    if initialize.get("method") != "initialize":
        fail("first message was not initialize")
    if initialize["params"].get("capabilities") != {}:
        fail("capabilities were not {}")
    if MODE == "ok":
        sys.stdout.write("server banner on stdout, not JSON\n")
    if MODE == "chatty":
        sys.stderr.write("x" * (1 << 20) + "\n")
        sys.stderr.flush()
    answer(initialize, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake", "version": "0"}})
    initialized = read()
    if initialized.get("method") != "notifications/initialized" or "id" in initialized:
        fail("expected notifications/initialized before anything else")
    page = 0
    while True:
        request = read()
        if request.get("method") != "tools/list":
            fail(f"unexpected {request.get('method')}")
        page += 1
        if MODE == "ok" and page == 1:
            send({"jsonrpc": "2.0", "method": "notifications/message", "params": {}})
            pong = ask("ping", "srv-1")
            if pong.get("result") != {}:
                fail("ping was not answered with {}")
            refused = ask("sampling/createMessage", "srv-2")
            if refused.get("error", {}).get("code") != -32601:
                fail("unknown request was not refused with -32601")
            answer(request, {"tools": [{"name": "alpha", "description": "First tool."}],
                             "nextCursor": "p2"})
            continue
        if MODE == "ok":
            if request["params"].get("cursor") != "p2":
                fail("second page did not carry the cursor")
            answer(request, {"tools": [{"name": "beta"}]})
            continue
        if MODE == "page-error" and page == 2:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32000, "message": "backend went away"}})
            continue
        if MODE in ("page-error", "loop"):
            answer(request, {"tools": [{"name": f"t{page}"}], "nextCursor": f"c{page}"})
            continue
        answer(request, {"tools": [{"name": os.environ.get("FAKE_SOLO_NAME", "solo"),
                                    "description": os.environ.get("FAKE_SOLO_DESC",
                                                                  "Only tool.")}]})


if __name__ == "__main__":
    main()
