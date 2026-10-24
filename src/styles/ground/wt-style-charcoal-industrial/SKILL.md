---
name: wt-style-charcoal-industrial
description: 制作或修正 War Thunder 地面载具的炭灰工业涂装（原 S42 / SPECTRE42）。以勒克莱尔 AZUR 源码为第一范本，安排三档主灰区、大几何与低对比块、差异化蜂窝、车型专属贴纸、车尾橙黑警示及分区材质；在目标车真实模型与原生UV上制作并检查最终DDS与游戏实装。
metadata:
  version: 0.1.5
  base_version: 0.1.1
  status: released
  previous_id: wt-style-spectre42
---

# 炭灰工业涂装 · 0.1.5

**勒克莱尔AZUR始终是第一制作范本。** 学它的源码、模型与原生UV所体现的整车构成；M1为美术参考，99A/A6HEL/A7V为适配和返工案例。0.1.2/0.1.3/0.1.4来自共同基线0.1.1，按经验取舍，本版重点补足可执行的美术方向。正式 ID 为 `wt-style-charcoal-industrial`；旧名 S42 / SPECTRE42 作为风格来源与历史别名保留。0.1.2—0.1.4 仅为本地分支，不单独发布。

## 开工先读这四件

1. [AZUR制作精髓与防单调检查](references/azur-art-direction.md)：三个主灰区、三种图形尺度、六个整车检查区及材质层次。
2. [颜色与区域配方](references/azur-style-recipe.json)、[色区角色卡](references/azur-style-card.svg)：主灰34/47/65是候选起点，侧面小块27/33/39/47/54来自AZUR源码；不要混为一种全车棋盘。
3. [六组车型贴纸标注](references/decal-adaptation.md)：D01身份、D02装备、D03前部、D04顶部、D05微色标、D06车尾橙黑线。前四组逐车确认文字语义，后两组随承载面适配。

4. [制作工具与发布规范](references/required-editor-and-blender.md)、[命名](references/naming-contract.md)、[GitHub简介](references/github-publication.md)：实际制作必须使用PS/Composa；Blender可用就必须实际调用。公开名称不带制作号，获准上传时简介同步完成。

**工具要求是制作流程的一部分。** 仅脚本合成或仅连接编辑器不算PS制作；已有网页预览器也不取代可用Blender的模型/UV和最终DDS检查。

## 制作顺序

先核实目标型号、附件、材质槽、原生UV和共享关系，模型定位与UV细节双向对照。然后安排整车A主炭灰、B次级灰、C提亮灰的大几何分区；主体占主导，提亮克制。首上、炮塔与顶部都要有构成，不能只做侧裙。

再叠局部低对比小块和蜂窝主带，保留安静区域。大几何、小灰块和蜂窝分别控制尺度；ERA基础色按真实板块组织，蜂窝按实际主面/窄面完整裁切。不能靠满车白线路、巨大徽记或碎块弥补底色单调。

按D01—D06做本车子版。先提取净图形，再规整与适配；生图结果仍检查规则几何、文字和透明污染，程序重画如实记录。标签、尺寸、位置、字向和遮挡逐车确认；LECLERC、FY-4 ERA、D-TECHNOLOGIE、APS等不跨车默认继承。**车尾默认安排橙色/橙黄黑警示线条并检查左右呼应，不能留下素灰屁股。** 对应部件不存在时改可用承载面或记录本车具体替代方案。

材质同时完成：主体克制磨砂金属，蜂窝较轻反射，火控壳体更深且有集中高光，镜片独立。去除低频脏斑，保留细磨砂、结构缝、焊缝与合理AO。炮管/炮根、机枪/枪托、备用履带、网布、橡胶和玻璃分别处理，不能全车一个材质值。黑色金属不是添加金色边线。

最后按六区检查表看最终DDS、全部mip与真实加载文件。窄压条、框边、后半裙甲、背面、小件与共享使用者不能漏查。贴花Alpha、固定漆面C覆盖、玻璃/裁切Alpha、N.A数据分别保护；同图钢面与镜片不能全图刷Alpha255。左右差异同时对比整片C/N/AO，不只擦掉旧条纹。

发布前按[命名与GitHub简介](references/github-publication.md)准备真实作品介绍、安装与验证状态、来源及下载说明，名称和目录沿用登记身份。具体发布授权已有则直接执行，不凭制作授权扩大上传范围。

## 按问题读取

| 问题 | 入口 |
|---|---|
| 范本身份、分支经验及规则范围 | [第一范本](references/primary-anchor.md)、[共同规则](references/consolidated-rules.md)、[分支经验](references/branch-lessons.md) |
| 蜂窝漏边、共享UV、目标子版 | [真实面覆盖](references/era-surface-coverage.md)、[模型与UV](references/model-uv-method.md)、[母子版](references/generation-children.md)、[素材目录](assets/catalog.json) |
| 材质、镜片、脏斑与色差 | [材质与Alpha](references/material-and-alpha.md)、[成对诊断](references/finish-diagnosis.md)、[原生部件](references/native-surface-corrections.md) |
| 车型选择、网布与部署 | [车型案例](references/vehicle-cases.md)、[原生模型边界](references/native-model-deployment.md)、[实装与工作集](references/runtime-and-storage.md) |
| 工具、图片、工程和证据 | [工具](references/tool-integration.md)、[生产](references/production.md)、[图片查看](references/image-input-workflow.md)、[验证边界](references/validation.md) |

优先复用已有本地交互预览器检查目标车型/场景/版本；用户要求图片导出时再生成，七视图逐次明确授权。Composa只收尾本批自有文档，保留当前与一个完整回退对，工程按需从ZIP取材。技术、离线视觉、游戏反馈、独立跨车复现与发布分别记录。当前AZUR圆镜试验与99A最新画面沿用各自待评边界；0.1.5的构图建议尚未在未见车型上独立验证。
