# 原生 UV 与面积检查

**绘制。** 矢量、人物、文字先按图表顺序和原生三角形解决共用纹素，再按层顺序合成。即使在同一图表，图像、文字与矢量也只能写入胜出三角形的纹素；`shared-within-chart` 标示同表内实际重叠面，普通共边本身不算镜像共用。保护使图元无法落位时，在模型检查另一侧后调整载体，不靠叠层或调整图元 ID 过检。机械罩对蒙皮、独立图层和向岛外的扩色均有效。回执的 `candidate_samples` 是图元在实际三角形上的正 Alpha 子采样事件数；`protected_samples`、`nonowner_samples`、`sample_hits` 分别记录保护拦截、表面归属拦截和进入合成的样本。三者之和等于候选数。同一纹素可以含多个样本；每层最终有色纹素见 `layers[].painted_texels`。原厂数据 Alpha 与绘制层的透明度独立：保持同尺寸源 Alpha，改变尺寸时按数据合同最近邻；RGB 混合按绘制层的覆盖率。扩色不能越过保护罩或从贴图一边回绕到另一边。

**可见方向。** 原生 frame 或双面图表没有明确观察方向时，默认分面是诊断近似。跨模型高度零点的大岛可能把真实机背错报成遮挡。用 `surface_map.py ... --chart dorsal --view-from dorsal=y` 明确从模型 +Y 看；实际轴以目标机为准。该选项只改变可见性检查，不改变设计、三角形归属或图层。工具在两种三角绕序中取向该侧最近的表面，包含双面遮挡；游戏材质剔面／透明度仍需实模核对。同面确实有双侧职责时，从两边各检查，不能取较好的一面作整组结论。

**承载。** `surface_map.py` 的图按物理投影显示，在每个可见位置取原 UV 及实际图表归属。原生 frame、旋转、翻转、裁切、Alpha、局部淡出、图元孔洞和 clip 参与检查。绘制与检查应传入相同尺寸的 atlas 和机械罩。分区图以 `--scale` 个像素/米采样；需检查几像素的断口时，配合原尺寸局部和真实模型。动画铰链和游戏 LOD 另行核对。

要单独检查一双眼睛、角尖或字标，在设计顶层添加 `inspection_regions`。每一项指向对应图表内唯一的图像／文字 ID，框在裁切后的原图坐标中归一化，左上为 (0,0)，随同主体翻转和旋转。

```json
{"inspection_regions":[{"chart":"left-wing","item":"portrait-left","name":"eyes","box":[0.36,0.22,0.60,0.33]}]}
```

整幅人物可以沿真实翼缘裁切。重点框按实际非透明部分单列，检查接缝并报告落在表面外、共用 UV、保护区及遮挡区的比例。扩大 `--scale` 复核极小重点框。`seam_pixels` 与 `seam_area_m2` 是接缝交集在当前投影中的像素数与面积。旧报告的 `seam_length_m` 用像素数除以比例，仅供旧阈值比较；缝宽会影响这个数。重点框命中一个接缝像素便单列。

**面积。** 在同一视角、同一模型遮罩下选择一种来源：

- 有逐像素角色标记时，使用 `airframe_setup.py shares --views V --roles R --view top`。每张 `R/<视角>-roles.png` 为 L 或 P 索引图，与同视角渲染同尺寸。0 其他／待分配、1 炭灰、2 签名色、3 淡染、4 白、5 人物、6 机械。人物与机械优先使用图层标签。
- 有原 UV 分层时，可用 `--layer-roles roles.json` 直接投射到现有视图的可见三角形。配置格式为 `{"geometry":"flight.npz","atlas_materials":["body"],"layers":[{"role":"signature","mask":"wing-field.png"},{"role":"portrait","mask":"art.png"},{"role":"mechanical","mask":"protected.png"}]}`，相对路径以该配置为准。取 L 或透明图的 Alpha，默认阈值 128，每层可设 1–255；用可选 `exclude_mask` 指定同尺寸 L 罩，排除后续已还原的下翼或其他区域。提供布局渲染同名的相机回执、深度／归属文件和模型遮罩；工具核对图像、几何、深度及相机指纹。
- 可同时传入 `--palette palette.json`；只给未标记像素匹配指定色板。独立色样写成字符串，连续渐变写成一组有序端点。未知色和超出匹配半径的颜色归入 other。单靠 RGB 无法区分同色的人物和蒙皮，此时报告注明没有角色遮罩。

```json
{"swatches":{"dark":["#333334"],"signature":["#219eaf",["#a5c69b","#dfd44f"]],"white":["#ececec"]},"max_rgb_distance":24}
```

用 `--legacy-f2a` 复算历史红色 F-2A 指标。面积命令只生成 JSON，支持重复 `--view` 和 `--out` 新文件。仅在用户明确授权本次七视图时使用独立命令 `airframe_setup.py seven --views V --out 新图.png`。

**风格意图。** `design_lint.py --design D --intent I` 接受只读意图文件，也可在设计中写 `art_intent`。示例：`{"signature_gradients":[["signature","gold"],["signature_deep","gold"]],"approved_echoes":{}}`。匹配的色相提示保留为 info，颜色端点改变或额外鲜艳色仍须复核。已有用户认可的细回声可把提示给出的 SHA-256 按图元 ID 写入 `approved_echoes`。指纹绑定实际图元及图表；改孔洞或 frame 会恢复警告。只有已获认可的具体轮廓才使用该例外。

**DDS。** `legacy_dds.py` 面向指定的传统头单层 BGRA8 导出，核对全 128 字节头和源图 RGBA，在同盘暂存和回读均成功后提交。一般格式、其他 mip 和历史编码使用 `inspect_skins.py` 或对应格式工具。游戏加载仍以实机为准。
