# 独立工具与生产输入

包内工具独立运行，不读取旧 Skill 安装目录。基线 Python 3.12；图像工具用 Pillow／NumPy，模型预览另需 ModernGL 及 OpenGL 3.3；Composa 客户端只用标准库。准确版本、脚本哈希和固定外部 texconv 身份见 [toolkit-lock.json](../toolkit-lock.json)。源仓库由 catalog 装配这些文件，通用工具单处维护，不随每个车型复制。

## 可编辑任务书

```text
python -B scripts/layout_brief.py create --family t-90 --theme ENDFIELD --number EF10 --out NEW_BRIEF.json
python -B scripts/layout_brief.py create --family type-99 --theme ENDFIELD --number EF11 --weathering none --surface-grain none --preset F02 --out ANOTHER_BRIEF.json
python -B scripts/layout_brief.py check BRIEF.json
```

family 为 `leopard-2|t-80|t-90|type-99|leclerc`，其中 t-90 明确指 T-90M，type-99 当前是无后油桶 99A。默认自由构图、`preset=null`、`weathering=none`，未确认漆面纹理时 `surface_grain=none`；可按已检查的材料选择 subtle。主题、编号和普通辅助文字可改，品牌标志用完整素材。JSON 里给了各部件职责和检查输入，仍需执行者写出具体布局并制作，不能把任务书当完成贴图。检查器验证输入契约与区域归属，不替代美术或 UV 检查。

## 本车资源和 RGB 查看副本

```text
python -B scripts/inspect_skin.py INPUT_DIR --materials MODEL_DIR/materials.json --manifest MANIFEST.json --profile RESOURCE_PROFILE.json --out NEW_REPORT.json
python -B scripts/export_uv_reference.py INPUT_C.dds SECOND_C.dds --out NEW_RGB_DIR
```

RGB 导出保留原尺寸并核对像素，原 DDS 不变。生产前从实际 BLK／materials 填写本车完整资源 manifest，逐项声明 file、role、alpha_semantics、color_space；不能从 Alpha 极值猜材质。包内 A7V 原作者资源清单位于 [a7v-author-resource](../profiles/ground/a7v-author-resource/)；它是输入审查案例，不是一键修复器。其他车型 profile 只有方向研究和节点／材质身份，生产贴图数量必须另查。

## DDS 和 mip

```text
python -B scripts/ground_dds.py --input NEW_STAGE_DIR --manifest MANIFEST.json --profile RESOURCE_PROFILE.json --config TOOL_CONFIG.json --out NEW_DDS_DIR --format rgba8
```

NEW_STAGE_DIR 只放本次新设计的颜色和已核实的材料贴图及对应 BLK；图层／mask／诊断图放别处，严格检查会拒绝混入的文件。新设计的颜色从实际分层工程导出，并按原资源语义恢复 Alpha。N/AO 来自本车已冻结材料输入，不能不看来源就复制 A7V 的 N/AO。

`rgba8` 为精确像素基线，`bc3` 为有损候选，转换后须重新做视觉检查。配置的 `texconv.path` 相对配置文件，sha256 必须为 `dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06`；使用已登记 2026.5.8.1 二进制，不下载或静默换版本。输出包括 `skin/`、`package.zip`、`mips.zip` 与报告，逐层读回检查到 1×1。未知材质／缺 AO 不能靠空图补齐而宣称保留。

## Blender 模型与 PS 原尺寸 UV 对照

实际方法见[双向对照](model-uv-cross-check.md)。Blender为外部工具，不随本包分发；优先使用可用的Blender连接或工作区已登记的预览入口，先查询实际能力，不能编造MCP工具名。保护源几何、材质和UV，确认对象/选面与图集对应，再进入PS类MCP看1:1局部；最后明确重载交付贴图复查。展示用缩图及图像缓存须记录，不能代替原尺寸检查。

下面的 `tank_preview.py` 使用ModernGL，可作快速排错；它不提供Blender选面/UV联动，执行成功不计作Blender检查。Composa接口以实时schema为准。

### 包内辅助命令

```text
python -B scripts/tank_preview.py --model MODEL_DIR --config PREVIEW.json --profile RESOURCE_PROFILE.json --out NEW_PREVIEW_DIR
python -B scripts/composa_mcp.py --out NEW_SESSION_DIR --timeout 60
python -B scripts/composa_mcp.py --calls CALLS.json --out ANOTHER_SESSION_DIR --timeout 60
```

模型输入为 `assembly.obj` 与 `materials.json`；PREVIEW 中 textures 的键对应真实颜色资源，每个绑定给 C/N/AO、颜色空间和 Alpha 语义，路径相对配置文件。方向、V 翻转、相机与灯光以本车实际验证为准。离线预览是近似材质，不宣称等价于游戏。所有目录型 `--out` 传全新路径，工具拒绝覆盖；inspect 的 `--out` 为新报告文件。PS 调用按实时 schema；MCP 缺工具就保留未完成，不能用桌面控制代替。

`build_a7v_design.py` 与 `stage_a7v_skin.py` 没有进入本包：它们服务于已经停止的临摹／清理支线。其技术教训保留在文档，新的默认流程从部件布局与实际 PS 制作开始。
