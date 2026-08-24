#!/usr/bin/env python3
"""studio-hooks launcher.

Spawns Roblox Studio under Frida and injects the hook modules listed
in config.json. Auto-discovers the newest installed Studio version so
weekly updates don't break the launcher.

Usage:
  python studio_hooks.py                  # spawn Studio with hooks
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
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import frida

ROOT = Path(__file__).resolve().parent
HOOKS_DIR = ROOT / "hooks"
CONFIG_PATH = ROOT / "config.json"
COMPAT = "00_compat.js"
STUDIO_GLOB = r"C:\Program Files (x86)\Roblox\Versions\version-*\RobloxStudioBeta.exe"


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
    parts = ["// ---- %s (compat) ----" % COMPAT,
             (HOOKS_DIR / COMPAT).read_text(encoding="utf-8")]
    for name in cfg.get("hooks", []):
        path = HOOKS_DIR / name
        if not path.exists():
            print("[!] missing hook file, skipped: %s" % name)
            continue
        parts.append("\n// ---- %s ----" % name)
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def on_message_factory(log_file):
    def on_message(message, data):
        if message["type"] == "send":
            line = str(message.get("payload"))
        elif message["type"] == "error":
            line = "[script-error] %s" % message.get("description", message)
        else:
            line = str(message)
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()
    return on_message


def run_session(device, target_pid_or_spawn, cfg, attach_mode):
    log_path = ROOT / "logs" / ("session-%s.log" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    (ROOT / "logs").mkdir(exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    log_file.write("# studio-hooks session  pid=%s\n" % target_pid_or_spawn)

    source = build_script_source(cfg)
    session = device.attach(target_pid_or_spawn)
    script = session.create_script(source, name="studio-hooks")
    script.on("message", on_message_factory(log_file))
    script.load()
    print("[*] hooks loaded, session log: %s" % log_path)

    if not attach_mode:
        device.resume(target_pid_or_spawn)

    try:
        sys.stdin.read() if sys.stdin.isatty() else time.sleep(1 << 30)
    except KeyboardInterrupt:
        pass
    finally:
        session.detach()
        log_file.close()
        print("[*] detached (Studio keeps running)")


def main():
    ap = argparse.ArgumentParser(description="Roblox Studio UI hook launcher")
    ap.add_argument("--place", help="place file to open on spawn")
    ap.add_argument("--attach", action="store_true", help="attach to running Studio")
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

    if args.attach:
        try:
            pid = device.get_process("RobloxStudioBeta.exe").pid
        except frida.ProcessNotFoundError:
            sys.exit("RobloxStudioBeta.exe is not running")
        run_session(device, pid, cfg, attach_mode=True)
        return

    exe = cfg.get("studioPath") or find_studio()
    if not exe:
        sys.exit("Roblox Studio not found under %s" % STUDIO_GLOB)
    argv = [exe] + ([args.place] if args.place else []) + cfg.get("studioArgs", [])
    print("[*] spawning: %s" % " ".join(argv))
    pid = device.spawn(argv)
    run_session(device, pid, cfg, attach_mode=False)


if __name__ == "__main__":
    main()
