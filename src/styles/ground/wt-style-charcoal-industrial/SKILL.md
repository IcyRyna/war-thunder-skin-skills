---
name: wt-style-charcoal-industrial
description: 制作或修正 War Thunder 地面载具炭灰工业涂装。以AZUR为第一范本，逐部位安排材质、主副装饰和原皮小标记，完成灰区、蜂窝、身份与警示、观瞄机枪及车尾细节；素材可直接用或由AI按车型调整，并在真实模型原生UV与最终DDS上核验。
metadata:
  version: 0.1.6
  base_version: 0.1.5.1
  status: release
  candidate_id: charcoal-0.1.6-release
  previous_id: wt-style-spectre42
---

# 炭灰工业涂装 · 0.1.6

Skill与素材是两个独立产物：本包只含规则、工具和必要文字模板。制作图形、高清材质与AZUR范本图位于独立的 `wt-charcoal-industrial-assets` 素材包；可以分别下载，也可以一起压缩交付。使用方式见[独立素材包](references/asset-pack.md)。版本身份以[VERSION.json](VERSION.json)为准；发布Skill不代表目标作品获美术或游戏认可。

**先按部位把作品做完整。** AZUR仍是第一构成范本；用户当前对目标车型的明确要求优先。不要等用户逐项指出首下、顶部、机枪、窄边或车尾遗漏后再补。

**素材可以照着拿，也可以由AI按车型自主调整。** 合适的素材包中的素材直接使用；不合适时，根据真实部位、原生UV和整车构图，调整文字、排版、外形、数量、密度、颜色和材质参数，也可拆分组合或参考包内风格新做本车子版。无需每次重画或生图，也无需为正常适配逐项再问用户。具体两条路线见[素材使用与AI适配](references/asset-use-and-adaptation.md)。

先按[AZUR主线](references/azur-primary-workflow.md)理解构成，再用[原生布局检查](references/layout-native-checks.md)处理目标车型；已验证范围及限制见[验证状态](references/validation.md)。

本版本新增[原生面、通道与场景契约](references/schema-3-contract.md)：五类误放行已转为最终入口回归，实际Composa兼容与BC7验收按明确合同执行。当前验证范围以[验证状态](references/validation.md)为准。

**装饰要充分，小件要完成。** 每个可见主要区域同时考虑大灰区/主图、部位副装饰、原皮小标记和真实材质细节。适用的原皮小字、刻线、色环、数据牌、反光片、焊缝与防滑先识别再处理；不能一并压灰，也不能用“克制”解释一色底漆和漏做的小件。

## 首先读取

1. [部位装饰与材质配方](references/decoration-and-material-recipes.md)、[原皮细节复用](references/native-skin-detail-reuse.md)，再对照[AZUR主线映射](references/azur-primary-workflow.md)与[部位默认配方](references/part-layout-defaults.md)：首下放什么、顶部放什么、机枪与观瞄怎么做，以及13项部位默认内容和替代规则。
2. [整车构成](references/azur-art-direction.md)、[第一范本](references/primary-anchor.md)：A/B/C主次、大几何/局部小块/蜂窝尺度、安静区域。60/30/10是建议，不是硬验收比例。
3. [统一规则](references/style-policy.json)和[候选制作流程](references/candidate-workflow.md)：脚本读取同一颜色、角色、材质和覆盖规则；线路与局部小灰块可选，不能为凑元素铺满全车。
4. [素材使用与AI适配](references/asset-use-and-adaptation.md)、[车型贴纸语义](references/decal-adaptation.md)、[布局结构](references/decal-layouts.json)：直接复用或按车型改制均可，文字和功能逐车核实，首下默认本车身份，顶部BLOW-OUT只用于核实的泄压盖。
5. [材质参数](references/material-parameters.md)、[覆盖检查](references/surface-coverage.md)：颜色、R/B、颗粒分别控制；按完整真实面和全部共享使用者检查，不用面积比例掩盖细边。
6. [极细制作检查](references/production-detail-checklist.md)：方向×状态、左右独立排版、动态图网布、不同C/N网格、撤旧图的六类通道、近中远与LOD。
7. [工具调用顺序与生产回执](references/tool-execution-contract.md)、[真实编辑器与Blender](references/required-editor-and-blender.md)、[包体预算](references/package-budget.md)：实际涂装制作必须完成PS/Composa；Blender可用时实际调用。只读研究或Skill维护不伪造制作调用。

## 默认制作顺序

**先定位部位。** 若有现用展开目录与旧ZIP，先按活动BLK的实际资源/目标/哈希确定本次输入；残留缓存中存在旧DDS不代表旧ZIP是当前版。 核实型号、附件、材质槽、原生UV、共享/镜像；逐项填写部位表与六区计划。首上、首下、炮塔侧、顶部底层、顶部警示、机枪、观瞄分别作决定，不能用一句“Z1/Z4已做”替代。

先确定首下字标、侧铭牌和顶部完整警示图组的实际占地；顶部防滑与灰块围绕警示和设备安排。

**整板构图不能因遮挡缩水。** 先固定真实完整盖板作为构图基准；要求占满时，文字安排到可读分区，斜条和副图形仍延展到整板。设备遮住部分非文字装饰不等于必须删掉那些装饰。禁止把承载范围裁成空闲角落，再用高可见率或局部填充率冒充整板完成。

**其他部位同样不能缩范围求通过。** 按[完整范围与实际画面审计](references/scope-and-visual-audit.md)固定制作前的源面合同，核对原导出器全部材质使用者；禁止改目标面组、把整面改局部、全方向标不可见或用零次像素比较凑通过。检查记录必须有当前模型/DDS绑定的实际图像和明确视觉结论，发现不满意就修正，不能只填 checked。

**先清点原皮细节。** 在目标模型和原C/N/AO上找实际小字、标线、色环、铭牌、结构与特殊材料；选择原位保留、保形换色、提取重组或替换。原生印刷图案必要时提取为本车独立透明层；独立材料按真实面组保护，不能拿随手挖空的大遮罩代替完整范围核验。

复用旧工程时先按[工程副本回放](references/existing-project-replay.md)检查已有内容。图层名称含“native detail”、G/A没改或蜂窝排除灯具，都不能证明原皮色标和材质保住；对代表性小件做原皮→底色→编辑器导出→最终DDS的同UV局部对照。

**再做无装饰底色。** A/B/C默认34/47/65，火控F约26；可按本车证据覆盖，不自动跨车套值。隐藏蜂窝、贴纸和新增微色标，保留大几何、材质分色、格栅素面和原生功能色；不能只留下00-base一层。检查首上/炮塔/顶部大几何仍能读清、安静面成立。不要把小数码块当大几何。

**安排本车图形。** 侧裙细蜂窝、炮塔局部较大蜂窝；首下本车身份构图及可选短警示条；顶部真实盖板上的完整警示图组；本车侧铭牌、黄青微色标、车尾橙黑条。部位无承载面或用户指定变化时，记录每个省略项及替代，不直接留空，也不强行造设备。完整图组随板形排版，检查旋转、字向、内部间距与遮挡。主图之外按部位补短刻度、角标、模块编号或适用原生小图形；原细节已丰富的区域可直接利用，素材不够时由AI改制。

**分开完成材质。** 主体克制金属，蜂窝轻反射，观瞄深色壳体与玻璃独立；机枪护罩/本体/枪托、炮管/炮根、备用履带钢/橡胶分别处理。去低频污斑，保留结构和微表面；原皮有效印刷标记不能当污斑抹掉。灯/反光片、胶圈、线缆、锁扣、钢索和布套按真实材料做出区别。磨砂用同一高度场生成C/法线/R，候选素材为中性27/27/27；粒度按真实采样决定。

**实际编辑、合成与检查。** 在PS/Composa完成真实分层、保存、导出和副本重开；本版本车计划使用schema 3，风格迁移的compose_native使用schema 4，必须带冻结的vehicle_design。check也实际投影图形检查越界，不能只校验JSON。全表面覆盖零遗漏，部分贴花按允许区域检查；不静默裁掉窄边或共享冲突。

**最终DDS与交付。** 重新绑定实际DDS和全部mip，完成六区、远中近景与转光检查。vehicle_review的final阶段分别审计canonical制作保护、真实图层、实际材质C/R/B/G/A、逐mip编码和原生BLK绑定；技术通过不代替美术或游戏认可。七视图逐次明确授权，日常复用既有本地预览。游戏ZIP严格<100,000,000字节、解压严格<200,000,000字节，使用delivery_validate同时核对编辑器/模型工具回执、预算、运行名单及ZIP逐成员SHA；完成后不自动保留涂装源码ZIP。

## 工具入口

- 工具调用与生产交付回执：[production_tools.py](scripts/production_tools.py)
- 第一范本核验：[azur_reference.py](scripts/azur_reference.py)
- 统一入口与完整字段：[candidate-workflow.md](references/candidate-workflow.md)
- 本车计划模板：[vehicle-review.template.json](references/vehicle-review.template.json)
- 整车检查：[vehicle_review.py](scripts/vehicle_review.py)
- 真实面覆盖：[surface_coverage.py](scripts/surface_coverage.py)
- 材质应用/检查：[material_parameters.py](scripts/material_parameters.py)
- 磨砂生成：[hd_antislip.py](scripts/hd_antislip.py)
- 发布验证范围：[validation.md](references/validation.md)
- 独立包完整性检查：[verify_release.py](scripts/verify_release.py)
- 极细制作指南：[production-detail-checklist.md](references/production-detail-checklist.md)
- 运行与交付：[runtime-and-delivery-contract.md](references/runtime-and-delivery-contract.md)
- 原生布局预检：[layout-native-checks.md](references/layout-native-checks.md)
- schema 3契约、迁移、场景探针：[schema-3-contract.md](references/schema-3-contract.md)
- 最新验证边界：[validation.md](references/validation.md)

以独立素材包中的素材、AZUR构图关系及目标原皮已有小细节为起点，可直接取用、由AI改制或创作本车子版；原作整车C/N/AO不跨车搬用。未知Shader先核实，C覆盖Alpha、贴花透明度、玻璃/裁切Alpha和N.A数据分别保护。只关闭本批自有编辑器文档。作品发布仍按本次授权，名称与简介见[命名](references/naming-contract.md)和[发布](references/github-publication.md)。
