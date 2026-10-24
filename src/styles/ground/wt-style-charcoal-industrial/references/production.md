# 从真实工具制作到交付与发布

实际涂装创作或实质修订必须完成[PS/Composa分层阶段](required-editor-and-blender.md)。Blender具备可用程序、API与目标模型处理能力时也必须调用，不能用已有网页预览代替；是否渲染图片由本次需要和授权决定。

1. 读AZUR第一范本与制作精髓，确认目标型号、模型、原生C/N/AO、材质语义及附件；填写本车艺术方向表和D01—D06适配。
2. 连接真实PS/Composa工具并读schema；Blender可用时实际核对目标模型/UV/材质与共享、遮挡、字向。
3. 提取、规整、制作本车子版；在编辑器完成真实图层组装/编辑、保存原生工程、导出关键图并以验证副本重开。脚本辅助精确遮罩/通道/DDS，不代替此阶段。
4. 按本车资源语义导出DDS及全部mip、BLK绑定；保留N数据Alpha、光学/裁切与固定漆面不同职责。无独立AO时按真实数量0记录，不造空图。
5. Blender可用时将最终DDS真实回绑模型并记录输入哈希，按六区与局部核对；默认用本地交互预览展示，七视图单次授权。实际游戏加载、文件身份、用户评价分开。
6. 按[命名规范](naming-contract.md)准备配对游戏/源码包与登记映射；当前与一个完整回退对按工作区规则保存，编辑器自有文档收尾。
7. 按[GitHub简介规范](github-publication.md)准备可审查作品README与Release文案，写清实际设计、安装、下载、状态和来源。本次已有发布授权则按明确范围上传并回读核验；未授权时保留本地成品和文案。

运行入口仍使用包内原生UV、固定颜色及DDS工具，不依赖另一个风格Skill。Python3.12/Pillow/NumPy，素材审计或局部修复使用SciPy；外部工具按项目固定版本与实时能力核对。规范脚本只写新输出。

技术辅助入口示意：

```text
python -B scripts/compose_native.py check --profile vehicle-profile.json --plan design-plan.json
python -B scripts/compose_native.py compose --profile vehicle-profile.json --plan design-plan.json --out NEW_COMPOSITION
python -B scripts/editor_batch.py --calls calls.json --out NEW_EDITOR_SESSION
```

保持模型、活动材质与UV图像对应。附件只在离线隐藏不等于游戏已移除；C.Alpha0不一定表示透明。Composa身份/修订冲突和未知执行结果先按回执恢复，不重复贴图或强杀窗口。
