# 原生 UV 接口

`compose_native.py` 接受两个 JSON：实际车型 profile，以及冻结该 profile 哈希的设计计划。路径分别相对于各自 JSON。脚本只写新目录；原 C、N、AO、模型都不改。它验证输入和合成，不自动判断你标注的语义是否正确。

## profile（schema_version = 1）

- `vehicle`：精确车型与附件状态。
- `uv_evidence`：本次核实模型、UV 与实际表面的记录位置/身份；不能填“同家族应该一样”。
- `textures`：以安全 ASCII ID 为键的映射；每项有 `file`、`sha256`、`alpha_semantics: fixed_rgb`、`color_space: srgb`，以及 `paint_mask` 与 `protected_mask`。两个 mask 均是 `{file, sha256}`，必须为原尺寸 L 模式二值 PNG，白代表允许绘制或禁止绘制。允许区域最终为 paint 减 protected。
- `surfaces`：每项 `id, texture, role, polygon_px, verified, evidence, sharing, rotation_deg`。polygon 是原生像素坐标凸多边形；凹形拆成子区。坐标从左上角起，x 向右、y 向下。`verified:true` 是执行者确认及证据声明，不是脚本从布尔值证明真实模型正确。
- `sharing`：`unique|repeated|mirrored`；后两者必须提供 `peers` 列表。文字图形不能投到 mirrored 表面；重复面须显式同意全部受影响部位。
- `rotation_deg`：0/90/180/270，Pillow 逆时针。它表示从素材正向到当前 UV 岛的旋转；平面透视由计划四角完成。

## plan（schema_version = 2）

- `profile_sha256`：整个 profile 文件的 SHA-256；修改 profile 后必须重冻计划。
- `catalog` 与 `catalog_sha256`：冻结统一素材索引。
- `placements`：每项含 `id, surface, asset_id, kind, asset, asset_sha256, quad_px, reason`；ID/用途/像素哈希必须与索引一致，trial_eligible 必须为true。
- `quad_px`：顺序为素材旋转后的左上、右上、右下、左下四角，均为目标原生图像像素坐标。必须严格凸且不退化；它表达已测量的平面 UV 对应，不是物理尺度自动识别。
- 可选 `opacity`（0 到 1，默认 1）、`accept_shared`（确认全部共享部位）、`allow_clip`（明确允许按表面裁切）。裁掉 2% 以上 alpha 覆盖且未显式允许时拒绝输出。此 2% 是合成诊断阈值，不是美术质量标准。
- 素材只用 PNG 等实际图片；SVG 先根据当前编辑版本栅格化。使用包内原图提取 PNG 时记录其哈希。

纹理最长边最多 8192。遮罩与纹理原尺寸一致；路径哈希变更、未知 alpha、未核实表面、镜像文字、非凸四角、覆盖越界或覆盖为空会失败。输出采用暂存目录提交，失败回收本次暂存，不修改已有输出。

## 输出

- `layers/`：各模块独立透明 PNG，供编辑器导入。
- `colors/`：合成后的完整 RGBA；源 A 逐像素保留。由于原游戏颜色 A 可能为零，普通图片查看器可能显示透明。
- `preview/`：仅供查看的 RGB 副本。
- `composition.json`：输入哈希、覆盖率、Alpha 与保护像素检查、范围说明。

固定颜色合成读取独立 RGB，再恢复原 A。贴纸透视滤波使用覆盖 Alpha 预乘，避免透明边缘色污染。材质图不进入此合成器；实际不透明/裁切颜色、AO/打包 N 采用随包工程工具各自的数据语义。

## 接口能力边界

一组贴图/遮罩通过接口不意味着整车已完成；缺少侧裙、炮塔或其他主区域时仍需制作。工程合成测试不是跨车型视觉测试。用户指定车型后应重新测量 profile，不从本包复制示意坐标。

文字身份从素材索引读取，调用者的 text:false 不能豁免。含字素材要求 surface.planar:true、text_height_px 至少8个最终纹理像素、禁止镜像与裁切。阈值只拦截明显不可读缩放，最终可读性仍看真实模型。

## 当前默认意图及细节预算

schema2计划增加intent（省略时style_transfer；像素复刻必须显式source_reproduction）。风格模式还会核对allowed_modes、源表面残留分类、干净图形检查证据及哈希、native_detail_size与critical_features。quality_budget可显式设置min_line_px/min_text_cap_px，默认工程试算值为2/12个最终纹理像素。检查基于有效尺寸而非PNG画布，采用透视变换5×5网格的局部最小缩放估算；不构成视觉质量保证。

完整原作C裁片、未经检查的AI元素在默认风格模式会拒绝。自编生产脚本同样先调用style_quality.authorize及check_detail；不得绕过该门槛再称已完成风格迁移。新检查未重新评测旧整车，不能把旧31项与新17项简单合成一个完整视觉分数。


## 0.1.1 模型＋UV 对照契约

计划必填 source_study: {file, sha256}，指向 schema_version=1 的原作研究。研究含 source_identity.vehicle、source_model 和 material_binding 文件/哈希，以及非空 regions。每个 region 有 id、state:checked_local、semantic_role、observed_parts、resource、source_texture/model_view/uv_view 的文件/哈希、uv_region 的 image_size 与 box_xyxy（image_pixels_top_left）、orientation/sharing 的已核对状态、sharing.kind 和具体 observation。model_view 与 uv_view 不能使用同一张图冒充两面观察。

放置项增加 source_region 和 target_correspondence: {surface, role, reason}；surface 必须与放置项相同。缺模型图、缺 UV 图、输入哈希变化、坐标越界、朝向/共享未核对、未知源区域或没有目标适配理由时，合成器拒绝输出。检查器只核对这些证据存在且身份一致；语义仍由模型＋UV 人工观察确认。

## 合成A与最终覆盖分开

合成保留源A用于来源检查；不透明固定漆面最终须按[color-and-material](color-and-material.md)确认shader并准备完整覆盖，不能直接沿用A=0。alpha-test材质和打包N.A不适用这项处理。

## 合成A与最终覆盖分开

合成保留源A用于来源检查；不透明固定漆面最终须按[color-and-material](color-and-material.md)确认shader并准备完整覆盖，不能直接沿用A=0。alpha-test材质和打包N.A不适用这项处理。
