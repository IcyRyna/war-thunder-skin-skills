# schema 3：原生面、通道、场景和实际输出

本契约自0.1.6起使用，0.2.0沿用。本车 manifest 使用 schema_version=3；compose_native 计划仍为 schema 4。旧 schema 2 用 migrate_manifest.py 读取或转换，缺证据保留 requires_evidence，不产生通过记录。

## 模型与覆盖

model 必须是本次实际 OBJ、GLB 或原生几何 NPZ。Blender工程先显式导出实际模型，不能把任意文本当作几何。OBJ保留三角化、材质名和原生UV；GLB读取实际场景节点变换、材质和纹理UV通道。带骨骼、形变或尚未支持的纹理变换先冻结为有来源的实际状态。

bindings.resources 中 users 是实际模型中的材质名称。未被实际几何使用的材质定义单列记录，不冒充现用面。每项 resource 绑定 role、shader、alpha_semantics、color_space。

coverage 增加 native_resource。geometry NPZ 具有：
- positions：N×3×3；
- uvs：N×3×2；
- source_face_ids：N个整数，顺序等于该实际资源的全部原始使用面。

入口重新解析 model，将覆盖文件与实际原始面、坐标、UV逐项比较。不得删掉共享者、退化项或沿用旧文件的面号。导出器：

    python -B scripts/native_inventory.py vehicle.json --resource body_c --out body-native.npz

历史网格若面数或顺序不同，按原始坐标、UV、材质唯一匹配，保存对应表；不按固定偏移猜测。rc3实际A7HU核对中，旧NPZ为260,984面，OBJ为260,995面，旧面号不能直接使用。

## 每条修复绑定实际资源

channel_repairs保留六类通道决定。每个非absent的decision增加runtime_texture_id，必须匹配通道角色：
- C_RGB、C_A → color；
- N_R、N_B、N_GA → normal；
- AO → ao。

before必须是该运行资源的baseline，after必须是canonical。reference/constant/not_written的原目标验证继续执行。多个修复对同一资源/通道可使用同一个真实before/after及各自局部mask；局部目标分别检查，范围外保护按所有modify/restore范围的并集检查。preserve只检查本条局部范围，不能掩盖其他实际改变。

absent需native_users和原生依据，并检查这些材质的实际槽中确实没有该角色。不能用一句缺失说明跳过真实存在的AO。

## C/N完整物理范围

每个paint材质增加surfaces，每项包含id、coverage_id、group_ids、color_resource、normal_resource。color_samples和final_samples均用surface_id绑定；每个surface恰好一份C样本、一份N样本。N样本还绑定runtime_texture_id。

C预期范围来自真实面在C网格的栅格化，仅减去已经由实际图层证明的装饰。N范围来自同一原生面在N网格的栅格化。两个遮罩不要求像素数量相同，但不得各自只挑合格像素。

independent_uv仍提供normal_coverage，并检查其完整源面与实际原生N UV。不能用另一组外观相似的面代替。资源、面组重复归属和孤立样本均拒绝。

preserve_runtime_ids继续用于完整未修改资源。区域preserve_samples除了runtime_texture_id、mask，还需coverage_id、group_ids、native_resource；遮罩必须等于完整原生部位范围。

## 字高与细线

critical_features单位固定为源图画布像素。native_detail_size可以记录有效内容，但不参与替代整张PNG画布的投影比例。

实际生产图形提供feature_regions，例如：

    "critical_features": {"text_cap_height_px": 18},
    "feature_regions": {
      "text_cap_height_px": {"bounds_px": [100, 0, 122, 18], "axis": "y"}
    }

bounds_px使用左上包含、右下不包含的源画布整数坐标；axis给出测量方向。区域应选真实代表字形/细线，尺寸与critical_features一致（半像素测量允许至多0.5源像素的离散包围差），不能圈透明留白。检查器核对实心墨迹、与合成一致的旋转/透视映射及实际落地像素。普通仿射使用精确奇异值，透视使用全画布保守下界，避免仅5×5采样漏掉极端缩小。保守拒绝时重新排版或提供更合适源图，不下调12px文字、2px细线底线。

## 遮挡与核心文字

placement继续绑定源图、实际载体、原生面、局部轴、中心、物理尺寸、旋转和独立物理边界。新增：
- contains_text：严格布尔；
- core_text_mask：有文字时，从源图实际Alpha选择核心文字；
- text_region_evidence：绑定asset_sha256与mask_sha256的文字区域核对；
- visibility.scene：冻结场景JSON及哈希。

scene包含schema_version=1、model_sha256、attachment_state、pose_id、lod、完整nodes和camera。每个原生节点恰好一条id、visible及4×4矩阵；不能漏掉挡住文字的附件。orthographic相机指定direction；perspective还需position、up、vertical_fov_deg、aspect。

探针使用全部实际可见三角形和BVH，对源图全部非零Alpha像素投影后计算首次命中；最终入口再次计算。计数或scene哈希不一致即拒绝：

    python -B scripts/visibility_probe.py vehicle.json --instance upper --out roof-probe.json

整体墨迹和核心文字分别统计。accepted_occlusion只说明整体遮挡取舍；核心文字低于门槛需要单独accepted_text_occlusion及真实当前依据，不能用斜条的可见性替代文字。

当前探针是冻结三角形场景的几何检测；不把它表述为游戏shader、透明裁切或动态动画验证。

## APS、观瞄、传感器

classification_evidence增加unit_id、model_sha256、equipment_source_faces和components（类别→实际源面ID列表）。从design阶段核对身份和分类范围。未知部件不能填成已确认外壳。

final从这些原生面计算所有实际运行C/N/AO范围，逐像素验证preserve组件保持不变，并拒绝其上新增装饰。工作面必须保护，机构涂覆保留原依据要求。脚本检查分类与结果一致性；功能识别仍需模型/实际资料证据。

## 编辑器合成与DDS

默认C合成逐像素精确。Composa 1.4.0实际回放发现炮塔3,202个半透明边缘像素与Pillow相差1阶。只有显式compositing.mode=composa_normal_u8才采用这项兼容合同：
- receipt绑定全部实际层RGBA哈希、canonical哈希、真实保存和重开导出；
- 只允许最终仍受非零非255图层Alpha影响的像素；
- RGB每通道至多1阶，Alpha精确；
- 最后被全不透明图层覆盖的区域恢复精确；
- 保护区和N/AO仍执行原有逐像素精确要求。

严格DDS支持单张2D DX10 RGBA8、BC3、BC7及相应sRGB标签，逐实际mip核对。fixed_rgb允许合法OPAQUE元数据，但必须证明所有解码Alpha都是255。N/AO不接受OPAQUE标记。

BC7为实际离线验证补充：A7HU机枪C的BC3第3级mip出现69阶误差；BC7在保留Alpha255后最大RGB误差11。固定漆面BC7调用已锁定texconv并使用alpha权重1000，仍以逐mip结果决定通过；不可认为这一参数本身保证正确。该路线未声称已经游戏实装。

历史导入：

    python -B scripts/import_legacy_dds.py old.dds --out NEW_IMPORT --role normal --alpha-semantics packed_data --color-space linear

导入保留原文件，记录原全部mip和哈希，生成新的canonical及DX10语义mip；导入成功不代表包体或整车验收成功。块压缩采用原生分辨率，N/AO不能为凑体积牺牲通道精度。

## 验收与传输

开发仓库的回归覆盖原161项、rc3正反例及保留的真实小样本；rc4输入指纹覆盖脚本、测试、嵌套参考、规则、素材索引及实际图片和二进制小样本。回归与冻结工具不随安装包分发；安装后用verify_release.py核对文件身份，不能用旧证明锁定新代码。

本轮A7HU验证包含六份编辑工程、23个实际图层、13份运行DDS、完整mip、14个ZIP成员及一次本地模型查看。顶部遮挡、旧网格面号失效和梅卡瓦功能面证据缺口独立记录，不改写成整车美术通过。

每次对话传输小于16,000,000字节并留余量。大图、模型、源码和完整Skill包在本地读写，仅传必要报告和小图。



不透明底上的图案可用feature_regions内的selector={mode:rgb_equal,rgb:[R,G,B]}选择真实源色墨迹，检查器重新从源像素构造选择。18个可迁移素材的测量见feature-region-measurements.json；重建测量的开发工具不随安装包分发。
