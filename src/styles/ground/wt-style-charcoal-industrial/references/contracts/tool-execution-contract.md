# 工具调用顺序、能力边界与生产回执

实际制作按下表调用，不以“已连接”“有文件”或“技术检查通过”替代操作。Skill维护只测试受影响工具，不为了凑次数改动旧作品。全部Python命令使用-B；Windows重定向日志使用-X utf8。

| 阶段 | 实际入口/动作 | 必须拿到的结果 |
|---|---|---|
| 输入身份 | input_snapshot.py；native_inventory.py | 活动BLK、真实资源哈希、完整源面与材质对应 |
| 编辑器发现 | editor_batch.py --out 新目录，不带--calls | 当前实时schema；只证明连接，尚未制作 |
| 实际分层 | editor_batch.py --calls 本批调用.json --out 新目录 | 按实时schema新建/打开、放置或编辑真实层、保存原生工程、导出；完整session/原始响应/lifecycle |
| 重开验证 | 复制已保存工程，用新批次打开副本、描述图层、再次导出 | 两个不同导出文件逐像素一致；副本与保存工程哈希一致；只收尾本批自有文档 |
| 素材改制 | 按任务采用SVG/排版/参数图案工具；确需位图生成再用imagegen | 新子版真实文件、来源与测量；已有素材直接用不必生图 |
| 材质处理 | hd_antislip.py、material_parameters.py及明确通道脚本 | 对应本车范围的C/R/B/微法线与保护记录；不把N.A当透明度 |
| 布局与合成 | compose_native.py check/compose；vehicle_review.py design/base | 实际投影、完整原生面范围、字高及本车设计关联 |
| 视线/遮挡 | visibility_probe.py、layout_fit.py | 完整场景与核心文字重算结果；手填计数不算通过 |
| 模型工具 | 已核实的Blender二进制，后台脚本 | 原生模型、UV、材质槽检查；重新绑定当前最终DDS；源面与导入面关系明确 |
| 日常观察 | 已有本地网页预览；必要时tank_preview.py | 默认一张iso检查图；近景按需，七视图必须有本次用户明确请求 |
| DDS | ground_dds.py、dds_variant.py、dds_snapshot.py等 | 实际编码、全mip解码、通道误差与原生BLK对应 |
| 技术与交付 | vehicle_review.py --stage final，再delivery_validate.py | 前者是纹理/模型契约技术检查；后者另检查真实工具回执和ZIP名单/哈希 |

## 当前编辑器入口

本候选scripts/editor_batch.py提供跨批互斥和UTF-8子进程，可用--exe指定真实Composa程序；COMPOSA_EXE发现仍有效。--calls省略时只读取schema。默认关闭本批自有文档；--keep-open仅用于明确需要保留本批文档的流程。

工作区通用photoshop-tools/scripts/composa_mcp.py与随包客户端可用于诊断；实际写批次优先经过editor_batch的互斥。直接用客户端库自编制作脚本时，也须使用editor_lock覆盖完整批次。锁只协调遵守同一协议的任务，不保证其他任意程序停止操作。

未知结果或日志读取失败时先检查session.json、原始response和文档状态。不得因调用方没读到日志就重放已经成功的编辑。客户端会保留不确定状态，不自动重试修改。

## production_tools字段

本车manifest继续使用schema 3，新增production_tools schema 1。它是生产交付入口的必需字段；旧manifest可以继续做技术诊断，但缺少回执时不能通过新的delivery_validate。

editor.sessions按时间顺序列出批次记录，每条包含带file/sha256的session、schema、lifecycle，以及完整responses列表。现成客户端输出可通过以下命令收集为一条记录，然后放入sessions数组：

    python -B -X utf8 scripts/production_tools.py session ACTUAL_SESSION_DIR --out NEW_SESSION_REFERENCE.json

editor.projects每项包含：

- project：真实保存的CMPS/PSD/PSB文件与SHA256。
- reopened_copy：不同路径、字节相同的重开副本；saved_export、reopened_export：不同路径的RGBA导出及SHA256。
- outputs：每项绑定runtime_texture_id与canonical文件/哈希。每份modified颜色输出都必须有编辑器链，不能遗漏。
- 如果规范像素还经过精确脚本调整，outputs项另有postprocess：实际script与run_log的file/sha256、exit_code=0、input_sha256（保存导出）、output_sha256（最终canonical）和operation。该记录说明网格/通道等后处理，实际像素边界仍由final检查。

调用核验会读取原始返回、实时schema和生命周期，检查实际编辑、保存、打开副本与导出操作是否存在且成功；只连上工具、打开平图或指向同一个导出文件不能替代制作与重开。

当前自动解析器支持随包Composa客户端的日志格式和调用名。其他真实Photoshop桥要先提供对应解析适配，不能把不同接口的日志改名伪装成Composa回执。可编辑源文件格式本身不证明用了哪个应用。

blender.status为checked时，receipt指向实际脚本运行产生的JSON（file/sha256），包含：

- executable、version、完整argv、exit_code=0；argv必须实际调用所记录的script，并使用--background及--python-exit-code 1。
- script、run_log的file/sha256；model_sha256与本车模型一致。
- bound_runtime_dds：运行纹理ID→实际最终DDS SHA256，必须与完整当前运行名单一致，不能只写“已绑定13张”。
- geometry_uv_before_sha256与geometry_uv_after_sha256：用同一原生面/UV清单算法计算，保持一致；导入器删面或重排时先重建对应，不能把两个不同来源的数组按下标相配。

若Blender确实不可用，status=unavailable，提供reason及diagnostic文件。诊断必须包含usable=false和实际attempts（entry、outcome=not_found/failed）；不能把“没GPU”“网页能看”或“未尝试”作为不可用。检查结果明确保留model_tool_validation=not_run，不能称Blender已通过。

    python -B -X utf8 scripts/production_tools.py check VEHICLE_MANIFEST.json --out NEW_TOOL_AUDIT.json
    python -B -X utf8 scripts/delivery_validate.py --manifest VEHICLE_MANIFEST.json --zip GAME.zip --out NEW_DELIVERY_AUDIT.json

回执检查验证记录和产物关联，不能鉴别外部伪造日志，也不自动批准美术、模型观感或游戏效果。

现有工程的图层隔离/恢复、保存和副本重开可作为真实回放；它不自动证明新增了设计内容。相对旧涂装baseline的state=preserve不代表原厂原皮被保留。回放时另做[原皮与构成检查](../workflow/existing-project-replay.md)，保存后的模型还要核对所有使用图片的外部文件或有效内嵌数据，不能只列新增DDS而漏掉原生附件资源。

## 预览与源面不能混用

tank_preview默认只生成iso。生成七张及以上时需--seven-view-authorization指向本次请求记录，其中user_request是用户明确要求原文，request_reference指向该次请求，authorized_views按顺序列出本次视角；不能复制旧授权或由AI自授。

tank_core的渲染读取器会略过不可渲染退化三角形，但现在保留source_face_ids、skipped_source_face_ids和source_triangle_count。缓存用源文件SHA256识别，不再仅看mtime。预览数组下标不是原始面号；完整验证以native_inventory.source_geometry为准。

本次A7HU实际检查发现：完整源OBJ有260,995个三角面，预览解析有260,984个可渲染面（11个退化面另列）；Blender 4.5.14默认验证导入产生260,977面，关闭validate_meshes仍只有260,993面。仅关闭清理并不能证明原生面完整。必须按实际顶点/UV/材质重建对应，不能以面数接近就沿用原面号。

旧MTL引用的缺失PNG只说明旧材质路径失效，不代表OBJ不能读。新制作从当前BLK/DDS绑定并逐项检查，缺图状态不能当成完整材质预览通过。此次只读导入试验没有重新绑定整个旧作品，因此只证明导入能力。

## 依赖与传输

核心Python依赖numpy、Pillow、scipy、numba；独立OpenGL预览另需moderngl，已写入toolkit-lock。bpy/mathutils由实际选定的Blender Python提供，不在宿主Python里盲装同名包。

编辑器图片响应在本地落盘，模型、纹理和完整包在本地处理。这里的工具内部消息上限不是聊天传输预算；向对话回传继续小于16,000,000字节并留余量，不打印Base64或一次输出整批schema/大报告。

本地8773网页预览在使用前先确认服务可达及场景确属本车。不把旧URL存在当成服务在线。实际制作时按本车已核实场景启动对应服务，或使用已验证可用的独立OpenGL单视图；没有当前车型场景的Skill审计不启动或替换其他任务服务。
