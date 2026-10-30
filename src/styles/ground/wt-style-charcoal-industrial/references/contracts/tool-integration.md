# 工具整合及仍需改进的边界

工具文件来自原分支，来源身份记录保留在开发仓库，未随安装包分发；不按版本号批量覆盖。非重叠工具保留原字节，两个实际重叠文件选用0.1.3的限定版本。0.1.4保留真实面蜂窝和成对材质审计；0.1.2保留色彩与UV覆盖检查。

| 情况 | 工具 | 使用条件 |
|---|---|---|
| 目标母版、用途与装备文字 | catalog_assets.resolve_asset、equipment_labels.check_label | 声明实际 unit_id、capabilities、approved_labels 与 label_evidence；不编造装备 |
| 固定颜色覆盖 | fixed_color.prepare/bind/check | 已验证不透明 shader 的漆面，镜片／裁切和共享像素另行保护 |
| 实际承载面、可见性、纹素 | native_carrier、carrier_visibility、uv_surface_map、uv_paint_scope | 真实几何、面清单、共享使用者；不是自动选好看部位 |
| 全面蜂窝与完整组件 | hex_surface、honey_field、native_components | 已声明真实表面、物理尺度、禁绘和共享面 |
| 连续底色与全车灰阶 | basecoat、carrier_color_audit、panel_tones、color_probe、uv_coverage | 具名漆面范围，不把案例31或24变成通用底色 |
| 去污、材质、光学 | surface_finish_audit、finish_hierarchy、satin_metal、optics_finish 等 | 每次显式选区与本车配方，不自动运行全部滤镜 |
| 动态网布 | net_pattern | 本车真实网布继承路径和共享基础迷彩已核实 |
| 带裁切Alpha的小件涂装 | cutout_coating | 枪体等裁切件：保持C.Alpha与打包N.G/A精确，R/B按金属/聚合物分别设定 |
| 源模型与UV对照 | source_model_uv | 研究原作时按BLK与材质槽建立模型↔UV对应；目标车仍用本车材质来源 |

整合时查出 `style_quality.authorize` 已支持目标车型，但 `compose_native.load` 没有传 `profile`，且仍只认 catalog schema 2。候选改为接受 schema 2/3、按显式 evidence_path_base 定位证据，并把已由 profile_sha256 冻结的 profile 传入语义检查。新增集成回归以真实 catalog 和带标签素材走完整 load，确认错误车型被拒绝、正确车型可用。

这是对调用链的修正，不表示现在有通用自动生成整车能力。旧的底色、哑光、抛光及玻璃函数是可选低层工具；API 成功不证明选面、美术或游戏通过。mixed-use 纹理的 Alpha 像素分区、实际 shader 与材质上下文仍由 profile 和制作检查明确，不能绕过它们全图运行固定覆盖。
