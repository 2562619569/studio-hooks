// ============================================================
// context_menu_demo.js — append a custom entry to every QMenu
// (context menus, ribbon dropdowns). Proof of concept for the
// Qt-layer injection framework.
// ============================================================

(function () {
    if (SH.modules.contextMenuDemo) return;
    SH.modules.contextMenuDemo = true;

    var W = 'Qt5Widgets.dll';
    var QMENU_EXEC   = '?exec@QMenu@@QEAAPEAVQAction@@AEBVQPoint@@PEAV2@@Z';
    var QMENU_EXEC2  = '?exec@QMenu@@QEAAPEAVQAction@@XZ';
    var QMENU_POPUP  = '?popup@QMenu@@QEAAXAEBVQPoint@@PEAVQAction@@@Z';
    var QMENU_ADDACT = '?addAction@QMenu@@QEAAPEAVQAction@@AEBVQString@@@Z';

    var myActions = new Set();

    function inject(menu) {
        if (menu.isNull()) return;
        try {
            var act = SH.fn(W, QMENU_ADDACT, 'pointer', ['pointer', 'pointer'])(
                menu, SH.makeQString('⚡ 自定义菜单项 (hook注入)'));
            myActions.add(act.toString());
            SH.log('injected action into QMenu @' + menu);
        } catch (e) {
            SH.log('inject failed: ' + e);
        }
    }

    [QMENU_EXEC, QMENU_EXEC2, QMENU_POPUP].forEach(function (sig) {
        Interceptor.attach(Process.getModuleByName(W).getExportByName(sig), {
            onEnter: function (args) { inject(args[0]); }
        });
    });

    // If our entry was chosen: run custom logic, then make Studio see
    // "nothing selected" so native handlers stay untouched.
    [QMENU_EXEC, QMENU_EXEC2].forEach(function (sig) {
        Interceptor.attach(Process.getModuleByName(W).getExportByName(sig), {
            onLeave: function (retval) {
                if (!retval.isNull() && myActions.has(retval.toString())) {
                    SH.msgBox(
                        '你点击了注入的自定义菜单项!\n' +
                        '这一层完全在 Qt5Widgets.dll 上 hook, 未改动 Studio 二进制。',
                        'studio-hooks');
                    retval.replace(ptr(0));
                }
            }
        });
    });

    SH.log('module armed: context_menu_demo');
})();
