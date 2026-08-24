// ============================================================
// menu_logger.js — log every QMenu as it opens (title + address).
// Useful for discovering which menus to target with new hooks.
// ============================================================

(function () {
    if (SH.modules.menuLogger) return;
    SH.modules.menuLogger = true;

    var W = 'Qt5Widgets.dll';
    var QMENU_TITLE = '?title@QMenu@@QEBA?AVQString@@XZ';   // QString title() const
    var qmenuTitle = SH.fn(W, QMENU_TITLE, 'void', ['pointer', 'pointer']); // sret: rcx=ret, rdx=this

    function menuTitle(menu) {
        try {
            var ret = Memory.alloc(8);
            qmenuTitle(ret, menu);
            var t = SH.readQString(ret);
            return t.length ? t : '(untitled)';
        } catch (e) { return '(?)'; }
    }

    ['?exec@QMenu@@QEAAPEAVQAction@@AEBVQPoint@@PEAV2@@Z',
     '?exec@QMenu@@QEAAPEAVQAction@@XZ',
     '?popup@QMenu@@QEAAXAEBVQPoint@@PEAVQAction@@@Z'
    ].forEach(function (sig) {
        Interceptor.attach(Process.getModuleByName(W).getExportByName(sig), {
            onEnter: function (args) {
                if (!args[0].isNull())
                    SH.log('menu opened @' + args[0] + ' — ' + menuTitle(args[0]));
            }
        });
    });

    SH.log('module armed: menu_logger');
})();
