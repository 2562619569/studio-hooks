// ============================================================
// menu_engine.js — declarative context-menu system with area zones.
//
// Reads SH_CONFIG (injected by the launcher from config.json):
//   { entries: [{text, action, areas:[...]}],
//     areaZones: [{area, x:[x0,x1], y:[y0,y1]}],  // fractions of screen
//     debug: bool }
//
// Area detection: QMenu::exec(QPoint)/popup(QPoint) carry the global
// popup position; menus without one (e.g. exec()) fall back to the
// mouse cursor. The position is matched against configured screen
// zones — no native Qt calls, no hot-path hooks.
//
// Clicking an entry sends {event:'menu_trigger', action, area} to the
// launcher, which runs actions/<action>.lua via Studio MCP.
// ============================================================

(function () {
    if (SH.modules.menuEngine) return;
    SH.modules.menuEngine = true;

    var CFG = globalThis.SH_CONFIG || { entries: [], areaZones: [], debug: false };
    var W = 'Qt5Widgets.dll';

    var QMENU_EXEC   = '?exec@QMenu@@QEAAPEAVQAction@@AEBVQPoint@@PEAV2@@Z';
    var QMENU_EXEC2  = '?exec@QMenu@@QEAAPEAVQAction@@XZ';
    var QMENU_POPUP  = '?popup@QMenu@@QEAAXAEBVQPoint@@PEAVQAction@@@Z';
    var QMENU_ADDACT = '?addAction@QMenu@@QEAAPEAVQAction@@AEBVQString@@@Z';
    var addAction = SH.fn(W, QMENU_ADDACT, 'pointer', ['pointer', 'pointer']);
    var getCursorPos = SH.fn('user32.dll', 'GetCursorPos', 'int', ['pointer']);

    var screenWidth  = 0, screenHeight = 0;
    try {
        var gm = SH.fn('user32.dll', 'GetSystemMetrics', 'int', ['int']);
        screenWidth = gm(0); screenHeight = gm(1);
    } catch (e) { screenWidth = 2062; screenHeight = 1126; }

    function cursorPos() {
        var p = Memory.alloc(8);
        getCursorPos(p);
        return { x: p.readS32(), y: p.add(4).readS32() };
    }

    function classify(x, y) {
        if (!CFG.areaZones.length || !screenWidth) return 'other';
        var nx = x / screenWidth, ny = y / screenHeight;
        for (var i = 0; i < CFG.areaZones.length; i++) {
            var z = CFG.areaZones[i];
            if (nx >= z.x[0] && nx < z.x[1] && ny >= z.y[0] && ny < z.y[1])
                return z.area;
        }
        return 'other';
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
                if (CFG.debug)
                    SH.log('menu popup at (' + p.x + ',' + p.y + ')');
                inject(args[0], classify(p.x, p.y));
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
