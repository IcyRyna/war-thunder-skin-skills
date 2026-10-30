---
name: wt-style-charcoal-industrial
description: 制作或修正 War Thunder 地面载具炭灰工业涂装。以勒克莱尔AZUR为唯一范本，按三层装饰（纹样场/焦点/小件）完成大斜切碎片、蜂窝、数码块、身份铭牌、顶部与车尾警示及材质分工；素材可直接用或由AI按车型调整，并在真实模型原生UV与最终DDS上核验。
metadata:
  version: 0.2.0
  base_version: 0.1.6
  status: release
  candidate_id: charcoal-0.2.0-release
  previous_id: wt-style-spectre42
---

# 炭灰工业涂装 · 0.2.0

**范本：勒克莱尔 AZUR（v29）。** 中性炭灰底上压大块直边斜切碎片；侧裙铺满带亮格的实心蜂窝，炮塔尾舱侧铺满暗色数码块，首上一簇渐散数码块；炮塔侧一组小而精的身份铭牌，首下琥珀斜体车名，顶部泄压盖黑底橙色人字斜条，车尾两侧橙黑斜条短板。纹样覆盖充分、对比克制、彩色极少。

**优先级：** 用户对当前车的明确要求 → 本 Skill 的风格规则（`references/style/`）→ 机器规则（`references/data/style-policy.json`）→ 案例数值。技术通过、离线视觉、游戏反馈和用户认可分开记录，任何一项都不能推出另一项。

## 目录

```text
SKILL.md                     入口（本页）
references/
  README.md                  全部参考文档的一句话索引
  style/       怎样才好看      审美总纲 · 装饰手法 · 逐部位做法 · 贴纸与文字 · 材质观感
  workflow/    怎样做出来      制作契约 · 极细检查 · 原皮细节 · 素材使用 · 生图与提取 · 症状诊断
  contracts/   怎样算做对      schema 3 · 布局/覆盖/范围审计 · 材质参数 · 运行与交付 · 工具回执
  delivery/    怎样交出去      包体预算 · 命名 · 发布模板 · 验证范围
  data/        机器读取的规则   style-policy · vehicle-review 模板 · AZUR 实测 · 贴纸角色
scripts/                     工具（下表）；每个都可 --help
```

素材在独立素材包 `wt-charcoal-industrial-assets`（32 项，其中 14 项是按 AZUR v29 实测绘制的子版，对照见[装饰手法](references/style/decoration-playbook.md)）：与本 Skill 并排解压自动识别，或设 `WT_CHARCOAL_ASSETS`。见[素材包](references/workflow/asset-pack.md)。

## 按任务读什么

| 任务 | 先读 | 再读 |
|---|---|---|
| 做一辆新车 | [审美总纲](references/style/aesthetic-direction.md) → [装饰手法](references/style/decoration-playbook.md) → [逐部位做法](references/style/part-recipes.md) | [贴纸与文字](references/style/decals-and-text.md)、[材质观感](references/style/material-looks.md)、[制作契约](references/workflow/production-contract.md) |
| 觉得车太素或太花 | [装饰手法](references/style/decoration-playbook.md) 第 5、7 节 | [逐部位做法](references/style/part-recipes.md) |
| 选用或改制素材 | [素材使用与AI适配](references/workflow/asset-use-and-adaptation.md) | [素材包](references/workflow/asset-pack.md)、[生图子版](references/workflow/generation-children.md) |
| 保留原皮小字、色环 | [原皮细节复用](references/workflow/native-skin-detail-reuse.md) | [症状诊断](references/workflow/troubleshooting.md) |
| 游戏里颜色、反光、残影不对 | [症状诊断](references/workflow/troubleshooting.md) | [材质参数](references/contracts/material-parameters.md)、[运行与交付](references/contracts/runtime-and-delivery-contract.md) |
| 检查旧工程 | [工程副本回放](references/workflow/existing-project-replay.md) | [完整范围与实际画面审计](references/contracts/scope-and-visual-audit.md) |
| 交付与发布 | [包体预算](references/delivery/package-budget.md) | [命名](references/delivery/naming-contract.md)、[发布](references/delivery/github-publication.md) |

## 制作顺序

1. **定输入与部位。** 核实型号、附件、材质槽、原生 UV、共享与镜像；按活动 BLK 的实际资源确定输入。先为首下车名、炮塔侧铭牌、顶部警示、车尾斜条板找好真实可见承载面，逐项决定 13 项部位与六区。
2. **清点原皮细节。** 在模型与原 C/N/AO 上找要保留、换色、提取重组或替换的小件。
3. **做无装饰底色。** 主体约 34，大斜切碎片浅约 64、深约 20–24，火控 26。隐藏蜂窝、贴纸、新增色标后整车仍成立。
4. **上三层装饰。** L1 纹样场（碎片、蜂窝主带、尾舱数码带、首上数码簇、防滑）→ L2 焦点（铭牌、车名、人字警示、车尾斜条板、炮塔大蜂窝）→ L3 小件（短横、缺口标、编号、刻度、NO STEP 虚线、原皮小件）。对照密度预算自查。
5. **分开做材质。** 蜂窝最轻、车体克制磨砂、炮塔略多金属感、火控最深最亮；镜片、枪体、枪托、炮管、备用履带、橡胶各自处理；去污保留磨砂。
6. **真实编辑与合成。** PS/Composa 分层、保存、导出、副本重开；Blender 可用时实际调用。本车计划 schema 3，`compose_native` 风格迁移 schema 4。
7. **最终 DDS 与交付。** 重绑实际 DDS 与全部 mip，远中近与转光检查；`vehicle_review --stage final` 与 `delivery_validate` 通过。游戏 ZIP <100,000,000 字节、解压 <200,000,000 字节；不保留涂装源码 ZIP。七视图逐次明确授权，日常复用本地预览。

开工时在本车任务里写设计记录：车型与附件；灰阶与碎片位置；纹样场分布；D01—D06 文字、依据、位置、朝向（不存在写替代）；材质分工与保护区；Z1—Z6 完成情况；最终 DDS、绑定、加载目录与游戏反馈。

## 机器规则要点

`vehicle_review` 按 [style-policy.json](references/data/style-policy.json) 强制：13 项部位必须逐项 `apply_default` / `adapted` / `not_applicable`，AZUR 默认（首上 `pixel_cluster`、炮塔侧 `rear_pixel_band`、炮管 `long_barrel_zone` 等）缺失时须写替代理由；图形角色 `honey_band`、`module_focus`、`warning`、`micro_accents`、`pixel_field` 必需，`circuit` 须附用户原话。字段见[制作契约](references/workflow/production-contract.md)与模板 [vehicle-review.template.json](references/data/vehicle-review.template.json)。

## 工具速查

| 阶段 | 脚本 | 用途 |
|---|---|---|
| 安装与素材 | `verify_release.py`、`asset_pack.py` | 安装包完整性；定位与校验素材包 |
| 范本 | `azur_reference.py` | AZUR 运行包身份与 13 项来源核对 |
| 部位与布局 | `native_carrier.py`、`carrier_visibility.py`、`layout_fit.py`、`uv_paint_scope.py` | 真实承载面、可见性、顶部图组预检、逐采样作用域 |
| 纹样 | `hex_surface.py`、`honey_field.py`、`panel_tones.py`、`net_pattern.py` | 物理坐标蜂窝场、灰阶板面、动态网布图案 |
| 合成 | `compose_native.py`、`basecoat.py`、`fixed_color.py`、`cutout_coating.py` | 原生 UV 合成、连续底色、固定漆面绑定、裁切件涂装 |
| 材质 | `material_parameters.py`、`hd_antislip.py`、`finish_hierarchy.py`、`satin_metal.py`、`optics_finish.py` | R/B 与微法线、防滑、材质层级、缎面金属、玻璃 |
| 检查 | `vehicle_review.py`、`surface_coverage.py`、`uv_coverage.py`、`surface_finish_audit.py`、`native_detail_probe.py` | 整车分阶段检查、真实面覆盖、左右对比、原皮见证 |
| 编辑器与交付 | `composa_mcp.py`、`editor_batch.py`、`production_tools.py`、`ground_dds.py`、`package_budget.py`、`delivery_validate.py` | Composa 调用与回执、DDS 导出、包体与交付核验 |
| 预览 | `tank_preview.py` | 单张 iso 检查图；七视图需本次授权 |

更细的工具与适用条件见[工具整合](references/contracts/tool-integration.md)。只关闭本批自有编辑器文档；未知 Shader 先核实，C 覆盖 Alpha、贴花透明度、玻璃/裁切 Alpha 与 N.A 数据分别保护；原作整车 C/N/AO 不跨车搬用；作品发布按本次授权。
