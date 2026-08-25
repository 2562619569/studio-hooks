#!/usr/bin/env python3
"""studio-hooks launcher.

Spawns Roblox Studio under Frida, injects hook modules from config.json,
and hosts the StudioMCP proxy so in-process hooks can trigger Luau
execution in Studio (menu items that do real work).

Usage:
  python studio_hooks.py                  # spawn Studio with hooks + MCP
  python studio_hooks.py --place X.rbxl   # spawn and open a place file
  python studio_hooks.py --attach         # attach to a running Studio
  python studio_hooks.py --list           # show hooks and enabled state
  python studio_hooks.py --enable NAME    # enable a hook module
  python studio_hooks.py --disable NAME   # disable a hook module
  python studio_hooks.py --kill           # kill running Studio instances
"""

import argparse
import glob
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parent
HOOKS_DIR = ROOT / "hooks"
CONFIG_PATH = ROOT / "config.json"
COMPAT = "00_compat.js"
STUDIO_GLOB = r"C:\Program Files (x86)\Roblox\Versions\version-*\RobloxStudioBeta.exe"
MCP_PROXY = r"C:\Program Files (x86)\Roblox\Versions\version-{v}\StudioMCP.exe"


# ---------------------------------------------------------------- MCP client

class StudioMcp:
    """JSON-RPC (MCP) client for StudioMCP.exe; Studio connects back to it."""

    def __init__(self, log):
        self.log = log
        self.proc = None
        self.responses = {}
        self.lock = threading.Lock()
        self.event = threading.Event()
        self._id = 0

    def start(self):
        proxy = MCP_PROXY.format(v=self._studio_version())
        proxy_log = (ROOT / "logs" / ("mcp_proxy-%s.log" %
                     datetime.now().strftime("%Y%m%d-%H%M%S"))).open("w", encoding="utf-8")
        self.proc = subprocess.Popen([proxy, "-v"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=proxy_log,
                                     text=True, encoding="utf-8")
        self.log("[mcp] proxy stderr log: %s" % proxy_log.name)
        threading.Thread(target=self._reader, daemon=True).start()
        r = self.request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "studio-hooks", "version": "0.1"}})
        self.log("[mcp] proxy initialized: %s" % r.get("result", {}).get("serverInfo", {}))
        self.notify("notifications/initialized")

    @staticmethod
    def _studio_version():
        exe = find_studio()
        # ...\version-dcbeee682ce74ee0\RobloxStudioBeta.exe
        return Path(exe).parent.name.split("-", 1)[1] if exe else ""

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg:
                with self.lock:
                    self.responses[msg["id"]] = msg
                self.event.set()

    def request(self, method, params=None, timeout=30):
        with self.lock:
            self._id += 1
            rid = self._id
        msg = {"jsonrpc": "2.0", "method": method, "id": rid}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if rid in self.responses:
                    return self.responses.pop(rid)
            self.event.wait(0.5)
            self.event.clear()
        raise TimeoutError("MCP request timed out: %s" % method)

    def notify(self, method):
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def call_tool(self, name, arguments, timeout=60):
        r = self.request("tools/call", {"name": name, "arguments": arguments},
                         timeout=timeout)
        result = r.get("result", {})
        texts = [c.get("text", "") for c in result.get("content", [])
                 if c.get("type") == "text"]
        return {"isError": result.get("isError", False),
                "text": "\n".join(texts)}

    def list_studios(self):
        r = self.call_tool("list_roblox_studios", {})
        if r["isError"]:
            return []
        try:
            data = json.loads(r["text"])
        except json.JSONDecodeError:
            self.log("[mcp] list_studios non-JSON: %s" % r["text"][:200])
            return []
        items = data if isinstance(data, list) else data.get("studios", data.get("instances", data.get("results", [])))
        if isinstance(items, dict):
            items = [items]
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = it.get("id") or it.get("studioId") or it.get("studio_id")
            if sid:
                out.append({"id": sid,
                            "name": it.get("name") or it.get("placeName") or sid})
        if not out:
            self.log("[mcp] list_studios unparsed: %s" % r["text"][:300])
        return out

    def wait_studio(self, timeout=90):
        """Wait until a Studio instance has connected to the proxy."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                studios = self.list_studios()
            except Exception as e:  # noqa: BLE001 - transient proxy hiccups
                self.log("[mcp] list_studios retry (%s)" % e)
                studios = []
            if studios:
                sid = studios[0]["id"]
                self.log("[mcp] studio connected: %s (id=%s)" %
                         (studios[0]["name"], sid))
                return sid
            time.sleep(2)
        self.log("[mcp] no Studio connected (needs Studio started after the proxy)")
        return None

    def execute_luau(self, studio_id, code, timeout=60):
        return self.call_tool("execute_luau", {
            "code": code, "datamodel_type": "Edit", "studio_id": studio_id},
            timeout=timeout)

    def stop(self):
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
            except OSError:
                pass
            self.proc = None


# ------------------------------------------------------------------ actions
# Menu items declared by hook modules dispatch here by name.
# Luau snippets live in actions/*.lua and are re-read per call, so they
# can be edited without restarting the launcher.

ACTIONS_DIR = ROOT / "actions"


def set_clipboard_text(text):
    """Write text to the Windows clipboard (CF_UNICODETEXT, no deps)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]

    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise OSError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, len(data))       # GMEM_MOVEABLE
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(13, h)                    # CF_UNICODETEXT
    finally:
        user32.CloseClipboard()


def lua_quote(s):
    """Escape a Python string as a Luau double-quoted literal."""
    s = (s.replace("\\", "\\\\").replace('"', '\\"')
          .replace("\n", "\\n").replace("\r", ""))
    s = "".join(c for c in s if ord(c) >= 32)  # drop other control chars
    return '"%s"' % s


class Actions:
    def __init__(self, mcp, log):
        self.mcp = mcp
        self.log = log
        self.studio_id = None
        # Actions needing more than "run the lua and log its result";
        # anything not listed falls back to run_lua_action.
        self.handlers = {"copy_instance_path": self.copy_path_action}

    def ensure_studio(self):
        if self.studio_id is None:
            self.studio_id = self.mcp.wait_studio(timeout=10)
        return self.studio_id

    def dispatch(self, name, arg=None):
        if not name:
            return
        handler = self.handlers.get(name, self.run_lua_action)
        try:
            handler(name, arg)
        except Exception as e:  # noqa: BLE001 - action layer must not kill session
            self.log("[action] %r failed: %s" % (name, e))

    def run_lua_action(self, name, area):
        sid = self.ensure_studio()
        if not sid:
            self.log("[action] %s skipped: no Studio connected to MCP" % name)
            return
        code = (ACTIONS_DIR / ("%s.lua" % name)).read_text(encoding="utf-8")
        code = 'local HOOK_AREA = "%s"\n' % (area or "other") + code
        r = self.mcp.execute_luau(sid, code)
        status = "error" if r["isError"] else "ok"
        self.log("[action] %s -> %s: %s" % (name, status, r["text"]))

    def copy_path_action(self, name, area):
        """Run copy_instance_path.lua and put the returned path(s) on the
        Windows clipboard (Luau has no clipboard API)."""
        sid = self.ensure_studio()
        if not sid:
            self.log("[action] %s skipped: no Studio connected to MCP" % name)
            return
        code = (ACTIONS_DIR / ("%s.lua" % name)).read_text(encoding="utf-8")
        code = 'local HOOK_AREA = "%s"\n' % (area or "other") + code
        r = self.mcp.execute_luau(sid, code)
        if r["isError"]:
            self.log("[action] %s error: %s" % (name, r["text"][:300]))
            return
        text = r["text"].strip().strip('"')
        if not text:
            self.log("[action] %s: empty result" % name)
            return
        set_clipboard_text(text)
        self.log("[action] %s -> clipboard (%d chars): %s" %
                 (name, len(text), text.replace("\n", " | ")))

    def print_to_output(self, text):
        """print() inside Studio so the message lands in the Output panel."""
        sid = self.ensure_studio()
        if not sid:
            self.log("[print] skipped: no Studio connected to MCP")
            return
        r = self.mcp.execute_luau(sid, "print(%s)" % lua_quote(text))
        if r["isError"]:
            self.log("[print] error: %s" % r["text"][:300])


# ------------------------------------------------------------------ launcher

def ensure_mcp_enabled(log):
    """Studio's MCP client is off by default per Roblox account; turn it on
    in every AssistantSettings profile so spawned Studios register with the
    proxy (otherwise list_roblox_studios stays empty)."""
    import glob as _glob
    pattern = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox",
                           "AssistantSettings", "*.json")
    for path in _glob.glob(pattern):
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
            if data.get("mcp-server", {}).get("enabled") is True:
                continue
            data["mcp-server"] = {"enabled": True}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            log("[mcp] enabled mcp-server in %s" % Path(path).name)
        except (OSError, json.JSONDecodeError) as e:
            log("[mcp] could not patch %s: %s" % (path, e))


def load_config():
    if not CONFIG_PATH.exists():
        return {"hooks": ["context_menu_demo.js"]}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")


def find_studio():
    """Newest RobloxStudioBeta.exe by file mtime (survives version bumps)."""
    candidates = glob.glob(STUDIO_GLOB)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def build_script_source(cfg):
    menu_cfg = {
        "entries": cfg.get("menuEntries", []),
        "areaRules": cfg.get("areaRules", []),
        "debug": cfg.get("debug", False),
    }
    parts = ["// ---- %s (compat) ----" % COMPAT,
             (HOOKS_DIR / COMPAT).read_text(encoding="utf-8"),
             "\nglobalThis.SH_CONFIG = %s;\n" % json.dumps(menu_cfg, ensure_ascii=False)]
    for name in cfg.get("hooks", []):
        path = HOOKS_DIR / name
        if not path.exists():
            print("[!] missing hook file, skipped: %s" % name)
            continue
        parts.append("\n// ---- %s ----" % name)
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def run_session(device, pid, cfg, attach_mode, log_file):
    def log(msg):
        print(msg, flush=True)
        log_file.write(str(msg) + "\n")
        log_file.flush()

    log_path = Path(log_file.name)
    print("[*] session log: %s" % log_path, flush=True)

    mcp = StudioMcp(log)
    mcp.start()
    actions = Actions(mcp, log)

    source = build_script_source(cfg)
    session = device.attach(pid)
    script = session.create_script(source, name="studio-hooks")

    def on_message(message, _data):
        if message["type"] == "send":
            payload = message.get("payload") or {}
            if payload.get("event") == "menu_trigger":
                log("[hook] menu_trigger: %s (area=%s)" %
                    (payload.get("action"), payload.get("area")))
                actions.dispatch(payload.get("action"), payload.get("area"))
            elif payload.get("event") == "menu_show":
                area = payload.get("area")
                chain = payload.get("chain", "")
                log("[hook] menu_show @(%s,%s) area=%s chain=%s" %
                    (payload.get("x"), payload.get("y"), area, chain))
                actions.print_to_output(
                    "[studio-hooks] 右键 @(%s,%s) → 区域: %s\n  身份链: %s"
                    % (payload.get("x"), payload.get("y"), area, chain))
            else:
                log("[hook] %s" % payload)
        elif message["type"] == "error":
            log("[script-error] %s" % message.get("description", message))
        else:
            log("[msg] %s" % message)

    script.on("message", on_message)
    script.load()
    log("[*] hooks loaded")

    if not attach_mode:
        device.resume(pid)
        sid = mcp.wait_studio()
        if sid:
            actions.studio_id = sid

    done = threading.Event()

    def on_detached(reason, *extra):
        log("[*] session detached: %s" % reason)
        done.set()

    session.on("detached", on_detached)
    log("[*] watching Studio (Ctrl+C to detach, Studio keeps running)")
    try:
        while not done.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        session.detach()
        mcp.stop()          # free the proxy's port before the next session
        log_file.close()


def watch_loop(device, cfg):
    """Stay resident forever: whenever RobloxStudioBeta.exe starts (however
    it was launched), attach the hooks and host the MCP proxy; when that
    Studio exits, go back to scanning."""
    while True:
        pid = None
        try:
            pid = device.get_process("RobloxStudioBeta.exe").pid
        except frida.ProcessNotFoundError:
            pass
        if pid is None:
            time.sleep(1.5)
            continue
        print("[watch] Studio started (pid=%s); giving Qt a moment to load "
              "before attach..." % pid, flush=True)
        time.sleep(4)
        log_file = (ROOT / "logs" / ("session-%s.log" %
                    datetime.now().strftime("%Y%m%d-%H%M%S"))).open(
                        "w", encoding="utf-8")
        try:
            run_session(device, pid, cfg, attach_mode=True, log_file=log_file)
        except Exception as e:  # noqa: BLE001 - keep watching regardless
            print("[watch] session error: %s" % e, flush=True)
            log_file.close()
        print("[watch] session ended; waiting for the next Studio start",
              flush=True)
        time.sleep(2)


def main():
    ap = argparse.ArgumentParser(description="Roblox Studio UI hook launcher")
    ap.add_argument("--place", help="place file to open on spawn")
    ap.add_argument("--attach", action="store_true", help="attach to running Studio")
    ap.add_argument("--watch", action="store_true",
                    help="stay resident: auto-attach hooks to every Studio start")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--enable")
    ap.add_argument("--disable")
    ap.add_argument("--kill", action="store_true")
    args = ap.parse_args()

    cfg = load_config()

    if args.list:
        enabled = set(cfg.get("hooks", []))
        for f in sorted(HOOKS_DIR.glob("*.js")):
            mark = "on " if f.name in enabled else "off"
            print("  [%s] %s" % (mark, f.name))
        return

    if args.enable or args.disable:
        name = args.enable or args.disable
        if not (HOOKS_DIR / name).exists():
            sys.exit("no such hook: %s" % name)
        hooks = cfg.setdefault("hooks", [])
        if args.enable and name not in hooks:
            hooks.append(name)
        if args.disable and name in hooks:
            hooks.remove(name)
        save_config(cfg)
        print("hooks now: %s" % hooks)
        return

    if args.kill:
        os.system("taskkill /IM RobloxStudioBeta.exe /F")
        return

    device = frida.get_local_device()

    (ROOT / "logs").mkdir(exist_ok=True)
    log_file = (ROOT / "logs" / ("session-%s.log" %
                 datetime.now().strftime("%Y%m%d-%H%M%S"))).open("w", encoding="utf-8")
    ensure_mcp_enabled(lambda m: (print(m, flush=True),
                                  log_file.write(m + "\n")))

    if args.watch:
        watch_loop(device, cfg)
        return

    if args.attach:
        try:
            pid = device.get_process("RobloxStudioBeta.exe").pid
        except frida.ProcessNotFoundError:
            sys.exit("RobloxStudioBeta.exe is not running")
        run_session(device, pid, cfg, attach_mode=True, log_file=log_file)
        return

    exe = cfg.get("studioPath") or find_studio()
    if not exe:
        sys.exit("Roblox Studio not found under %s" % STUDIO_GLOB)
    argv = [exe] + ([args.place] if args.place else []) + cfg.get("studioArgs", [])
    print("[*] spawning: %s" % " ".join(argv), flush=True)
    pid = device.spawn(argv)
    run_session(device, pid, cfg, attach_mode=False, log_file=log_file)


if __name__ == "__main__":
    main()
