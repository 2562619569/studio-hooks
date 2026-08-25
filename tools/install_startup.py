#!/usr/bin/env python3
"""Install (or --remove) a login startup shortcut that runs the hook
watcher silently with pythonw, so every Studio launch gets the hooks
without opening a console. Usage:
  python tools/install_startup.py           # install
  python tools/install_startup.py --remove  # uninstall
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def startup_dir():
    import os
    return Path(os.environ["APPDATA"]) / \
        "Microsoft/Windows/Start Menu/Programs/Startup"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    lnk = startup_dir() / "studio-hooks watch.lnk"
    if args.remove:
        lnk.unlink(missing_ok=True)
        print("removed:", lnk)
        return

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        sys.exit("pythonw.exe not found next to %s" % sys.executable)

    ps = "\n".join([
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s')" % lnk,
        "$s.TargetPath = '%s'" % pythonw,
        "$s.Arguments = '\"%s\" --watch'" % (ROOT / "studio_hooks.py"),
        "$s.WorkingDirectory = '%s'" % ROOT,
        "$s.WindowStyle = 7",
        "$s.Save()",
    ])
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print("installed:", lnk)
    print("hooks will follow every Studio launch after next login "
          "(silent pythonw watcher)")


if __name__ == "__main__":
    main()
