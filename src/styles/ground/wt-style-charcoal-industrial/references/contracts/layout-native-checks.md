# 原生布局检查：实际墨迹、载体、尺度与遮挡

layout_fit用于首批布局预检。每个顶警示实例独立绑定真实模型、载体、源图、局部轴、中心、尺寸、旋转和可见性；base/final实际调用。

roof_warning提供required_instances和placement_checks，两者ID集合相等。每个placement有：
- source_model_sha256；
- geometry文件/哈希与完整原始faces；
- frame的origin/u/v，轴为正交单位向量；
- center_uv_m；
- graphic_size_m：旋转前物理宽高；
- rotation_deg、minimum_margin_m；
- target_fill的min/max/reason；
- visibility：绑定当前源与布局的实际墨迹样本证明。

## 透明墨迹与实体矩形

mode=actual_ink从asset的真实RGBA Alpha投影墨迹，不把透明画布当墨迹。必须有scope_polygon_uv_m和depth_interval_m：前者是独立核实的物理部件边界，后者说明真实支撑起伏。

10式的约9毫米沟槽说明，墨迹可能落在下层真实支撑面。可以纳入这些面，但必须保留盖板clip，不能将整块下层屋顶无限授权。边界不得从“想让图形通过”的范围反推。

mode=solid_rectangle仅用于真正实体矩形，按平面三角形交集检查。不能用于大量透明空隙图形，否则会误报跨缝或小沟槽。孔洞、紧固件、保护区仍由实际原生覆盖审计负责。

## 尺度与可见性

主panel-group警示起始检查采用填充下界25%、可见墨迹95%，用于防极小图组或严重遮挡；不是所有车型的美术定律。
- 更小图组提供target_fill.smaller_group_basis的本车理由和冻结证据，不靠把min随手改0.01绕过设计。
- 遮挡取舍用visibility.accepted_occlusion的具体理由和当前目标证据；已有明确选择可沿用，不重复问用户。
- 几何通过不等于字自然，12px纹理字高不代替常用模型视距阅读。

visibility.probe由实际模型工具产生，含：
source_model_sha256、geometry_sha256、frame、asset_sha256、center_uv_m、graphic_size_m、rotation_deg、ink_samples、visible_ink_samples。
任一身份、轴、源图或布局不同即拒绝。样本来自真实墨迹，不是空白矩形；记录遮挡物、相机/姿态与采样方式。rc3从绑定的完整场景重新计算计数，旧外部计数仅作比对；详见[schema 3契约](schema-3-contract.md)。

旧手填carrier_size_m/graphic_size_m/margins_m不再作为技术通过依据。多个图组分别给真实实例，不能用一条“顶部完成”覆盖两个不同载体。标签资格、原生UV投影、数据通道和最终DDS仍走各自检查，本入口不替代它们。


实际图组填充按非零Alpha内容包围范围计算；透明画布留白不计入图组尺度，不能扩大PNG空白让小字标冒充大警示。分母始终来自完整原生承载面的投影面积。scope_polygon_uv_m只限定允许墨迹位置，不能作为“整板填充”分母；缩小scope不会提高carrier_fill_fraction。canvas_fill_fraction与scope_fill_fraction仅作诊断。

用户要求占满/铺满某块板时，先以模型完整面组和用户圈定固定范围，不得因图形难放而改小faces或边界。在该placement增加composition_requirement，例如basis="complete_native_carrier"、min_span_fraction=[0.90,0.85]和本车reason，分别检查两个板向的实际墨迹延展。比例按本车选择，不是所有车型的固定门槛；只增加角落小点也不能替代真实构图的视觉检查。

先保证核心文字可读，再处理非文字装饰的自然遮挡。明确要求整板构图时，可用既有accepted_occlusion绑定当前请求与具体设备遮挡取舍，让斜条延展到设备下方；这不自动允许文字被挡，也不是全局降低可见率。

投影到贴图与可见性测量必须使用同一坐标约定。ink_points将图像顶端映射到局部+v；image_coordinates是其精确逆变换，输出左上原点图像UV。不要在实际绘制中误用v/height+0.5，导致验收与落图上下相反。

文字的frame还须面对真实承载面的正面：u叉乘v应与实际三角面绕序的法向同向。反向基准即使正反变换完全互逆也会镜像字形，含文字的布局会拒绝这种frame。修改轴向时同步变换中心和边界坐标，再重算探针；最终仍查看模型字形朝向。


rc3另要求contains_text、实际core_text_mask、text_region_evidence及visibility.scene。整体与核心文字分别核验；附件状态、节点显隐、变换和相机全部进入场景身份。
