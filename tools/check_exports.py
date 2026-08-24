#!/usr/bin/env python3
"""Attach to the running Studio and list Qt exports matching keywords,
to verify which mangled symbols exist before hooking them."""

import sys
import time

import frida

KEYWORDS = sys.argv[1:] or [
    "activeWindow", "focusWidget", "inherits", "qt_metacast",
    "parentWidget", "childAt", "mapFromGlobal", "widgetAt",
    "topLevelAt", "window",
]

SCRIPT = r"""
var want = %s;
['Qt5Widgets.dll', 'Qt5Core.dll', 'Qt5Gui.dll'].forEach(function(m) {
    var mod;
    try { mod = Process.getModuleByName(m); } catch (e) { return; }
    var hits = {};
    mod.enumerateExports().forEach(function(e) {
        for (var i = 0; i < want.length; i++) {
            if (e.name.indexOf(want[i]) >= 0) {
                hits[e.name] = (hits[e.name] || 0) + 1;
                break;
            }
        }
    });
    console.log('=== ' + m + ' (' + Object.keys(hits).length + ' hits) ===');
    Object.keys(hits).sort().forEach(function(n) { console.log('  ' + n); });
});
""" % str(KEYWORDS).replace("'", '"')

pid = frida.get_local_device().get_process("RobloxStudioBeta.exe").pid
session = frida.get_local_device().attach(pid)
script = session.create_script(SCRIPT)


def on_msg(msg, _data):
    if msg["type"] == "error":
        print("script error:", msg.get("description"))


script.on("message", on_msg)
script.load()
time.sleep(3)
session.detach()
