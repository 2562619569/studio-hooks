# studio-hooks

Roblox Studio 原生 UI 的 Qt 层注入框架。不修改 Studio 二进制，通过 Frida
hook `Qt5Widgets.dll` 的导出符号（`QMenu::exec/popup/addAction` 等）实现
右键菜单增强、界面交互自定义等逻辑。

## 原理

- Studio 链接的是**标准 Qt 5.15 DLL（带完整导出符号）**，所有 hook 都落在
  Qt 层，与 223MB 的主程序无关 → Studio 每周更新版本目录后，符号名不变，
  框架继续可用（launcher 运行时自动发现最新 `version-*` 目录）。
- 兼容层（`hooks/00_compat.js`）提供 Qt5 对象构造/读取工具：
  - `SH.makeQString(text)`：手工构造不可变 `QString`（`{Data*}` + 24 字节
    `QArrayData` 头 + UTF-16 载荷）。
  - `SH.readQString(ptr)`、`SH.fn(dll, mangled, ret, args)`（NativeFunction
    缓存）、`SH.msgBox()`。

## 使用

```bash
pip install frida            # 依赖仅此一项

python studio_hooks.py                 # 启动 Studio 并注入
python studio_hooks.py --place x.rbxl  # 打开指定 place
python studio_hooks.py --attach        # 附加到已运行的 Studio
python studio_hooks.py --list          # 查看 hook 模块开关
python studio_hooks.py --enable menu_logger.js
python studio_hooks.py --disable context_menu_demo.js
python studio_hooks.py --kill          # 结束 Studio 进程
```

每次会话日志写入 `logs/session-*.log`（`console.log` / 脚本错误都会记录）。

## 编写新 hook 模块

在 `hooks/` 下新建 `.js`，遵循模板：

```js
(function () {
    if (SH.modules.myFeature) return;      // 防重复加载
    SH.modules.myFeature = true;

    var W = 'Qt5Widgets.dll';
    Interceptor.attach(
        Process.getModuleByName(W).getExportByName('?exec@QMenu@@QEAAPEAVQAction@@XZ'),
        { onEnter: function (args) { /* args[0] = QMenu* */ } });

    SH.log('module armed: myFeature');
})();
```

然后 `python studio_hooks.py --enable myFeature.js`。

查找目标符号：`objdump -p Qt5Widgets.dll` 或
`python -c "import pefile; ..."` 枚举导出表；常用目标：
`QMenu`（右键/下拉菜单）、`QMenuBar`、`QAction`、`QShortcut`、`QWidget::event`
（全局事件层）。`menu_logger.js` 可打印每个弹出菜单的标题，用来定位目标。

## 已验证能力（Windows x64, Qt 5.15）

- 向所有 `QMenu::exec/popup` 弹出的菜单注入自定义条目，点击后执行任意
  逻辑，并把返回值伪装成"未选择"，Studio 主程序无感知。

## 注意

- 属于本地个人定制；修改客户端/注入违反 Roblox ToS，不要用于发布内容
  的生产流程或多人协作环境，账号风险自负。
- Studio 大版本升级若换 Qt 主版本（Qt6），符号名会变，需要更新 mangled
  名单。
