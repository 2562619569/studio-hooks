# studio-hooks

Roblox Studio 原生 UI 的 Qt 层注入框架：向 Studio 的右键菜单注入自定义
功能项，并按右键区域（Explorer / 3D 视口 / 脚本编辑器…）显示不同条目。
点击后经 Studio 内置 MCP 通道执行 Luau，可以操作整个 DataModel。

不修改 Studio 二进制。所有 hook 落在标准 Qt 5.15 DLL 的导出符号上，
Studio 每周更新版本目录后无需改代码（launcher 运行时自动发现最新版本）。

## 架构

```
hooks/*.js (Frida, 进程内)                actions/*.lua (DataModel 内)
  QApplication::notify → 识别右键区域          spawn_part / camera_info / ...
  QMenu::exec/popup  → 注入菜单条目                  ▲
        │ 点击                                       │ execute_luau (MCP)
        ▼                                            │
  send({menu_trigger, action, area}) ──► studio_hooks.py ──► StudioMCP.exe 代理
                                        (spawn Studio + 持有代理 + 分发动作)
```

- **菜单层**（`hooks/menu_engine.js`）：声明式引擎。`QMenu::exec/popup`
  弹出时的全局坐标与 `areaZones` 屏幕分区比对判定区域（Explorer/3D 视口
  等，零原生调用、不碰热点函数）；弹出前注入匹配条目，点击后把返回值
  伪装成"未选择"，Studio 主程序无感知。
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
python studio_hooks.py --attach        # 附加到已运行的 Studio
python studio_hooks.py --kill          # 结束 Studio
```

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

`areas` 取值：`all` 或 `areaZones` 里定义的区域名。区域是主屏上的矩形
分区（`x`/`y` 为屏幕宽高的比例），把 Studio 各面板的位置圈出来即可；
`debug: true` 时每次右键会打印弹出坐标和判定区域，方便校准分区。

## 配置（config.json）

| 字段 | 说明 |
|---|---|
| `hooks` | 启用的 Frida 模块（`00_compat.js` 自动前置，勿手动加） |
| `menuEntries` | 右键菜单条目：`text` 显示文字 / `action` 对应 actions 文件名 / `areas` 生效区域 |
| `areaZones` | 区域分区：`area` 名称 + `x`/`y` 两个元素的屏幕比例区间 |
| `studioPath` / `studioArgs` | 覆盖自动发现的 Studio 路径 / 附加启动参数 |
| `debug` | true 时日志打印每次右键的弹出坐标与区域（校准分区用） |

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
logs/             会话日志（gitignore）
```

## 已验证能力

- 向所有 `QMenu::exec/popup` 菜单注入条目、伪装返回值（Studio 无感知）
- 右键区域识别 + 按区域注入不同条目
- 菜单点击 → MCP `execute_luau` 在 Edit datamodel 执行任意 Luau
  （含 ChangeHistory 撤销记录）

## 注意

本地个人定制；注入客户端违反 Roblox ToS，勿用于生产/多人环境，账号风险
自负。Studio 若升级到 Qt6，符号名会变，需更新 hooks 里的 mangled 名单。
