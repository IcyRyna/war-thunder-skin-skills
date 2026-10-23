# 从目标资源到可交付整车

Python3.12、Pillow、NumPy；素材审计和局部修复使用SciPy。独立包包含脚本，不需要安装另一个风格Skill。工程脚本的来源与内容哈希在toolkit-lock.json；不包含运行时二进制。Blender、Composa、texconv等外部工具先读取项目固定版本与实时能力，不能静默升级。

1. 冻结本车模型、原始C/N/AO和材质资源。建立独立的资源语义契约与原生表面profile；两者用途不同，不互换。
2. 在实际模型/UV上试贴关键部件，确认材质槽、遮挡、共享UV、字向与目标像素预算。先整车构图，再细节。
3. 从明确用途的母版制作子版，完成提取与规整两次验收。复制完整源面板、源车阴影和N/AO不属于风格移植。
4. 建分层工程并导出PNG。固定漆面用fixed_color.py核实覆盖和BLK；打包N/AO按本车语义处理。所有脚本只写新路径。
5. 全部mip读回、BLK检查、验证副本重开、原生模型重新加载最终DDS。以材质来源哈希验证预览确实读取当前包，而非旧暂存文件。
6. 查看整车、近景、下部/背面和完整UV。原色漏涂常出在小件、岛边、装饰/机枪组下的金属壳体与过粗高度保护区。按材质拆分，不用一条关键词排除所有表面。
7. 提供游戏包、可编辑工程、七视图和三张独立整车图。当前源与输入保持可追溯；失败/放弃/人工介入保留在任务，公开包不装任务对话、机器环境或内部审计。

## 运行入口

```text
python -B scripts/export_uv_reference.py BODY_C.dds TURRET_C.dds --out NEW_RGB
python -B scripts/inspect_skin.py TARGET_SKIN --materials MODEL/materials.json --manifest texture-manifest.json --profile resource-profile.json --out NEW_INSPECTION.json
python -B scripts/compose_native.py check --profile vehicle-profile.json --plan design-plan.json
python -B scripts/compose_native.py compose --profile vehicle-profile.json --plan design-plan.json --out NEW_COMPOSITION
```

实际没有独立AO时显式记录数量0及材质/资源证据，不造空AO。DDS工程工具保留原有显式语义、完整mip和有损/无损区分；fixed_color.py export提供无需texconv的无损BGRA8基线。颜色为fixed_rgb/srgb；实际透明贴花为opacity/srgb；打包N为packed_data/linear；AO为scalar_data/linear。

## Composa完整批次

通过 `python -B scripts/editor_batch.py --calls calls.json --out NEW_SESSION` 调用。批次包括打开自己的基底/工程、导入图层、描述、导出和保存；客户端记录并关闭其自有文档。不要把“打开”与依赖活动文档的后续编辑拆成两个默认关闭的进程。复制CMPS到验证目录再开；重导出逐像素比较。

多个载具会话必须共用该包装器的系统临时锁，不能同时依赖活动文档。已有文档不属于新批次。画布拖动、revision变化、工具超时或未知应用状态时先看原始响应与document_state；不能重放已成功的place_image。只有确认同一自有文档/同一revision时才做保存恢复，验证副本重开后再计通过。

## 模型、显示与附件

活动材质对应活动UV图像；多材质部件逐槽看。加载最终DDS后保存可移动的打包Blender工程，保持原模型与UV，不把概念生图的几何/光影烘进C。工作区宣传图使用登记的地面studio入口与标准；普通预览保持均匀中灰、克制高光和完整整车取景。

要求去掉附件时，先验证游戏附件开关、节点与shader可用路径。只在离线模型隐藏几何不等于游戏涂装能移除它；不透明C的Alpha0可能是迷彩混合，不能冒充透明隐藏。实际游戏不支持的部分如实记录，仍完成能交付的部分。
