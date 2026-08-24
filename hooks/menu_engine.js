// ============================================================
// menu_engine.js — declarative context-menu system (identity based).
//
// Reads SH_CONFIG (injected by the launcher from config.json):
//   { entries: [{text, action, areas:[...]}],
//     areaRules: [{area, match}],   // regex against objectName chain
//     debug: bool }
//
// Area detection: when a QMenu is about to show, the widget that had focus
// (QApplication::focusWidget) is the panel the user right-clicked — its
// ancestor objectNames are matched against areaRules. Fallbacks:
// activeWindow + childAt descent, then the menu's own parent chain.
// Works no matter where panels are docked or floated. Only runs on menu
// show (human pace), never on hot paths.
//
// Clicking an entry sends {event:'menu_trigger', action, area} to the
// launcher, which runs actions/<action>.lua via Studio MCP.
//
// Every menu popup also sends {event:'menu_show', area, chain, x, y};
// the launcher prints the classification to Studio's Output window via
// execute_luau, so right-clicking anywhere shows the detected area live.
// ============================================================

(function () {
    if (SH.modules.menuEngine) return;
    SH.modules.menuEngine = true;

    var CFG = globalThis.SH_CONFIG || { entries: [], areaRules: [], debug: false };
    var W = 'Qt5Widgets.dll', CORE = 'Qt5Core.dll';

    var QMENU_EXEC   = '?exec@QMenu@@QEAAPEAVQAction@@AEBVQPoint@@PEAV2@@Z';
    var QMENU_EXEC2  = '?exec@QMenu@@QEAAPEAVQAction@@XZ';
    var QMENU_POPUP  = '?popup@QMenu@@QEAAXAEBVQPoint@@PEAVQAction@@@Z';
    var QMENU_ADDACT = '?addAction@QMenu@@QEAAPEAVQAction@@AEBVQString@@@Z';

    var qParent    = SH.fn(CORE, '?parent@QObject@@QEBAPEAV1@XZ', 'pointer', ['pointer']);
    var wParentW   = SH.fn(W, '?parentWidget@QWidget@@QEBAPEAV1@XZ', 'pointer', ['pointer']);
    var qObjName   = SH.fn(CORE, '?objectName@QObject@@QEBA?AVQString@@XZ', 'void', ['pointer', 'pointer']);
    // Static QApplication accessors — the focus widget IS the widget under
    // the right-click (Explorer tree / viewport / properties view), and both
    // are guaranteed real QWidgets. Far safer than walking a QMenu's parent
    // chain: parentWidget() does an unchecked static_cast, so a QMenu owned
    // by a QAction yields a fake "QWidget" that AVs on any QWidget API call.
    var appFocus   = SH.fn(W, '?focusWidget@QApplication@@SAPEAVQWidget@@XZ', 'pointer', []);
    var appActive  = SH.fn(W, '?activeWindow@QApplication@@SAPEAVQWidget@@XZ', 'pointer', []);
    var qStrDtor   = SH.fn(CORE, '??1QString@@QEAA@XZ', 'void', ['pointer']);
    var wChildAt   = SH.fn(W, '?childAt@QWidget@@QEBAPEAV1@AEBVQPoint@@@Z', 'pointer', ['pointer', 'pointer']);
    // This Qt build keeps `this` in RCX and passes sret return buffers in
    // RDX (Clang-style, NOT the MSVC layout where sret takes RCX). Verified
    // by disassembly: objectName reads its d-pointer from [rcx+8]. All
    // by-value 8-byte returns here follow (this, sret, args...) ordering.
    var wMapFromG  = SH.fn(W, '?mapFromGlobal@QWidget@@QEBA?AVQPoint@@AEBV2@@Z',
                           'void', ['pointer', 'pointer', 'pointer']);
    var addAction  = SH.fn(W, QMENU_ADDACT, 'pointer', ['pointer', 'pointer']);
    var getCursorPos = SH.fn('user32.dll', 'GetCursorPos', 'int', ['pointer']);

    function cursorPos() {
        var p = Memory.alloc(8);
        getCursorPos(p);
        return { x: p.readS32(), y: p.add(4).readS32() };
    }

    function objName(w) {
        var ret = Memory.alloc(8);
        qObjName(w, ret);              // (this, sret) — this first, see ABI note
        var s = SH.readQString(ret);
        try { qStrDtor(ret); } catch (e) { /* static QString: dtor is a no-op */ }
        return s;
    }

    // Walk QWidget::parentWidget(), NOT QObject::parent(): a QMenu's QObject
    // parent can be a QAction (non-widget), and calling QWidget APIs like
    // mapFromGlobal on it null-derefs inside Qt (observed 0xc0000005 at 0x0).
    function topLevelOf(w) {
        for (var i = 0; i < 64; i++) {
            var p = wParentW(w);
            if (!p || p.isNull()) return w;
            w = p;
        }
        return w;
    }

    function deepChildAt(top, x, y) {
        var w = top;
        var pt = Memory.alloc(8);
        var out = Memory.alloc(8);
        for (var i = 0; i < 40; i++) {
            try {
                pt.writeS32(x); pt.add(4).writeS32(y);
                wMapFromG(w, out, pt);        // (this, sret, &globalPos)
                pt.writeS32(out.readS32()); pt.add(4).writeS32(out.add(4).readS32());
                var child = wChildAt(w, pt);
                if (child.isNull()) break;
                w = child;
            } catch (e) {
                SH.log('deepChildAt step ' + i + ' failed (w=' + w + '): ' + e);
                break;   // keep the deepest widget found so far
            }
        }
        return w;
    }

    function nameChain(w) {
        var names = [];
        for (var i = 0; w && !w.isNull() && i < 30; i++) {
            var n = objName(w);
            if (n && n.length) names.push(n);
            w = qParent(w);
        }
        return names;
    }

    // Returns {area, chain}; area='error' if detection blew up (still
    // reported so the launcher can print the failure to Studio Output).
    //
    // Target resolution, most reliable first:
    //   1. QApplication::focusWidget() — the focused widget at right-click
    //      time lives in the clicked panel (tree, viewport, properties).
    //   2. QApplication::activeWindow() + childAt descent on the popup point.
    //   3. The menu's own parentWidget() chain (may be bogus, last resort).
    function classify(menu, x, y) {
        var stage = 'focusWidget';
        try {
            var w = appFocus();
            if (!w || w.isNull()) {
                stage = 'activeWindow';
                w = appActive();
            }
            if (w && !w.isNull()) {
                var chain = nameChain(w);
                return matchArea(chain);
            }
            stage = 'topLevelOf+deepChildAt';
            var top = topLevelOf(menu);
            var deep = deepChildAt(top, x, y);
            return matchArea(nameChain(deep));
        } catch (e) {
            SH.log('classify failed at [' + stage + ']: ' + e);
            return { area: 'error', chain: '<failed at ' + stage + '>' };
        }
    }

    function matchArea(chain) {
        var hay = chain.join(' / ');
        for (var i = 0; i < CFG.areaRules.length; i++) {
            var r = CFG.areaRules[i];
            if (new RegExp(r.match, 'i').test(hay)) {
                SH.log('area=' + r.area + ' via chain: ' + hay);
                return { area: r.area, chain: hay };
            }
        }
        SH.log('area=other, chain: ' + hay);
        return { area: 'other', chain: hay };
    }

    // ---- menu injection ------------------------------------------
    var myActions = {};   // QAction ptr -> {action, area}

    function entriesFor(area) {
        var out = [];
        for (var i = 0; i < CFG.entries.length; i++) {
            var e = CFG.entries[i];
            var areas = e.areas && e.areas.length ? e.areas : ['all'];
            if (areas.indexOf('all') >= 0 || areas.indexOf(area) >= 0)
                out.push(e);
        }
        return out;
    }

    function inject(menu, area) {
        var entries = entriesFor(area);
        if (!entries.length) return;
        for (var i = 0; i < entries.length; i++) {
            try {
                var act = addAction(menu, SH.makeQString(entries[i].text));
                myActions[act.toString()] = { action: entries[i].action, area: area };
            } catch (e) {
                SH.log('inject failed: ' + e);
            }
        }
        SH.log('menu @' + menu + ' area=' + area + ' +' + entries.length + ' item(s)');
    }

    function showWithPos(sig, hasPos) {
        Interceptor.attach(Process.getModuleByName(W).getExportByName(sig), {
            onEnter: function (args) {
                var p = hasPos
                    ? { x: args[1].readS32(), y: args[1].add(4).readS32() }  // QPoint
                    : cursorPos();
                var cls = classify(args[0], p.x, p.y);
                inject(args[0], cls.area);
                send({ event: 'menu_show', area: cls.area, chain: cls.chain,
                       x: p.x, y: p.y });
            }
        });
    }
    showWithPos(QMENU_EXEC, true);
    showWithPos(QMENU_POPUP, true);
    showWithPos(QMENU_EXEC2, false);

    [QMENU_EXEC, QMENU_EXEC2].forEach(function (sig) {
        Interceptor.attach(Process.getModuleByName(W).getExportByName(sig), {
            onLeave: function (retval) {
                var hit = myActions[retval.toString()];
                if (hit) {
                    retval.replace(ptr(0));   // Studio sees "nothing selected"
                    send({ event: 'menu_trigger', action: hit.action, area: hit.area });
                    SH.log('menu_trigger dispatched: ' + hit.action + ' (area=' + hit.area + ')');
                }
            }
        });
    });

    SH.log('module armed: menu_engine (' + CFG.entries.length + ' entries)');
})();
