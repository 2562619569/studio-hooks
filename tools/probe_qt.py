#!/usr/bin/env python3
"""Standalone Qt API probe: attach to the running Studio and call
QApplication::focusWidget/activeWindow + objectName step by step,
printing every intermediate value to find where the AV comes from."""

import sys
import time

import frida

SCRIPT = r"""
function tryStep(name, fn) {
    try { var v = fn(); console.log('[ok] ' + name + ' -> ' + v); return v; }
    catch (e) { console.log('[ERR] ' + name + ' -> ' + e); return null; }
}

var W = 'Qt5Widgets.dll', C = 'Qt5Core.dll';
function exp(dll, name) { return Process.getModuleByName(dll).getExportByName(name); }
var fw = new NativeFunction(exp(W, '?focusWidget@QApplication@@SAPEAVQWidget@@XZ'), 'pointer', []);
var aw = new NativeFunction(exp(W, '?activeWindow@QApplication@@SAPEAVQWidget@@XZ'), 'pointer', []);
var qn = new NativeFunction(exp(C, '?objectName@QObject@@QEBA?AVQString@@XZ'), 'void', ['pointer', 'pointer']);
var qp = new NativeFunction(exp(C, '?parent@QObject@@QEBAPEAV1@XZ'), 'pointer', ['pointer']);

// how many Qt5 modules are loaded?
Process.enumerateModules().forEach(function(m) {
    if (m.name.indexOf('Qt5') >= 0) console.log('module: ' + m.name + ' @ ' + m.base + ' (' + m.path + ')');
});

var focus = tryStep('focusWidget()', function() { return fw(); });
var active = tryStep('activeWindow()', function() { return aw(); });
console.log('focus=' + focus + ' active=' + active);
var pt0 = Memory.alloc(8);
pt0.writeS32(960); pt0.add(4).writeS32(580);

function probeObj(tag, w) {
    if (!w || w.isNull()) { console.log(tag + ': null'); return; }
    var ret = Memory.alloc(64);
    tryStep(tag + '.objectName', function() {
        qn(ret, w);
        var d = ret.readPointer();
        var size = d.add(4).readS32();
        var off = d.add(16).readS64();
        return 'd=' + d + ' size=' + size + ' off=' + off + ' str=' + d.add(off).readUtf16String(size);
    });
    tryStep(tag + '.parent', function() { return qp(w); });
}

probeObj('focus', focus);
probeObj('active', active);

// Ground truth: disassemble the first instructions of each function.
// parent() is known-good (this=RCX, ret=RAX); compare against the
// by-value-returning ones to see which register they treat as this.
function disasm(tag, dll, sig) {
    try {
        var addr = exp(dll, sig);
        console.log('--- ' + tag + ' @ ' + addr);
        var p = addr;
        for (var i = 0; i < 8; i++) {
            var ins = Instruction.parse(p);
            console.log('   ' + ins);
            p = ins.next;
        }
    } catch (e) { console.log('disasm ' + tag + ' failed: ' + e); }
}
disasm('QObject::parent', C, '?parent@QObject@@QEBAPEAV1@XZ');
disasm('QObject::objectName', C, '?objectName@QObject@@QEBA?AVQString@@XZ');
disasm('QWidget::mapFromGlobal', W, '?mapFromGlobal@QWidget@@QEBA?AVQPoint@@AEBV2@@Z');
disasm('QApplication::focusWidget', W, '?focusWidget@QApplication@@SAPEAVQWidget@@XZ');

// This Qt build keeps `this` in RCX and passes the sret buffer in RDX
// (not the MSVC layout where sret takes RCX). Verify: (this, sret, ...).
var qn_ok = new NativeFunction(exp(C, '?objectName@QObject@@QEBA?AVQString@@XZ'), 'void', ['pointer', 'pointer']);
var mfg_ok = new NativeFunction(exp(W, '?mapFromGlobal@QWidget@@QEBA?AVQPoint@@AEBV2@@Z'), 'void', ['pointer', 'pointer', 'pointer']);
var outq = Memory.alloc(64), outp = Memory.alloc(16);
tryStep('objectName (this,sret) on active', function() {
    qn_ok(active, outq);
    var d = outq.readPointer();
    var size = d.add(4).readS32();
    var off = d.add(16).readS64();
    return 'd=' + d + ' size=' + size + ' str=' + d.add(off).readUtf16String(size);
});
tryStep('mapFromGlobal (this,sret,&pt) on active', function() {
    mfg_ok(active, outp, pt0);
    return '(' + outp.readS32() + ',' + outp.add(4).readS32() + ')';
});

// Hypothesis: this Qt build returns 8-byte values (QString, QPoint) in RAX,
// NOT via MSVC sret hidden pointer. Test both styles on objectName.
var qn_rax = new NativeFunction(exp(C, '?objectName@QObject@@QEBA?AVQString@@XZ'), 'pointer', ['pointer']);
tryStep('objectName RAX style on active', function() {
    var d = qn_rax(active);
    var size = d.add(4).readS32();
    var off = d.add(16).readS64();
    return 'd=' + d + ' size=' + size + ' off=' + off + ' str=' + d.add(off).readUtf16String(size);
});
var mfg_rax = new NativeFunction(exp(W, '?mapFromGlobal@QWidget@@QEBA?AVQPoint@@AEBV2@@Z'), 'uint64', ['pointer', 'pointer']);
tryStep('mapFromGlobal RAX style on active', function() {
    var packed = mfg_rax(active, pt0);
    var v = packed.valueOf();
    var x = v % 0x100000000, y = Math.floor(v / 0x100000000);
    if (x >= 0x80000000) x -= 0x100000000;
    if (y >= 0x80000000) y -= 0x100000000;
    return '(' + x + ',' + y + ')';
});

// walk the active window's childAt descent toward screen center
if (active && !active.isNull()) {
    var childAt = new NativeFunction(exp(W, '?childAt@QWidget@@QEBAPEAV1@AEBVQPoint@@@Z'), 'pointer', ['pointer', 'pointer']);
    var mfg = new NativeFunction(exp(W, '?mapFromGlobal@QWidget@@QEBA?AVQPoint@@AEBV2@@Z'), 'void', ['pointer', 'pointer', 'pointer']);
    var w = active;
    var pt = Memory.alloc(8), out = Memory.alloc(8);
    pt.writeS32(960); pt.add(4).writeS32(580);
    for (var i = 0; i < 20; i++) {
        var r = tryStep('descend[' + i + '] mapFromGlobal(w=' + w + ')', function() {
            mfg(out, w, pt);
            return '(' + out.readS32() + ',' + out.add(4).readS32() + ')';
        });
        if (r === null) break;
        pt.writeS32(out.readS32()); pt.add(4).writeS32(out.add(4).readS32());
        var child = tryStep('descend[' + i + '] childAt', function() { return childAt(w, pt); });
        if (!child || child.isNull()) break;
        probeObj('child[' + i + ']', child);
        w = child;
    }
}
"""

pid = frida.get_local_device().get_process("RobloxStudioBeta.exe").pid
session = frida.get_local_device().attach(pid)
script = session.create_script(SCRIPT)


def on_msg(msg, _data):
    if msg["type"] == "error":
        print("script error:", msg.get("description"))


script.on("message", on_msg)
script.load()
time.sleep(4)
session.detach()
