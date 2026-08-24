// ============================================================
// 00_compat.js — shared runtime for all studio-hooks modules.
// Auto-prepended by the launcher; every hook script runs in the
// same JS context and uses the global namespace `SH`.
// ============================================================

var SH = globalThis.SH || {};
globalThis.SH = SH;

SH.modules = SH.modules || {};

// Cached NativeFunction factories keyed by dll!mangledName
SH.fns = SH.fns || {};

SH.fn = function (dll, mangled, ret, args) {
    var key = dll + '!' + mangled;
    if (!SH.fns[key]) {
        var addr = Process.getModuleByName(dll).getExportByName(mangled);
        SH.fns[key] = new NativeFunction(addr, ret, args);
    }
    return SH.fns[key];
};

// ---- Qt 5 QString construction (immutable, ref = -1) ----------
// QString object = { Data* } (8 bytes).
// Data = QArrayData header (24 bytes on x64: ref@0, size@4,
// alloc-bitfield@8, pad@12, offset@16) + UTF-16 payload.
SH.keepAlive = SH.keepAlive || [];

SH.makeQString = function (text) {
    var units = [];
    for (var i = 0; i < text.length; i++) units.push(text.charCodeAt(i));
    var data = Memory.alloc(24 + (units.length + 1) * 2);
    data.writeS32(-1);                       // ref: static, never freed
    data.add(4).writeS32(units.length);      // size
    data.add(8).writeU32(0);                 // alloc / capacityReserved
    data.add(16).writeS64(24);               // offset to char payload
    for (var i = 0; i < units.length; i++)
        data.add(24 + i * 2).writeU16(units[i]);
    data.add(24 + units.length * 2).writeU16(0);
    var strObj = Memory.alloc(8);
    strObj.writePointer(data);
    SH.keepAlive.push(data, strObj);
    return strObj;
};

// Read a QString* into a JS string (owned heap strings only).
SH.readQString = function (strObj) {
    try {
        var d = strObj.readPointer();
        var size = d.add(4).readS32();
        var offset = d.add(16).readS64();
        if (size < 0 || size > 4096) return '<invalid>';
        return d.add(offset).readUtf16String(size);
    } catch (e) { return '<unreadable>'; }
};

// ---- Windows helpers ------------------------------------------
SH.msgBox = function (text, caption) {
    var MessageBoxW = SH.fn('user32.dll', 'MessageBoxW', 'int',
        ['pointer', 'pointer', 'pointer', 'uint32']);
    MessageBoxW(ptr(0), SH.makeQString(text), SH.makeQString(caption || 'studio-hooks'), 0x40);
};

SH.log = function (msg) { console.log('[SH] ' + msg); };
