# 制作契约与执行顺序

身份由VERSION.json提供，默认设计由style-policy.json提供。当前本车manifest为schema 3，compose_native风格迁移计划为schema 4。旧schema 1/2不直接当作当前通过记录，先补足实际输入；原工程与历史证据不覆盖、不伪造。

先读[AZUR主线](../style/part-recipes.md)与[部位默认](../style/part-recipes.md)，再读[极细制作检查](production-detail-checklist.md)。首下、顶部、机枪等13项默认设计仍有效；本版补齐的是实际状态、图层、通道、编码和交付之间的对应。

当前字段变化、逐通道资源绑定、原生面对应、重算遮挡和编辑器舍入合同，先读[schema 3契约](../contracts/schema-3-contract.md)。

素材先选[直接取用或AI按车型适配](asset-use-and-adaptation.md)：合适的现成图无需重做，不合适的图由AI自行调整文字、布局、外形、密度与材质，也可参考包内风格创作本车子版。正常适配不逐项询问。改变源图后在本车局部目录更新真实文件、哈希和测量，再进入同一合成与验收流程。

## 1. 决定本车具体做什么

- model和bindings均带file/sha256；unit_id、vehicle、attachment_state必须是真实目标。
- zones为Z1至Z6。每项写真实大几何、安静面、焦点、图案尺度、材质对比及coverage_ids；不按60/30/10机械评分。
- part_layouts有13项。apply_default采用默认元素；adapted逐项写replacements；not_applicable用实际缺失/当前用户要求证据说明。
- 首下身份绑定identity_unit_id和identity_text；顶部图组的graphic_size_m记录旋转前画布物理宽高；旋转后四角、余边与可见性由真实面探针重算；机枪housing/gun_body/stock/ammunition分别绑定面组或缺失依据。
- graphics每项有唯一id、role、layer_role、coverage_id、purpose。role说明风格职责，layer_role必须是decal/honeycomb/antislip，并与coverage一致。底漆许可不能借给装饰。
- 先给首下身份、侧铭牌、顶部警示留位置，再安排底色、防滑和小块。不要做完底材才发现贴纸无处可放。

## 2. 核实目标语义与标签

capabilities统一为名称→严格布尔值字典，例如{"ammunition_blowout_panels":true}；False不是确认。每个True有capability_evidence文件/哈希。

approved_labels是已核实的文本列表；label_evidence按规范化文本索引，每项包含：
- unit_id：目标单位；
- text：实际文字；
- asset_sha256：真正使用的图形字节；
- carrier：对应实际承载面；
- evidence：当前用户选择或真实设备依据的file/sha256。

label_text非空必须contains_text=true。BLOW-OUT及其大小写/连接符变体都要求本车能力为True；不因文本换了连字符就绕过。profile与vehicle_design的capabilities、capability_evidence、approved_labels、label_evidence必须一致，避免两份记录互相矛盾。

## 3. 底色与真实面

先完成[原皮细节识别](native-skin-detail-reuse.md)，再按[部位材质与装饰](../style/part-recipes.md)安排底层、主图、副装饰和小件。模板finish_plan/native_detail_plan记录设计取舍，实际结果落实到已有layers、coverage、materials和channel_repairs；这些新备注本身不是通过证明。

每张textures条目：
- id、base_c（无装饰的完整材质颜色层）、base_paint_mask；
- paint_regions列表：每项有唯一id、role=A/B/C/F、独立mask；可选本车rgb与override_reason；
- 原本没有中性漆的原生保留纹理可使用空paint_regions、全零base_paint_mask和no_neutral_paint_reason。

颜色遮罩从实际面选区产生，不能按“哪些像素看起来合格”筛选。base阶段检查中位数、偏色和局部离群像素，并要求角色并集恰好覆盖声明漆面。

coverage按[surface-coverage.md](../contracts/surface-coverage.md)提供同一纹理的真实面与全部使用者。full_surface零缺失；partial允许局部图形，仍检查共享污染、未知面、越界和采样。法线图不一定与颜色图同尺寸，N样本必须显式说明对应关系。

## 4. 材质计划与C/N网格

materials的每个角色有state：
- paint：本车R/B、已核实打包语义及证据；
- preserve：最终提供preserve_runtime_ids，或preserve_samples（runtime_texture_id和实际mask）检查对应原生区域不变；
- not_applicable：缺失原因和冻结evidence，不得再携带真实样本假装跳过。

paint的color_mode可以是：
- neutral/tinted：parameters.color_srgb必须对应实际最终颜色范围；tinted要有理由；
- paint_roles：parameters.paint_roles显式引用A/B/C/F，不再带一个未被使用的color_srgb。

paint材质最终有color_samples（texture、mask）及final_samples（N样本）。N样本包括coverage_id、before_n、final_n（实际DDS解码）、final_n_dds、mask、可选micro_mask，以及uv_mapping：
- same_native_uv：color_texture及本车UV对应证据，按同一原生面在N网格重新采样；
- independent_uv：另提供normal_coverage文件/哈希，不能用颜色UV冒充法线UV。

material_grid提供向量正确的旋转/镜像、不会抹掉细边的保守遮罩缩小、带独立coverage的法线加权下采样。禁止普通RGBA透明合成N、放大低清颗粒或静默各向异性拉伸。详见[材质参数](../contracts/material-parameters.md)。

## 5. 真实图层与合成入口

在PS/Composa完成真实分层、保存、导出、副本重开；Blender可用时实际完成目标模型/UV和最终DDS检查。工具职责与受影响阶段复验见细化指南。

compose_native schema 4在原字段上增加/落实：
- vehicle_design文件/哈希；
- profile.surface.coverage_id；
- 每个placement的graphic_id和layer_role；
- source asset的allowed_layer_roles；没有声明时仅按decal；
- profile与本车计划的语义信息一致。

check也实际投影贴纸，不静默裁掉越界/保护像素；文字默认至少12最终纹理像素，细线至少2像素，不能通过quality_budget暗中下调。旧8px是历史检查，不是本版准入。

实际最终textures.layers必须按合成顺序提供每层id、graphic_id、catalog文件/哈希、asset_id、asset文件/哈希、quad_px、rotation_deg、opacity，以及完整原生网格rgba图层导出/哈希。

final会重新投影源图形并比较实际图层字节、逐层按真实装饰角色审计，再由真实Alpha推导decoration_mask。预编码canonical C必须等于base_c加这些图层的精确合成。编辑器中修改了源图形时先更新为本车已审子版，不能借旧源哈希证明新图。

final_paint_regions每项用base_region_id回连原漆区，mask必须恰好等于该原区域减去实际装饰；不可删除B/C样本或拿一个巨大手写装饰mask遮掉偏色。

## 6. 制作精确性与编码误差分开

每个实际DDS均在runtime_textures中声明：
id、dds文件/哈希、role(color/normal/ao)、alpha_semantics、color_space、state(preserve/modified)、baseline（编辑前RGBA）、canonical（编辑完成、编码前RGBA）、encoding。

制作阶段：
- C的before_c到canonical：保护区/允许区外/固定Alpha精确不变；
- N的before_n到canonical：R/B在各材质范围内符合参数，非micro区G/A精确不变；
- preserve逐实际资源或区域检查原值，不再因名称是preserve就跳过；
- 改过的N必须有真正的材质审计；改过的AO必须有绑定该baseline/canonical的channel_repairs。

编码阶段：
- 实际DDS逐mip解码到1×1，拒绝截断、缺级、尾随载荷、错误sRGB/Alpha模式；
- 每级对照由canonical按真实alpha/color_space生成的语义mip；
- exact逐字节一致；bounded有冻结依据及RGBA每通道最大/平均误差，N另算法线方向最大误差；
- 有损量化不能当作修改过原生G/A，也不能靠扩大micro_mask掩盖真正改动。

实际支持的严格导出/验收DDS是单张2D DX10 RGBA8、BC3或BC7及对应sRGB标记。其他容器/格式不得因Pillow能打开就声称全链已验证；按实际支持的转换路线重新导出并检验，不改头伪装格式。

## 7. 运行绑定与最终ZIP

bindings是实际目标模型资源清单：unit_id、model_sha256、resources；每个资源有resource、role、alpha_semantics、color_space、shader、users。BLK的from资源与角色逐项对照此清单；目标DDS必须正好是受审资源。

final_runtime_files每项有file、sha256、package_path，包含一份实际车辆BLK、全部DDS及必要模型依赖。package_path是ZIP内位置，保持BLK相对目标目录关系。禁止少件、多件、重复路径和未审核DDS。

    python -B scripts/vehicle_review.py vehicle-review.json --stage design
    python -B scripts/vehicle_review.py vehicle-review.json --stage base --out base-check.json
    python -B scripts/compose_native.py check --profile vehicle-profile.json --plan design-plan.json
    python -B scripts/compose_native.py compose --profile vehicle-profile.json --plan design-plan.json --out NEW_COMPOSITION
    python -B scripts/vehicle_review.py vehicle-review.json --stage final --out final-check.json
    python -B scripts/delivery_validate.py --manifest vehicle-review.json --zip final-game.zip --out delivery-check.json

delivery_validate包含严格100/200MB预算、实际ZIP逐成员SHA、BLK与模型slot、所有DDS的角色和mip。package_budget单独通过只表示大小/容器检查，不代表交付身份已通过。更多字段见[运行与交付合同](../contracts/runtime-and-delivery-contract.md)。

## 8. 实际观察与旧图修复

final要求observation_matrix：交付状态、相关替代/运动状态、前后左右顶部及可见底侧、成对表面、动态图网布与可得LOD。checked必须有真实证据；无法检查的相关替代状态明确not_checked/unsupported，不冒充游戏通过，不要求穷举所有组合或新增七视图。

旧图清理用channel_repairs逐项决定C_RGB/C_A/N_R/N_B/N_GA/AO保留、恢复、限定修复或实际缺失。restore_from是旧效果加入前目标；before是本轮修改前快照，两者不可混淆。不得因清一条橙线全局重置N/AO。具体观察与返工办法见[极细检查](production-detail-checklist.md)。

## 安装包完整性

    python -B scripts/verify_release.py
    python -B scripts/verify_release.py --assets "独立素材包目录"

只核对本包文件清单、哈希与身份，以及可选素材包；不安装、不上传。哈希一致不等于美术认可，也不等于面分类或图案语义判断正确。候选冻结与回归测试属于开发仓库，不随安装包分发。


## 输入快照、顶部预检与通道修复


1. 输入有多份时，用input_snapshot按实际BLK目标比较，不把目录中的旧缓存当活动文件。只读dds_snapshot可核对legacy/BC7历史成品，不能把旧容器不支持等同涂装错误，也不因此跳过新交付的严格语义和预算。
2. roof_warning以required_instances/placement_checks代替手填余边：真实源Alpha、完整支撑面、物理部件clip、中心/尺度/旋转与有来源的可见墨迹计数。详见[原生布局](../contracts/layout-native-checks.md)。透明画布不能当实体矩形；下层大支撑面不能无限扩大载体。
3. 已确认APS必须填写sensitive_equipment，完整拆分casing/working_face/mechanism。每件有classification_evidence、coverage_id、equipment_group_ids，以及三个components。每个实际组件有group_ids与paint/preserve决定；不存在需证据。工作面必须显式保护；面组不能重叠、遗漏或全部冒充外壳。机器不代替功能识别。
4. surface_coverage保留退化项身份：真实3D的UV塌缩仍检查采样和过滤足迹，无交集不整批阻塞，有交集仍拒绝。目标自身UV塌缩必须解决，不能静默删面。
5. channel_repairs必须声明intent=remove_graphic/material_adjustment/diagnostic。remove_graphic的每个实际通道都需postcondition，before==after本身不证明旧残影消失。
6. postcondition可为reference（可信目标文件与容差）、constant（当前目标值及依据）、not_written（绑定removed_effect id/hash的真实写入谱系，证明旧效果未写该通道）。没有目标就保持诊断未闭合，不伪装为清理通过。

命令示例：

    python -B scripts/input_snapshot.py folder path/to/current.blk --out current-snapshot.json
    python -B scripts/input_snapshot.py archive old-game.zip --out archive-snapshot.json
    python -B scripts/input_snapshot.py compare archive-snapshot.json current-snapshot.json
    python -B scripts/dds_snapshot.py old-game.zip --member Exact/texture.dds --out historical-dds.json

输入快照不修改或部署文件。真实回归fixture仅供测试，不进入制作素材目录；不需要恢复已删除源码ZIP。

## 范本来源核对

vehicle_review各阶段核对reference_hierarchy与13项primary_basis的来源哈希，报告明确AZUR主范本与适配案例。局部数码块为可选元素，不能靠强制堆块填补大灰区缺失。

## 工具调用回执

生产交付必须按[工具调用与回执契约](../contracts/tool-execution-contract.md)提供production_tools schema 1。vehicle_review final仍是技术检查；delivery_validate额外核对真实编辑、保存、复制重开、导出、后处理关联和Blender执行/实际不可用证据。旧日志缺字段时据实转换或补做缺失步骤，不生成虚构成功记录。

预览默认单张iso；七张及以上需本次明确用户请求记录。渲染器source_face_ids用于追溯被略过退化面后的原始面身份，不能把导入器的数组下标当原生面号。Windows editor_batch固定UTF-8子进程日志，未知结果先读回执再决定，不自动重放编辑。
