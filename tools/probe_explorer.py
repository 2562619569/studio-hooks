#!/usr/bin/env python3
"""Probe #2: (a) hook every QMenu show path (exec/exec()/popup/event(Show))
to see which one the Explorer context menu takes; (b) grid-scan the main
window with childAt to find the Explorer widget's real screen coordinates."""

import time

import frida

SCRIPT = r"""
var W = 'Qt5Widgets.dll', C = 'Qt5Core.dll';
function exp(dll, name) { return Process.getModuleByName(dll).getExportByName(name); }
var qn_ok = new NativeFunction(exp(C, '?objectName@QObject@@QEBA?AVQString@@XZ'), 'void', ['pointer', 'pointer']);
var qp = new NativeFunction(exp(C, '?parent@QObject@@QEBAPEAV1@XZ'), 'pointer', ['pointer']);
var aw = new NativeFunction(exp(W, '?activeWindow@QApplication@@SAPEAVQWidget@@XZ'), 'pointer', []);
var mfg = new NativeFunction(exp(W, '?mapFromGlobal@QWidget@@QEBA?AVQPoint@@AEBV2@@Z'), 'void', ['pointer', 'pointer', 'pointer']);
var childAt = new NativeFunction(exp(W, '?childAt@QWidget@@QEBAPEAV1@AEBVQPoint@@@Z'), 'pointer', ['pointer', 'pointer']);

function objName(w) {
    var ret = Memory.alloc(8);
    qn_ok(w, ret);
    var d = ret.readPointer();
    var size = d.add(4).readS32();
    if (size < 0 || size > 512) return '?';
    return d.add(d.add(16).readS64()).readUtf16String(size);
}

// ---- (a) menu show paths --------------------------------------
function hook(sig, tag) {
    try {
        Interceptor.attach(exp(W, sig), {
            onEnter: function (args) { console.log('[path] ' + tag + ' menu=' + args[0] + ' name=' + objName(args[0])); }
        });
        console.log('hooked ' + tag);
    } catch (e) { console.log('hook ' + tag + ' failed: ' + e); }
}
hook('?exec@QMenu@@QEAAPEAVQAction@@AEBVQPoint@@PEAV2@@Z', 'exec(pos,at)');
hook('?exec@QMenu@@QEAAPEAVQAction@@XZ', 'exec()');
hook('?popup@QMenu@@QEAAXAEBVQPoint@@PEAVQAction@@@Z', 'popup(pos,at)');
hook('?event@QMenu@@QEAA_NPEAVQEvent@@@Z', 'QMenu::event');

// ---- (b) grid scan: unique deepest-widget names + sample position ----
var active = aw();
console.log('activeWindow=' + active + ' name=' + objName(active));
var pt = Memory.alloc(8), out = Memory.alloc(16);
var seen = {};
for (var gx = 0; gx < 2560; gx += 40) {
    for (var gy = 0; gy < 1440; gy += 40) {
        pt.writeS32(gx); pt.add(4).writeS32(gy);
        mfg(active, out, pt);
        pt.writeS32(out.readS32()); pt.add(4).writeS32(out.add(4).readS32());
        var child = childAt(active, pt);
        if (child.isNull()) continue;
        var n = objName(child);
        if (n && n !== '?' && !seen[n]) {
            seen[n] = 1;
            console.log('[scan] ' + n + ' @global(' + gx + ',' + gy + ')');
        }
    }
}
console.log('scan done');
"""

pid = frida.get_local_device().get_process("RobloxStudioBeta.exe").pid
session = frida.get_local_device().attach(pid)
script = session.create_script(SCRIPT)


def on_msg(msg, _data):
    if msg["type"] == "error":
        print("script error:", msg.get("description"))


script.on("message", on_msg)
script.load()
time.sleep(8)
session.detach()
