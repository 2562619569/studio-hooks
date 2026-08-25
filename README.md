# studio-hooks

Roblox Studio 原生 UI 的 Qt 层注入框架：向 Studio 的右键菜单注入自定义
功能项，并按右键区域（Explorer / 3D 视口 / 脚本编辑器…）显示不同条目。
点击后经 Studio 内置 MCP 通道执行 Luau，可以操作整个 DataModel。

不修改 Studio 二进制。所有 hook 落在标准 Qt 5.15 DLL 的导出符号上，
Studio 每周更新版本目录后无需改代码（launcher 运行时自动发现最新版本）。

## 架构

```
hooks/*.js (Frida, 进程内)                actions/*.lua (DataModel 内)
  QApplication::focusWidget → 识别右键区域    spawn_part / camera_info / ...
  QMenu::exec/popup  → 注入菜单条目                  ▲
        │ 点击                                       │ execute_luau (MCP)
        ▼                                            │
  send({menu_trigger/menu_show}) ──► studio_hooks.py ──► StudioMCP.exe 代理
                                    (spawn Studio + 持有代理 + 分发动作)
```

- **菜单层**（`hooks/menu_engine.js`）：声明式引擎。菜单弹出时取
  `QApplication::focusWidget()`——右键那一刻的焦点控件必然在目标面板内
  （Explorer 树 / 3D 视口 / 属性视图…），沿 `parent()` 链收集 `objectName`
  与 `areaRules` 正则匹配判定区域——面板拖动/浮动都不影响；弹出前注入
  匹配条目，点击后把返回值伪装成"未选择"，Studio 主程序无感知。
  每次右键同时上报 `menu_show` 事件，launcher 经 MCP `print` 到 Studio
  Output 窗口，区域判定结果实时可见。
- **动作层**（`actions/*.lua`）：每次调用时从磁盘读取，改 Lua 不用重启。
  脚本内可用 `HOOK_AREA` 变量获知触发区域。
- **MCP 层**：Studio 内置 MCP 客户端反向连接 `StudioMCP.exe` 代理
  （`ws://127.0.0.1:13469`），launcher 作为 MCP 客户端驱动。完整工具清单
  见 [docs/mcp_interface.md](docs/mcp_interface.md)。

## 使用

```bash
pip install frida

python studio_hooks.py                 # 启动 Studio(注入+MCP代理)
python studio_hooks.py --place x.rbxl  # 打开指定 place
python studio_hooks.py --watch         # 常驻守护:Studio 无论怎么启动都自动注入
python studio_hooks.py --attach        # 附加到已运行的 Studio
python studio_hooks.py --kill          # 结束 Studio
```

### 跟随 Studio 启动（watch 模式）

`--watch` 常驻运行：检测到 RobloxStudioBeta.exe 启动（双击、开始菜单、
命令行都一样）就自动 attach 注入并托管 MCP 代理，Studio 退出后回到扫描
状态，支持多个 Studio 先后启动。配合开机自启即可完全无感使用：

```bash
python tools/install_startup.py           # 登录时静默启动 watcher
python tools/install_startup.py --remove  # 取消自启
```

注意：watch 模式对**新**启动的 Studio 生效；watcher 启动前已经在跑的
Studio 不会被接管（避免与 spawn 模式双重注入）。

## 添加一个右键功能（30 秒）

1. 写动作 `actions/my_feature.lua`（Luau，返回值会进日志）：

```lua
return ("hello from %s, selected=%d"):format(HOOK_AREA, #game:GetService("Selection"):Get())
```

2. 在 `config.json` 的 `menuEntries` 加一行：

```json
{ "text": "✨ 我的功能", "action": "my_feature", "areas": ["explorer", "viewport"] }
```

3. 重启 Studio（`python studio_hooks.py --kill` 再启动）。完成。

`areas` 取值：`all` 或 `areaRules` 里定义的区域名。区域按"鼠标下控件的
objectName 链"识别，面板拖到哪都跟随；`debug: true` 时每次右键打印完整
objectName 链与判定结果，发现新面板时照着链上的名字加一条规则即可。

## 配置（config.json）

| 字段 | 说明 |
|---|---|
| `hooks` | 启用的 Frida 模块（`00_compat.js` 自动前置，勿手动加） |
| `menuEntries` | 右键菜单条目：`text` 显示文字 / `action` 对应 actions 文件名 / `areas` 生效区域 |
| `areaRules` | 区域规则：`area` 名称 + `match`（对右键处控件 objectName 链的正则） |
| `studioPath` / `studioArgs` | 覆盖自动发现的 Studio 路径 / 附加启动参数 |
| `debug` | true 时日志打印每次右键的 objectName 链与判定区域 |

## 添加新的 hook 模块（不限于菜单）

`hooks/` 下新建 `.js`（`menu_logger.js` 是最简示例），IIFE + `SH.modules`
防重复，用 `SH.fn(dll, mangled, ret, args)` 拿 NativeFunction、
`SH.makeQString()/SH.readQString()` 造/读 Qt 字符串，然后
`python studio_hooks.py --enable xxx.js`。

## 目录结构

```
studio_hooks.py   启动器：Frida 会话 + MCP 代理客户端 + 动作分发
config.json       菜单条目 / 区域规则 / 开关
hooks/            Frida 模块（00_compat 为共享兼容层）
actions/          Luau 动作脚本（按 action 名对应文件）
docs/mcp_interface.md   Studio MCP 26 个工具的接口文档
tools/mcp_probe.py      独立 MCP 探测脚本（调试用）
tools/check_exports.py  枚举 Qt DLL 导出符号（验证 mangled 名）
tools/probe_qt.py       独立 Qt API 探针（ABI/调用方式验证）
tools/probe_explorer.py 网格扫描各面板控件的真实屏幕坐标
tools/right_click.py    模拟右键/左键指定坐标（自动化测试）
tools/verify_copy.py    端到端验证「复制节点完整路径」（点击菜单→读剪贴板）
tools/install_startup.py 登录自启 watcher 的安装/卸载
tools/screenshot.py     全屏截图（配合视觉模型核验）
logs/             会话日志（gitignore）
```

## 已验证能力

- 向所有 `QMenu::exec/popup` 菜单注入条目、伪装返回值（Studio 无感知）
- 右键区域识别 + 按区域注入不同条目（实测：3D 视口=viewport、
  Explorer=explorer、其他面板=other，判定链见 Output）
- 视口专属：生成 Part、摄像机信息；Explorer 专属：统计选中对象、
  **复制节点完整路径**（`GetFullName()` → 系统剪贴板，多选每行一条）
- 右键时区域判定结果实时 `print` 到 Studio Output 窗口
- 菜单点击 → MCP `execute_luau` 在 Edit datamodel 执行任意 Luau
  （含 ChangeHistory 撤销记录）
- `--watch` 常驻：正常双击启动 Studio 即自动注入（含 Studio 周更后的
  新版本目录，hook 按 mtime 自动发现）

## Qt ABI 注意（重要）

Roblox 自带的 Qt5*.dll 虽是 MSVC 修饰名，但**按值返回的 8 字节对象
（QString/QPoint）走 `this=RCX, sret缓冲=RDX` 的布局**（Clang 风格，
不是 MSVC 的"sret 占 RCX"）。用 Frida 调这类函数时参数顺序必须是
`(this, 输出缓冲, 其余参数)`，已用反汇编验证（见 menu_engine.js 注释）。

## 注意

本地个人定制；注入客户端违反 Roblox ToS，勿用于生产/多人环境，账号风险
自负。Studio 若升级到 Qt6，符号名会变，需更新 hooks 里的 mangled 名单。
