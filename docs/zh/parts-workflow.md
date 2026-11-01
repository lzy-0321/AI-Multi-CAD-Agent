[English](../parts-workflow.md) | **中文**

# 按 part 局部修改（0.4.0）

通过现有 Agent 使用统一网关。以 `backend="project"`、关键词 `parts` 搜索能力，再按需获取操作 schema。MCP 仍保持八个入口，不需要另配模型 API。

## 使用流程

1. `parts_import`：提供源 3MF、新项目目录和用户目标。复制并校验原文件，保留切片名称、打印板归属、源类型和资源实例。网格不自动等于真实产品零件。
2. `parts_list`：分页查询简短对象记录。`parts_detail` 返回源尺寸、网格质量及形状分析；`parts_preview` 生成本地 PNG。详情明确描述原始来源，不把它当作后续修改版本的尺寸。
3. 选择明确 ID，重名时消除歧义。`scope` 必须为 `instance` 或 `all_instances`；后者指共享同一源资源的实例，不自动包括几何相似的独立资源。不猜测用户要改一个还是全部。
4. `parts_plan`：传入编辑要求，查看路线、几何依据、限制和关联切除体。缺少尺寸或目标含糊时集中询问。
5. `parts_edit`：执行选定对象。一次多目标编辑在项目层面整体提交；多条独立网关调用不构成一个事务。同一批次对目标执行相同修改，不同修改分别形成版本。
6. `parts_verify`：在隔离副本中重开 Blender 和已有 SW 原生文件，检查保存的几何、位置、尺寸与映射。`parts_export` 按毫米导出选中的已解析产品实体 STL。打印位置与未知装配位置分开保留。

## 支持的修改与路由

| 操作 | 参数 | 执行方式 |
|---|---|---|
| `translate` | `delta_mm` 向量 | Blender 世界坐标移动 |
| `scale` | 正数 `factors`、`pivot_mm` | Blender 世界坐标缩放；对应轴的全部特征尺寸都会变化 |
| `cut_cylinder` | `center_mm`、单位向量 `axis`、`diameter_mm`、`depth_mm` | 可编辑 Blender 布尔，检查切孔结果与封闭性 |
| `resize_negative` | `diameter_mm` | 已识别圆柱负体积；按世界坐标毫米调整孔径，并检查所属产品 |
| `set_parameters` | `thickness_mm` 和／或 `diameter_mm` | SW 平板／垫圈重建，或修改持久化原生参数 |

机械参数修改要求源网格封闭、方向一致，且为两个匹配平面端盖的轴对齐平板或垫圈。圆拟合与弦误差必须满足项目容差，默认 0.05 mm。改孔径目前要求唯一已识别孔；多个直通圆孔可以在修改厚度时一同重建。任意朝向、阶梯、曲面、筋板或未解析的源布尔实体会拒绝 SW 重建，不属于通用逆向。

复杂网格由 Blender 执行明确支持的操作。用户要求参数化时不静默降级成网格。源负体积保留为可编辑切除体，不作为产品实体导出。产品移动／缩放会携带归属明确的源切除体，计划中列出关联对象。未知类型和含多个产品的歧义布尔组阻止修改或导出；非流形结果拒绝通过。Blender 5.2 支持且网格适用时使用流形布尔求解器，否则使用精确求解器，结果仍须通过检查。

重建后以 SW 原生文件为主，STL 仅作为场景预览，并检查单位与规范坐标边界。高层 Blender 路线拒绝修改该派生预览。已在 Blender 改过的对象转入 SW 也需要重新分析当前几何；本版尚未自动重新分析任意已编辑网格。

## 执行、文件与恢复

通过配置的 Blender MCP 启动独立后台 Blender worker，不会把工程加载到用户当前场景。这要求上游 `execute_blender_code` 允许启动子进程。安全模式拒绝时会报告，本项目不会关闭或绕过安全模式。编辑前需要启动对应 Blender 及 MCP 插件。

SW 复用现有兼容宿主、已配置的零件模板和上游草图／特征工具。只关闭本次拥有的工作副本，并恢复此前活动文档。小草图在上游坐标选择前自动缩放视图。

项目状态保存相对工程引用、源／清单／工程哈希、选中及关联 ID、测量几何、用户修改、原生参数映射、验证与不可覆盖版本。大型网格、报告和完整日志保留本地。每次从副本开始，重开通过后才登记。批次失败不改变上一成功状态，并保存本地失败报告。写入超时先检查实际状态，再解除阻塞；不自动重放写操作。

`parts_upgrade` 会先备份旧网格项目状态与清单，再重新分析，不冒充旧对象映射已被核验。已有版本记录的项目不静默迁移。

CLI 自动化可将参数写入 UTF-8 JSON 文件后执行：

```powershell
python -m multi_cad parts parts_import --arguments import.json
python -m multi_cad parts parts_list --arguments list.json
python -m multi_cad parts parts_plan --arguments edit.json
python -m multi_cad parts parts_edit --arguments edit.json
python -m multi_cad parts parts_verify --arguments selection.json
python -m multi_cad parts parts_export --arguments selection.json
```

选择实际 ID 后，`edit.json` 示例：

```json
{"project":"D:/CAD/my-project","targets":["part-ID-from-parts_list"],"scope":"instance","edit":{"operation":"set_parameters","diameter_mm":12}}
```

输出为 `.blend`、选定 `.SLDPRT` 及可选 STL，不回写切片 3MF 设置。本轮不包含自动装配、任意雕刻、图片重建与异机验证。
