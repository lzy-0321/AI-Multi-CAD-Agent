[English](README.md) | **中文**

# AI Multi-CAD Agent v0.2

面向现有 AI Agent 的本地 CAD 工具系统。Agent 理解自然语言；本项目提供配置、能力发现、MCP 调度、项目版本和验证。无需额外模型 API，也不内置聊天模型。

## 当前能力

- 用户独立配置与有限范围路径发现；可复用现有 Blender / SolidWorks stdio MCP。
- 统一 MCP 入口，按需搜索工具及读取参数 schema；持久连接、串行执行、结果摘要和本地日志。
- 已知只读操作最多重试一次；写操作不重放，超时或进程中断后需要检查实际状态并明确解除阻塞。
- 限定底板的参数化创建、孔径修改、版本文件与重开检查；不是任意文字建模算法。
- 原有 3MF 基础解析和 Blender 网格导出仍可使用。

SolidWorks 使用现成的 [HarrierPigeon MCP](https://github.com/HarrierPigeon/Solidworks-MCP-Server)，Blender 使用 [ahujasid MCP](https://github.com/ahujasid/mcp-for-blender)。本项目不重写它们的建模工具。可选 SW 兼容宿主增加精确验收查询、模板路径配置和尺寸弹窗处理，上游源码保持原样。

## 安装和配置

Windows、Python 3.11+、本机已安装并可正常启动的 CAD 软件。在源码根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\python.exe -m multi_cad setup
.\.venv\Scripts\python.exe -m multi_cad doctor
```

配置默认保存在 `%LOCALAPPDATA%\MultiCAD\config.json`，`MULTI_CAD_HOME` 可覆盖数据目录；`--config` 可覆盖配置文件位置。自动迁移当前目录的 `cad.local.json`，导入本项目旧 MCP 配置或用户已有 Codex 配置。发现不到或存在多个版本时才询问；无交互模式返回 `needs_input` 列表。失效的显式路径不会静默换成其他软件版本。

复用任意目录下的现成 MCP：

```powershell
python -m multi_cad setup --import-mcp "D:\settings\mcp.json" --blender-server blender --solidworks-server sw
```

输入可以是通用 `mcpServers` JSON 或 Codex TOML。已有本机 backend 配置优先保留；更换后端需明确编辑本机配置或调用安装命令。MCP 命令、参数数组、工作目录、环境变量独立于 CAD 软件路径。Blender 仅支持本机 loopback 连接，端口可配置。

缺少后端时，显式安装固定上游版本（需要网络和 Git）：

```powershell
python -m multi_cad install-backend blender
python -m multi_cad install-backend solidworks
```

每次安装使用新目录，保留旧环境和配置备份；来源提交及实际依赖清单保存在安装目录。Blender 还需安装并启用上游插件：运行新环境中的 `mcp-for-blender.exe install-addon`，在目标 Blender 偏好设置启用插件。多版本先用其 `addon-paths` 确认目标。已有安装不自动重装。

## 接入 Agent

使用安装本项目的 Python 执行：

```powershell
python -m multi_cad export-config "D:\settings\mcp.json"
python -m multi_cad export-config ".codex\config.toml" --format codex
python -m multi_cad doctor --live
```

导出只新增统一 `multi_cad` 服务，保留其他配置并备份；同名但不同设置报告冲突。重启 Agent 客户端后加载。日常只启用统一入口，旧的直接 CAD MCP 留作诊断，避免两个客户端同时修改同一个 CAD 会话。`doctor --live` 可能启动 CAD；未传 `--live` 不启动软件。已连接不等于建模已验证。

Codex 可在导出命令后添加 `--disable-server 旧服务名`（可重复指定），仅停用明确指定的直接服务并保留原设置；不会修改其他服务器。

Agent 使用说明：[工具调用与项目流程](docs/zh/agent-workflow.md)。首版支持 Windows 本地 stdio，提供 Codex TOML 和通用 JSON 配置，不保证每种客户端的配置文件布局相同。

## 参数化底板验收

底板 120 × 80 × 5 mm；四孔中心 (10,10)、(110,10)、(110,70)、(10,70) mm。高层配方只支持这个限定形状，其他任务由 Agent 搜索下游工具并规划。

使用已有 SW MCP 源码时，启用可选兼容宿主（当前 Python 必须已装上游依赖）：

```powershell
python -m multi_cad setup --use-sw-host "D:\MCP\Solidworks-MCP-Server" --part-template "D:\templates\Part.prtdot"
python -m multi_cad plate create "runs\plate" --hole-diameter 6
python -m multi_cad plate edit "runs\plate" --hole-diameter 8
python -m multi_cad plate verify "runs\plate"
```

每条命令可在新进程中执行。修改从已验证文件的工作副本开始，核对哈希、几何和完整参数映射；模糊映射会停止。新版本验证通过才登记。原版本不覆盖，失败文件另存并标记失败，不关用户其他文档。高层验收要求可选 `multi_cad_inspect_part` 能力；其他 MCP 可通过通用接口调用，但不能冒充通过此配方验收。

## 原有 3MF 流程与限制

```powershell
python -m multi_cad analyse "source.3mf" --project "runs\mesh" --goal "保留独立对象"
python -m multi_cad blender "runs\mesh" --executable "D:\Blender\blender.exe"
```

3MF mesh resource 是候选资源，不是已确认产品零件。Bambu/Orca 专属 plate、modifier、support 分类、材质纹理、通用参数化逆向、装配推断尚未实现。打印变换与真实装配位置分开保存。截图不能代替尺寸验证。

## 测试

```powershell
python -m unittest discover -v
```

测试需安装 `[mcp]` 依赖；协议测试使用假 MCP，不启动 CAD。实机验收单独执行上述底板流程。完整 schema 和日志留在本机缓存，查询结果默认截断并附文件引用。上下文体积报告使用字符/UTF-8 字节数，不冒称为实际模型 token 消耗。

本机验收与限制：[v0.2 验证记录](docs/zh/validation-v0.2.md)。安装包说明：[Windows 候选版安装指南](docs/zh/installation-quickstart.md)。产品需求：[需求文档 v2](docs/zh/requirements-v2.md)。
