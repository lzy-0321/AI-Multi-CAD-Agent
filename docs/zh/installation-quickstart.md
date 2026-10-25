[English](../installation-quickstart.md) | **中文**

# Multi-CAD Windows 安装指南

需要 Windows、64 位 Python 3.11+；实际建模还需要本机可用且已授权的 CAD。安装过程联网下载 Python 依赖，不捆绑 CAD、许可证或模型 API。第二台电脑的 CAD 实测尚未完成。

## 安装程序

解压 ZIP，在其目录执行（无需管理员权限）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
# 自定义目录和 Python：
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -InstallDir "D:\工具\Multi CAD" -Python "C:\Python314\python.exe"
```

安装器创建独立环境、联网安装依赖，并通过网关 MCP 握手后才切换活动版本。不启动 CAD、不创建零件。默认目录为 `%LOCALAPPDATA%\MultiCAD`。失败详情在新版本目录的 `install.log`，已有入口保持有效。缺少 Python 时，请从 https://www.python.org/downloads/windows/ 安装 64 位 Python 后重试。

## 配置 CAD 和现成 MCP

以下命令在安装目录执行。`launch.ps1` 始终使用当前成功安装的版本；可从任意工作目录以绝对路径调用。

```powershell
.\launch.ps1 setup
.\launch.ps1 doctor --report .\diagnosis.json
.\launch.ps1 export-config "D:\Agent settings\mcp.json"
# Codex 配置用 --format codex：
.\launch.ps1 export-config "D:\项目\.codex\config.toml" --format codex
```

向导优先复用已有路径和 MCP。缺失或有多个版本才询问。可导入现成 MCP 配置：

```powershell
.\launch.ps1 setup --import-mcp "D:\settings\mcp.json" --solidworks-server my-sw --blender-server my-blender
```

若没有 MCP，可明确选择安装固定上游版本（需要 Git 和网络）：

```powershell
.\launch.ps1 install-backend solidworks
.\launch.ps1 install-backend blender
```

上游来源与固定提交写在 ZIP 的 `release.json`。成功安装且握手工具检查通过才保存后端配置。SolidWorks 使用随包 wheel 提供的兼容宿主，无需源码目录。Blender 还需在所选版本中安装、启用插件：使用安装结果目录下 `venv\Scripts\mcp-for-blender.exe addon-paths` 查看目标，运行该工具的 `install-addon --help` 按上游选项指定目标。不要仅因另一个 Blender 版本中已安装插件就标记配置完成。

导出只合并统一服务，不覆盖其他服务；遇到不同的同名 `multi_cad` 条目会停止并提示冲突。旧源码版入口需要用户显式移除该单个条目再导出；不要删除整个 Agent 配置。加载新入口后重启 Agent，日常仅启用统一网关。

## 修复和诊断

```powershell
.\launch.ps1 setup --repair
# 自动化先预览，确认后添加 --apply：
.\launch.ps1 setup --repair --non-interactive --solidworks "F:\solidworks\SOLIDWORKS\SLDWORKS.exe"
.\launch.ps1 setup --repair --non-interactive --solidworks "F:\solidworks\SOLIDWORKS\SLDWORKS.exe" --apply
.\launch.ps1 doctor --live --report .\diagnosis-live.json
```

修复不自动选择另一个 CAD 版本；更换已有 MCP 时须指定导入条目。命令、参数数组和工作目录可分别配置。修复前显示字段变更摘要，保存时备份；配置目录下的 `.bak` 可能包含本机环境信息，请勿直接分享。

`doctor` 不启动 CAD；`--live` 会调用 CAD，可能启动软件。报告区分安装、COM 注册、MCP 连接、CAD 可调用、历史业务验收。历史记录包含时间及配置匹配情况，不代表当前连接健康。报告不包含环境变量值、完整命令参数、原始错误或模型内容。原始错误在本机 `cache\*-stderr.log`，分享前自行检查。

Blender 无法调用时，检查目标版本插件是否启用及 localhost 端口是否一致。SW 注册不匹配时，选择已注册安装或使用软件自身的注册修复方式。写入超时应先检查实际模型状态，再由 Agent 使用 `reconcile_write` 记录证据，禁止直接重放建模操作。

## 显式建模验收

配置 SolidWorks 的有效零件模板；已有上游源码可使用：

```powershell
.\launch.ps1 setup --repair --use-sw-host "D:\MCP\Solidworks-MCP-Server" --part-template "D:\templates\Part.prtdot"
.\launch.ps1 plate create "D:\CAD projects\验收底板" --hole-diameter 6
.\launch.ps1 plate edit "D:\CAD projects\验收底板" --hole-diameter 8
.\launch.ps1 plate verify "D:\CAD projects\验收底板"
```

也可以通过 Agent 的 `plate_workflow` 完成相同流程。验收只覆盖 120×80×5 mm、四孔距边 10 mm 的限定底板。不要同时启动多个客户端修改同一 CAD 会话。

## 升级与回滚

新 ZIP 对同一安装目录运行 `install.ps1`。安装器保留旧环境，在激活前备份本机配置，Agent 仍指向固定 `launch.ps1`。升级后重启 Agent。

```powershell
.\launch.ps1 rollback
```

回滚恢复上一成功程序版本及升级前配置，并备份回滚前配置；无旧配置快照时保留现有配置。不会删除或回退 CAD 工程文件。首次安装没有可回滚版本。暂不自动清理旧版本，避免删除仍被 MCP 引用的环境。
