# 参考文档索引

按目录分五类，每份一句话说明用途。入口和制作顺序见 [SKILL.md](../SKILL.md)。

## style/ 怎样才好看

| 文档 | 用途 |
|---|---|
| [aesthetic-direction.md](style/aesthetic-direction.md) | 审美总纲：AZUR 实测颜色、四种纹样尺度、焦点、顶部警示、六区、默认不做 |
| [decoration-playbook.md](style/decoration-playbook.md) | 装饰手法：三层装饰、密度预算、构图原则、装饰词汇、救素顺序、按车型落位、素/花自查 |
| [part-recipes.md](style/part-recipes.md) | 逐部位做法：13 项部位与其他小件的主装饰、副装饰、材质、禁忌；机器默认元素对照 |
| [decals-and-text.md](style/decals-and-text.md) | 贴纸与文字：D01—D06 角色、字体颜色、排版、清晰度底线、母子版记录 |
| [material-looks.md](style/material-looks.md) | 材质观感：材质相对层级、已用 R/B 数值、部件观感、去污、防滑、印刷图形 |

## workflow/ 怎样做出来

| 文档 | 用途 |
|---|---|
| [production-contract.md](workflow/production-contract.md) | 制作契约：vehicle-review 各字段、标签依据、底色与材质计划、合成入口、DDS 编码、运行绑定 |
| [production-detail-checklist.md](workflow/production-detail-checklist.md) | 极细检查：输入链、方向×状态观察、左右排版、动态网布、不同 C/N 网格、撤旧图、近中远、mip 与 LOD |
| [native-skin-detail-reuse.md](workflow/native-skin-detail-reuse.md) | 原皮细节：识别、保留/换色/提取/替换四种处理、同 UV 见证、压灰小件补回 |
| [asset-pack.md](workflow/asset-pack.md) | 素材包：独立分发、定位、校验命令 |
| [asset-catalog.md](workflow/asset-catalog.md) | 按用途选素材 |
| [asset-use-and-adaptation.md](workflow/asset-use-and-adaptation.md) | 素材直接取用或 AI 按车型改制，改制记录方式 |
| [generation-children.md](workflow/generation-children.md) | 确需生图时的子版流程与门槛 |
| [extraction-and-regularization.md](workflow/extraction-and-regularization.md) | 从原作提取图形与规整两阶段验收 |
| [extraction-and-repair.md](workflow/extraction-and-repair.md) | 原像素复刻模式的提取与受控修复 |
| [local-repair.md](workflow/local-repair.md) | 局部修复工具接口 |
| [image-input-workflow.md](workflow/image-input-workflow.md) | 大量参考图与预览的读取方式 |
| [existing-project-replay.md](workflow/existing-project-replay.md) | 用本 Skill 检查旧工程的回放步骤 |
| [troubleshooting.md](workflow/troubleshooting.md) | 常见症状与诊断：偏色、黑斑、发白、天空蓝、镜片、漏边、残影、太素/太花 |

## contracts/ 怎样算做对

| 文档 | 用途 |
|---|---|
| [schema-3-contract.md](contracts/schema-3-contract.md) | 本车 manifest schema 3：原生面、通道、场景契约与迁移 |
| [layout-native-checks.md](contracts/layout-native-checks.md) | 顶部图组等布局预检：实际墨迹、承载面、尺度、遮挡、字向 |
| [surface-coverage.md](contracts/surface-coverage.md) | 真实面覆盖与共享使用者检查 |
| [uv-coverage.md](contracts/uv-coverage.md) | 完整原生 UV 覆盖与共享 UV 几何检查 |
| [scope-and-visual-audit.md](contracts/scope-and-visual-audit.md) | 完整范围合同与实际画面审计、无装饰底色图层状态 |
| [material-parameters.md](contracts/material-parameters.md) | 打包 N 语义、R/B 与微法线应用、防滑参数、网格映射 |
| [native-profile.md](contracts/native-profile.md) | compose_native 的 profile 与计划接口 |
| [native-resource-checks.md](contracts/native-resource-checks.md) | 原生资源名、DDSx 头与导出门槛 |
| [carrier-and-budget.md](contracts/carrier-and-budget.md) | 承载面测量与最终像素预算 |
| [native-model-deployment.md](contracts/native-model-deployment.md) | 共享 UV 与原生模型 UV 接入的证据边界 |
| [runtime-and-delivery-contract.md](contracts/runtime-and-delivery-contract.md) | 运行纹理、逐 mip 编码误差与交付合同 |
| [runtime-and-storage.md](contracts/runtime-and-storage.md) | 实装、部署回执与工作集 |
| [tool-execution-contract.md](contracts/tool-execution-contract.md) | 工具调用顺序与生产回执 |
| [required-editor-and-blender.md](contracts/required-editor-and-blender.md) | 真实编辑器与 Blender 的必做步骤 |
| [tool-integration.md](contracts/tool-integration.md) | 按情况选工具及使用条件 |

## delivery/ 怎样交出去

| 文档 | 用途 |
|---|---|
| [package-budget.md](delivery/package-budget.md) | 游戏包 <100 MB、解压 <200 MB 与任务收尾 |
| [naming-contract.md](delivery/naming-contract.md) | 公开名称、目录与版本命名 |
| [github-publication.md](delivery/github-publication.md) | 作品发布与涂装简介 |
| [publication-templates/](delivery/publication-templates/) | 发布说明与 README 模板 |
| [validation.md](delivery/validation.md) | 本版已验证内容与明确边界 |

## data/ 机器读取的规则与数据

| 文件 | 用途 |
|---|---|
| [style-policy.json](data/style-policy.json) | 唯一机器规则：灰阶、图形角色、13 项部位默认、覆盖角色、布局门槛、参考层级 |
| [vehicle-review.template.json](data/vehicle-review.template.json) | 本车设计/检查记录模板 |
| [azur-style-recipe.json](data/azur-style-recipe.json) | AZUR v29 实测：灰阶、点缀色、蜂窝、碎片参数 |
| [azur015-measurements.json](data/azur015-measurements.json) | AZUR 分区灰阶与 N 值历史测量 |
| [azur-retained-evidence.json](data/azur-retained-evidence.json) | AZUR v29 运行包身份与逐文件哈希 |
| [decal-adaptation.json](data/decal-adaptation.json) | D01—D06 角色与每车须改字段 |
| [decal-layouts.json](data/decal-layouts.json) | 四种贴纸版式结构 |
| [palette-policy.json](data/palette-policy.json) | 中性漆面色度容差 |
| [feature-region-measurements.json](data/feature-region-measurements.json) | 素材细线与字高测量区域 |
| [production-assets.json](data/production-assets.json) | 制作素材清单摘要 |
| [workflow-requirements.json](data/workflow-requirements.json) | 流程必做项 |
| [release-validation.json](data/release-validation.json) | 本版回归测试结果 |
