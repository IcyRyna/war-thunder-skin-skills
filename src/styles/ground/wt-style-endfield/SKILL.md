---
name: wt-style-endfield
description: 为 War Thunder 坦克设计终末地 / ENDFIELD 黑白黄工业风涂装。先解析 A7V 原作者范本，再按目标车型的车体、炮塔、炮管等真实部件重新构图；含豹2、T-80、T-90M、99A、勒克莱尔四视方向、完整透明徽记、可编辑素材、可选兜底，以及 Blender 模型与 PS／Composa 原尺寸 UV 的双向对照。用于此风格的布局讨论、素材制作及原生 UV 落地，不用于飞机或任意工业风主题。
metadata:
  version: 0.1.1
  status: released
---

# 终末地坦克风格 · 0.1.1

用 A7V 范本学会组织明暗、方向、识别和留白，然后为目标坦克重新设计。车型方向图帮助判断哪里能承载设计；它们不规定图案坐标、面积比例、徽记大小或黄线走向。默认独立构图，预设仅在用户选择或执行者拿不定方案时作为起点。

## 按当前阶段读取

| 当前工作 | 先读／查看 |
|---|---|
| 理解范本 | [A7V 完整解析：8 条规则及证据](references/a7v-analysis.md)、[原作左视参考](assets/reference/a7v/left.png)、[原作顶视参考](assets/reference/a7v/top.png) |
| 选择车型大方向 | [五个车型家族索引](references/vehicle-directions.md)，再读对应家族；每个都有侧、前、后、顶视图 |
| 给各部件划分任务 | [部件与子区](references/parts-and-briefs.md)、[可编辑 6 部件／29 子区](references/layout/zone-tree.json) |
| 决定素材与主次 | [素材目录与使用条件](references/assets-and-editing.md)，主徽记必须完整 |
| 按需读取分区／预设参考图 | [AI 视觉参考索引](references/visuals/index.md)，只读当前车型或正在比较的方案 |
| 暂时拿不定构图 | [3 套可选兜底](references/optional-fallbacks.md)；不选也能执行全流程 |
| 定位实际构件、检查纹理细节 | [Blender模型 ↔ PS/Composa UV双向对照](references/model-uv-cross-check.md)：同一部位、同一图集、成对复查 |
| 开始实际制作 | [PS/MCP 制作与检查](references/ps-production.md)、[工具与输入接口](references/tool-usage.md)、[贴图契约](references/texture-contract.md) |
| 核对来源和历史成果 | [r11 与旧 Skill 取舍](references/inheritance-and-lessons.md)、[成果覆盖表](references/coverage.json)、[来源](references/provenance.json) |
| 检查已验证到哪里 | [验证范围与交付](references/validation-and-delivery.md)、[来源与验证范围](references/provenance.json) |

按当前阶段读取资料；原作图和局部参考用于观察视觉关系，车型原始四视用于判断承载面。展示网页与排版图板放在仓库文档，演示 CMPS 和完整检查过程留在本地研究记录，不随运行包加载。完整旧 40 文件保存在可选素材库，运行包带所需的精选资源；源码附件包含可重复构建运行包的全部输入。

## 实际工作顺序

1. **理解原作。** 以 HK416の午夜福音的 A7V 范本为第一视觉依据。分清观察、解释、迁移建议。r11 的总结只补充检查点；不把临摹的漏洞、色板和自述工序当成原作规则，也不默认继续修复它。
2. **识别本车。** 确认具体型号、模型、附件状态、资源和原生 UV。先从车型家族方向找可读承载面，再适应子型号。T-90 用 T-90M；当前 99A 无两只后置油桶；当前勒克莱尔主徽记放车体／侧裙，炮塔另行设计。
3. **先分区，再构图。** 按车体 H、炮塔 T、炮管 G、机枪／座 M、附件 A、轮履 R 划区，可增加、合并、删除子区。为全车确定焦点、颜色角色、黄色职责和疏密，再给每个部位自己的设计意图。H07 是 H04 细分方式，不能重复覆盖同一片面。
4. **自由设计。** 主徽记、次级组合和微字有等级；黄面、路线、端点及细伴线各有作用；安静区保留机械结构。跨板关系在本车上重排。车体／炮塔和炮塔／炮管会独立运动，方向可呼应，不要求一条图形跨轴静止连通。
5. **需要时借用兜底。** F01 范本关系、F02 浅色疏朗、F03 深色集中都能改、混合、只取局部或不用。不能为了符合预设而裁徽记、扭曲车型或填满每一块板。
6. **用 Blender 与 PS/Composa 双向落实。** 先在真实模型确认部位、朝向、材质槽和原生UV岛，再在对应原尺寸图集以1:1看纹素细节；修改后重载回同一模型，核对变形、接缝、遮挡及共享UV影响，必要时再回PS。模型看“在哪里”，UV看“具体什么样”；两边成对记录，按[对照方法](references/model-uv-cross-check.md)执行。使用实时工具能力，保护已有场景与文档；最终DDS读回后仍复查两边，CMPS用副本重开。
7. **分项交付。** 技术、视觉、游戏、复现各自记录；结构正确不等于美术认可。未运行就写 `not_run`。本包为已发布的 0.1.1 方法修订，基于0.1.0；构建不等于完成实车的模型/UV验收。实际作品、后续规则改动、安装和再次发布，仍按该次用户明确授权的范围执行；旧 1.4 保留为历史版本。

## 不能在迁移中丢掉的约束

- **工业徽记是一整个标志。** 三角、轮廓纹、ENDFIELD 和 INDUSTRIES 保持完整。优先使用 [已有透明 PNG](assets/legacy/decals/endfield-industries-en-native.png)，保留原文件与透明边界、统一缩放，不拆字、裁标或拉伸。通过车身实际色块保证对比，不额外加不透明“贴纸底板”。400×400 是画布，实际墨迹仅 122×122；大尺寸用途必须核对清晰度或选择已标注来源的矢量。
- **默认不做旧。** `weathering=none|light`，默认 `none`。`surface_grain=none|subtle` 独立选择；没有确认的漆面微粒保持 `none`，不能套用旧 A7V 清理试验的噪点幅度。关做旧要去掉颜色和材质两方面影响；结构、焊缝、AO 与掉漆不是同一层。
- **材质有自己的身份。** 颜色、N、AO、玻璃、网格和橡胶分别处理。固定替换 C 的全零 Alpha 下仍有有效 RGB；透明覆盖按覆盖语义滤波，N/AO 是数据。完整 mip 到 1×1。不能把原车阴影、孔口和机械痕迹连同裁片搬到新车。
- **方向图不是精确 UV 遮罩。** 五家族真实模型四视图及节点／材质归类已经保留；其他车型的生产 UV、最终 DDS 和游戏效果仍需实际检查。模型文件和整套原始 DDS 由目标任务提供，包内不重复分发游戏模型。

可先执行 `python -B scripts/layout_brief.py create --family t-90 --theme ENDFIELD --number EF10 --out NEW_BRIEF.json` 生成可编辑部件任务书；省略 `--preset` 即自由构图。该工具组织输入和检查接口，不自动生成最终涂装。
