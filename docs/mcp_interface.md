# Roblox Studio MCP 接口文档

本文档描述本机 Roblox Studio（2026-08 版本目录 `version-dcbeee682ce74ee0`）内置
MCP 服务的工作方式与全部 26 个工具，供 `studio-hooks` 的 action 层及任何外部
脚本调用参考。信息来源：`StudioMCP.exe` 逆向（导出字符串/代理日志）、
`%LOCALAPPDATA%\StudioMCP\tools-cache.json` 工具缓存、实际握手抓包。

## 1. 架构

```
MCP 客户端(本框架 launcher / Claude 等)
      │  stdio, JSON-RPC (MCP 协议 2024-11-05)
      ▼
StudioMCP.exe  (代理, 随 Studio 安装)
      │  WebSocket  ws://127.0.0.1:13469/proxy  (端口可由环境变量
      │  MCP_PROXY_HTTP_PORT 覆盖)
      ▼
Roblox Studio 内置 MCP 客户端 (反向连接代理)
      │
      ▼
DataModel (Edit / Client / Server 三种 datamodel 可寻址)
```

要点：

- **Studio 是反向连接**：Studio 启动后主动连代理的 WS 端口。代理没起时 Studio
  会持续重试，代理先于 Studio 启动最可靠；Studio 先启动也最终会连上。
- **启用开关按账号存储**：`%LOCALAPPDATA%\Roblox\AssistantSettings\<userId>.json`
  中需要 `"mcp-server": {"enabled": true}`（默认缺失=关闭）。切换账号后如果
  突然连不上，先查这个文件。launcher 的 `ensure_mcp_enabled()` 会自动补全。
- 代理把 Studio 暴露的工具列表缓存到 `%LOCALAPPDATA%\StudioMCP\tools-cache.json`，
  Studio 未连接时 `tools/list` 也返回缓存。
- `StudioMCP.exe --help` 可用；`-v` 输出详细日志。

## 2. 握手流程（stdio JSON-RPC，换行分隔）

```jsonc
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
     "protocolVersion":"2024-11-05","capabilities":{},
     "clientInfo":{"name":"studio-hooks","version":"0.1"}}}
← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",
     "capabilities":{"tools":{"listChanged":true}},
     "serverInfo":{"name":"RobloxStudio","version":"1.0.0"}}}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}
→ {"jsonrpc":"2.0","id":2,"method":"tools/list"}
→ {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
     "name":"execute_luau","arguments":{"code":"return 1+1",
     "datamodel_type":"Edit","studio_id":"<uuid>"}}}
```

**任何工具调用前必须先 `tools/call list_roblox_studios`**（无参数）获取
`studio_id`。返回 `{"studios":[{"id":"...","name":"..."}]}`；Studio 未连接时
返回 `{"studios":[]}`，错误时 `isError:true` 文本提示 "Unable to reach..."。

## 3. 工具清单（26 个，`*` 为必填参数）

### 本框架核心使用

| 工具 | 参数 | 说明 |
|---|---|---|
| `list_roblox_studios` | — | 列出已连接 Studio 实例，取 `studio_id` |
| `execute_luau` | `code*`, `datamodel_type*`(Edit/Client/Server), `studio_id*` | 在 Studio 内执行 Luau，返回 return 值或错误文本。撤销记录需自行用 `ChangeHistoryService:TryBeginRecording/FinishRecording`（`SetWaypointAfterEditing` 已不存在） |
| `get_studio_state` | `studio_id*` | 当前播放状态与可用 datamodel |
| `start_stop_play` | `is_start*`, `studio_id*` | 进入/退出运行模式 |

### 实例与场景

| 工具 | 参数 | 说明 |
|---|---|---|
| `search_game_tree` | `datamodel_type*`, `studio_id*`, 可选 `path/instance_type/keywords/max_depth/head_limit` | 平铺 JSON 输出 DataModel 树，支持过滤 |
| `inspect_instance` | `path*`, `studio_id*` | 读取实例全部可读属性、属性表、子级摘要 |
| `insert_asset` | `assetId*`, `studio_id*`, 可选 `assetName/assetType/parentPath` | 按 ID 插入商城资产到场景 |
| `script_search` | `keywords*`, `studio_id*` | 模糊搜索脚本名（≤10 条，不支持通配） |
| `script_read` | `target_file*`, `studio_id*`, 可选行号范围 | 读脚本内容（带行号） |
| `script_grep` | `query*`, `studio_id*` | 全工程脚本内容正则搜索（≤50 条） |
| `multi_edit` | `edits*`(数组), `file_path*`, `datamodel_type*`, `studio_id*`, 可选 `className` | 批量编辑/新建脚本 |
| `get_console_output` | `studio_id*` | 读取输出窗口日志 |

### 输入模拟与截图

| 工具 | 参数 | 说明 |
|---|---|---|
| `user_mouse_input` | `actions*`(数组: moveTo/mouseButtonDown/mouseButtonUp/mouseButtonClick/scrollUp/scrollDown/wait), `datamodel_type*`, `studio_id*` | 模拟鼠标（支持 `instance_path` 定位） |
| `user_keyboard_input` | `actions*`(keyDown/keyUp/keyPress/textInput/wait), `datamodel_type*`, `studio_id*` | 模拟键盘 |
| `character_navigation` | `datamodel_type*`, `studio_id*`, 可选 `x/y/z/instance_path/speed_multiplier` | 导航角色到坐标或实例 |
| `screen_capture` | `capture_id*`, `studio_id*`, 可选 `camera_position/look_at_position` | 截取编辑视图画面（可临时摆相机） |

### AI 生成类

| 工具 | 参数 | 说明 |
|---|---|---|
| `generate_procedural_model` | `prompt*`, `studio_id*`, 可选 `attachedImageUri/partNames/segmentation` | 用基础图元生成模型 |
| `generate_mesh` | `textPrompt*`, `studio_id*`, 可选 `size/maxTriangles/partNames/segmentation` | AI 生成贴图网格 |
| `generate_material` | `baseMaterial*`, `materialDescription*`, `materialId*`, `materialPattern*`, `studio_id*` | 生成材质变体（返回 BaseMaterial+Name 用于 BasePart） |
| `segment_mesh` | `parts*`, `selectedInstanceRef*`(对象), `studio_id*` | 把网格按名字拆分为子部件模型 |
| `run_as_job` | `toolName*`, `arguments*`, `studio_id*` | 异步跑工具，立即返回 jobId |

### 资产与杂项

| 工具 | 参数 | 说明 |
|---|---|---|
| `search_asset` | `studio_id*` + 大量可选（`query/assetType/maxResults/...`） | 搜 Creator Store / 个人库存资产 |
| `upload_image` | `imagePaths*`(数组), `studio_id*` | 上传图片得 `rbxassetid://` |
| `store_image` | `filePath*`, `studio_id*` | 本地图片转 `IMAGEID_<id>` URI（供生成类工具） |
| `http_get` | `url*`, `studio_id*`, 可选 `query/return_full/context_lines` | 服务端代抓 URL |
| `skill` | `skill_name*`, `studio_id*` | 取 Roblox 官方技能知识库文档 |
| `subagent` | `description*`, `task*`, `subagent_type*`, `studio_id*` | 起受限子代理（explore 等） |

## 4. 已知坑

1. `datamodel_type` 不匹配当前模式（如未运行时选 Client/Server）会报错，
   先 `get_studio_state` 再选。
2. `execute_luau` 在 `AssistantCommand` 脚本上下文执行，错误输出也会进
   Output 窗口。
3. 本地 `.rbxl` 未保存的改动不受影响，MCP 操作走正常 ChangeHistory，可撤销。
4. 代理单实例：两个代理进程只有先起的能绑 13469，后起的 stdio 会话收不到
   任何 Studio 事件（表现为 studios 恒为 `[]`）。
