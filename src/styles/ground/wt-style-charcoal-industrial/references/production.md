# 当前制作顺序

先按[极细制作检查](production-detail-checklist.md)落实方向、状态、采样与通道闭环，再以[部位默认配方](part-layout-defaults.md)和[候选流程](candidate-workflow.md)为当前入口；历史步骤不覆盖统一style-policy.json。

1. 核实车型、附件、实际部件和共享UV。先为首下身份、顶部完整警示、侧铭牌留出可见承载面；逐项做13部位与六区决定。
2. 选本车材质参数，安排大灰区、防滑与安静面。base_only检查隐藏蜂窝/贴纸/微色标后仍成立的整车构成。
3. 做本车图形子版，使用完整真实面和共享使用者检查范围；细密侧裙蜂窝与炮塔较大蜂窝分层。字体、图组尺寸、方向、留边、遮挡同时核对。
4. 实际完成[PS/Composa编辑与副本重开](required-editor-and-blender.md)。Blender可用时实际检查模型/UV与最终DDS；仅连接工具不算制作。
5. compose_native schema 4接入vehicle_design；check也检查实际投影范围。完成N材质与微法线时按[参数规则](material-parameters.md)保护数据Alpha及结构。
6. 导出完整mip后实际回绑，执行vehicle_review --stage final及delivery_validate。观察、技术、游戏反馈与用户认可分别记录。
7. 默认复用本地交互预览，不自动出七视图。本次有发布授权时才按[命名](naming-contract.md)与[简介](github-publication.md)发布；完成后按[包体与收尾](package-budget.md)处理本任务文件。

本轮Skill维护仅是本地候选，不触发新涂装制作、编辑器调用、安装、上传或历史作品清理。
