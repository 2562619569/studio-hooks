#!/usr/bin/env python3
"""End-to-end check of the Explorer 'copy instance path' menu item:
select an Explorer row, right-click it, choose the last menu item
(our injected entry) with UP+ENTER, then read the clipboard."""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]


def key(vk, up=False):
    user32.keybd_event(vk, 0, 0x0002 if up else 0, 0)
    time.sleep(0.04)


def press(vk):
    key(vk)
    key(vk, True)
    time.sleep(0.12)


def click(down, up):
    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(up, 0, 0, 0, 0)


def read_clipboard():
    s = None
    if user32.OpenClipboard(0):
        h = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if h:
            p = kernel32.GlobalLock(h)
            s = ctypes.wstring_at(p)
            kernel32.GlobalUnlock(h)
        user32.CloseClipboard()
    return s


def main():
    x, y = 1900, 400
    press(0x1B)                      # ESC: close any stale menu
    time.sleep(0.3)
    user32.SetCursorPos(x, y)
    time.sleep(0.3)
    click(0x0002, 0x0004)            # left: select the node under cursor
    time.sleep(0.4)
    click(0x0008, 0x0010)            # right: open context menu
    time.sleep(0.8)
    press(0x26)                      # UP: highlight LAST item (selection_info)
    press(0x26)                      # UP: second-to-last = copy_instance_path
    press(0x0D)                      # ENTER: trigger it
    time.sleep(2.0)
    print("clipboard:", repr(read_clipboard()))


if __name__ == "__main__":
    main()
