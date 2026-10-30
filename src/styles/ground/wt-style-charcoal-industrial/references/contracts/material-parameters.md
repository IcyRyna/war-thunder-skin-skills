# 材质参数与实际应用

style-policy.json是默认值的唯一入口。A/B/C/F为漆面颜色角色；材质角色独立，不能用某个灰值代替粗糙度/金属度。主体、蜂窝、火控、炮管、机枪金属、枪托聚合物、备用履带、玻璃、橡胶、网布、防滑各自有决定。

body/honey/fire_control/barrel/gun_metal/gun_polymer/spare_track/antislip需要喷涂时明确本车C颜色与N.R/B；没有跨车固定R/B表。packed_n_semantics必须与实际目标验证一致（R=inverse_roughness,G=normal_x,B=metallic,A=normal_y）。其他shader不用这条应用路线。玻璃/橡胶/网布保留原生并使用原有专用工具，记录其真实修改范围。

## 参数化防滑

候选默认C=27/27/27，R中心48、B128、颜色噪声1.3、坡度RMS0.22、Gaussian sigma=1像素。R/B只是素材起点，不能直接视作每车通过。方片/长片/窄条均已在候选中按原尺寸重新生成。

    python -B scripts/hd_antislip.py generate --preset square --out NEW_PATCH
    python -B scripts/hd_antislip.py generate --width 768 --height 384 --color 31 31 31 --inverse-roughness 55 --metallic 72 --grain-mm 4 --texels-per-meter 1000 --slope 0.18 --out NEW_TARGET_PATCH
    python -B scripts/hd_antislip.py verify NEW_TARGET_PATCH

grain-mm定义为2倍Gaussian sigma的特征直径；与实际N承载面的texels-per-meter相乘换算像素，不与--grain-px同时使用。required-mip默认0：要求该级仍有至少2像素特征直径；远处mip细颗粒正常消退，不承诺1×1仍有颗粒。显式提高required-mip时必须重新选择尺度。输出附前4级衰减诊断，最终仍检查压缩DDS。偏色必须显式提供tint-reason，不能把25/27/29作为中性灰。

color.png、coverage.png、normal-rgb.png、packed-n.png来自同一高度场；N.A从不承载透明度。生成器输出同一网格。目标C/N尺寸不同时，必须由同一场按通道重采样或使用已有显式重采样工具；不能以不同尺寸/种子各生成一次冒充同一颗粒场，也不能普通RGBA缩放N。法线旋转/镜像须同步变换向量。

## 应用R/B与微法线

material_parameters.apply_parameters(native_n, mask, material_record)只改指定区域R/B，保留G/A和外部精确字节。可另传detail_normal（RGB8切线法线）和detail_coverage（独立L8覆盖）进行RNM混合，保留底层结构朝向。细节覆盖不得超出材质mask。

    python -B scripts/material_parameters.py material-apply.json --out NEW_PACKED_N.png

记录文件包含native_n、mask的file/sha256，material对象（同vehicle-review格式），可选detail_normal和detail_coverage。工具不自动改变C，不经Alpha透明合成N，也不改几何。颜色层在编辑器/现有精确脚本中独立合成。

vehicle_review --stage final从实际解码N检查R/B、微法线变更范围与遮罩外字节。目标压缩产生的真实误差要按通道核实并选择可保持约束的格式；不得仅为通过检查放宽全图G/A或把有损变化声称为原样。


R/B除中位数之外逐像素检查偏差，默认每通道最多5。确有颗粒粗糙度波动时在material记录中写variation（R_max_delta/B_max_delta）及variation_reason，每项上限64，仍不容许超范围异常像素。不要通过巨大容差掩盖错材质；不同表面应拆成对应材料范围。


## 制作、编码和目标网格

材质的color_mode=paint_roles时显式引用A/B/C/F，不再携带未使用的color_srgb；uniform中性/有意色调则检查实际C样本。preserve必须核对真实资源或区域，不会跳过已有变化。

final_samples.uv_mapping必须明确same_native_uv或independent_uv；后者提供独立normal_coverage。C/N可以不同分辨率，报告记录各自实际尺寸，不能隐式复用不相干UV。

material_grid.transform_packed在旋转/镜像图像时同步变换G/A向量；conservative_mask保留任何参与下采样的细边或保护样本；downsample_patch使用独立coverage加权R/B与法线向量，不把N.A当透明度。它拒绝扩大低清细节与静默各向异性拉伸。实际UV切线手性仍以本车原生数据核实，不盲目翻转。

制作阶段比较baseline与canonical，要求范围外和结构通道精确；实际DDS相对canonical的有损误差在runtime_textures.encoding中逐通道、逐mip单独验收。不要把量化变化写入micro_mask。字段见[runtime-and-delivery-contract.md](runtime-and-delivery-contract.md)。

## 先选部件材质，再选本车参数

各部件该读成什么见[材质观感](../style/material-looks.md)；已用数值也在那里，只作起点。reference_contract.masked_gloss必须显式传factor和ceiling，保留遮罩外与G/B/A精确字节。

按[材质与部位表](../style/part-recipes.md)区分主体涂层、次级盖板、蜂窝、深色火控、玻璃、枪钢、聚合物、防滑、网布、备用钢件和灯/反光片。相同灰色也应通过高光、微结构和真实结构形成不同材料读感；不能仅为“有区别”给每个零件都调成银色。

原皮小字/色标通常属于薄印刷或涂画，默认主要改变C，不自动给它们凸起、金属边或浮雕法线。原生金属铭牌、刻字、镜片、胶圈与反光材料另按实际部件处理。用于保留的N.G/A和AO不经过全局去噪；原生印刷细节的复合见[原皮细节复用](../workflow/native-skin-detail-reuse.md)。

同一body或root材质里可能混有灯/反光小件、胶圈与金属。按节点名找lantern、按原C明度找recess/rubber只能生成待检查的候选，不能直接确认为材料边界。已识别的特殊小件须同时保护相应C与R/B；honey_exclusion只排除蜂窝，不会自动阻止底漆、数码块或全图R/B覆盖。G/A精确保留只说明这两个结构通道未变，不能推断颜色与表面材料未变。

全图R/B有多个峰值也不等于逐部件分工正确。把实际材质面组与样本对应后，才报告哪一处是主体涂层、钢、橡胶或光学件；未完成的归类继续标为未核验，不用更换整车统一参数来掩盖它。

## 修复旧工程中过度统一的材质

先比较现用N与原N，区分需要撤回的整片R/B覆盖和仍有效的局部材质、结构法线、防滑微法线。仅恢复需要修正的通道与部件，不把已有有效微法线或用户指定火控材质一并清掉。

当已确认原生G/A仍完整、问题来自全图R/B统一赋值时，可从原N建立本车材质基线，再仅对经过模型确认的装甲/护罩面应用涂层参数；轮胎、钢件、布套、卡箍、内部机构和其他原生材料保留自身区别。轮履、网布、玻璃等独立资源继续用原资源，不为了让报表“全部有改动”而改写。需要重着色的小件可在C单独处理，不要求其R/B也全换成主体值。

连接部件必须展开为完整面组，分别在C/N自身网格栅格化。共享UV同时被非涂层部件使用时保留其原生材质，或明确选择双方都成立的共同材质；不可只取栅格最后一个面。检查结果应能说明每个纹素属于哪条处理路线，最终解码图的保留区域与原数据精确相同，改漆区域符合所选参数。

