# 局部修复接口

`apply_local_repair.py --mode rgb` 只改允许区 RGB，Alpha 原样；`--mode alpha` 允许局部 RGBA 改写，用于去除背景残片、补完整外缘和格缝。两种模式都要求 binary L 的 `--mask`；可另给 `--protected`，保护区优先。允许区外及保护区 RGBA 必须逐像素不变。

输入必须同画布对齐，或在 `--recipe` JSON 中明确给 `alignment` 六个逆仿射系数（输出坐标→模型图坐标）。禁止自动按Alpha外框强行拉伸。变换后先检查未修改区域 Alpha IoU（默认至少0.98）、RGB中位漂移（默认每通道≤12）；阈值是工程保护，不能证明视觉保真。失败保留原文件并记录，不写替换图。

`components` 为可选数组，每项声明 `source_seed`、`generated_seed`、`margin`（原生像素）、`area_range`、`colour_sample`（原生矩形）、`max_colour_offset`。种子选择连通部件、局部色样匹配色调，相邻实体自动保护；全部仍受显式允许/保护遮罩约束。工具不含任何蜂窝固定坐标。局部色匹配不能豁免整幅改亮检查。`anchor_mask` 可指定稳定的参照区域。

先从原图抠出全部可见内容；只把明确缺损的素材和范围交给生图。模型结果是参考，只有通过局部检查的区域才回写。未知微字保持原像素；不让模型猜新字。修复输出始终为候选，原图不覆盖。
