#!/usr/bin/env python3
"""Simulate a right-click at an absolute screen coordinate (for testing
the context-menu hooks without a human at the console).

Usage: python tools/right_click.py X Y [--wait 0.4]
"""

import argparse
import ctypes
import time

user32 = ctypes.windll.user32

MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def click(x, y, wait, button):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(wait)          # let hover/motion handlers settle before the click
    down, up = ((MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left"
                else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP))
    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(up, 0, 0, 0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("x", type=int)
    ap.add_argument("y", type=int)
    ap.add_argument("--wait", type=float, default=0.4,
                    help="pause after moving the cursor, before clicking")
    ap.add_argument("--left", action="store_true", help="left-click instead")
    ap.add_argument("--close", action="store_true",
                    help="send ESC afterwards to dismiss the menu")
    args = ap.parse_args()
    click(args.x, args.y, args.wait, "left" if args.left else "right")
    if args.close:
        time.sleep(0.6)
        # ESC keydown/keyup
        for flags in (0x0000, 0x0002):
            user32.keybd_event(0x1B, 0, flags, 0)
            time.sleep(0.03)
    print("%s-clicked at (%d, %d)" % ("left" if args.left else "right",
                                      args.x, args.y))


if __name__ == "__main__":
    main()
