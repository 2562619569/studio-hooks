"""Probe Studio's MCP endpoint via StudioMCP.exe stdio proxy.

Speaks JSON-RPC (MCP) over the proxy's stdio and lists available tools,
then optionally calls one. Studio must be running with a place open and
mcp-server enabled in Assistant settings.
"""
import json
import subprocess
import sys
import threading
import time

PROXY = r"C:\Program Files (x86)\Roblox\Versions\version-dcbeee682ce74ee0\StudioMCP.exe"

proc = subprocess.Popen([PROXY, "-v"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8")


def reader(pipe, tag):
    for line in pipe:
        line = line.strip()
        if line:
            print("[%s] %s" % (tag, line[:400]), flush=True)


threading.Thread(target=reader, args=(proc.stderr, "err"), daemon=True).start()

_id = [0]


def send(method, params=None, notify=False):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if not notify:
        _id[0] += 1
        msg["id"] = _id[0]
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return _id[0] if not notify else None


def recv(want_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            resp = json.loads(line)
        except json.JSONDecodeError:
            print("[raw] %s" % line[:200])
            continue
        if resp.get("id") == want_id:
            return resp
        print("[msg] %s" % json.dumps(resp)[:300])
    return None


send("initialize", {"protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "studio-hooks", "version": "0.1"}})
init = recv(1)
print("== initialize:", json.dumps(init)[:300] if init else "TIMEOUT")
send("notifications/initialized", notify=True)

send("tools/list")
tools = recv(2)
if tools:
    for t in tools.get("result", {}).get("tools", []):
        print("tool:", t["name"], "-", t.get("description", "")[:80].replace("\n", " "))

if len(sys.argv) > 2 and sys.argv[1] == "call":
    name, argjson = sys.argv[2], sys.argv[3]
    send("tools/call", {"name": name, "arguments": json.loads(argjson)})
    print("== call result:", json.dumps(recv(3))[:800])

proc.terminate()
