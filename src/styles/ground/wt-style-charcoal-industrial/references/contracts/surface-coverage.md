# 真实面覆盖与共享使用者

surface_coverage按UV纹素中心逐面重心插值，不使用全车覆盖率、质心或包围盒替代部件。输入是同一纹理全部原生使用者的三角面与UV，保留真实面序号；无需改模型或UV。

coverage记录字段：
- id、texture、layer_role(honeycomb/decal/base_paint/antislip)、mode(full_surface/partial)。
- geometry: 有哈希的NPZ，positions形状N×3×3、uvs形状N×3×2。UV是原生0..1/平铺坐标，图像原点在左上。
- binding_evidence: 有哈希的材质/使用者清单；all_texture_users_included必须true。工具不会凭空发现未提供的模型，清单完整性仍由实际绑定证据负责。
- paint_mask: 图层计划覆盖或最终实际覆盖，原生尺寸L8二值PNG及哈希。不要用渲染颜色反推覆盖。
- face_groups: 每组id、role、faces（完整实际面索引）、evidence（分类依据）。所有提供的面必须恰好分类一次，包括保护和共享使用者。
- target_groups: 本层完整目标部件；accepted_shared: 额外受影响组ID→具体外观接受理由。不是全局accept_shared=true。
- 合法面角色与装饰适用范围来自style-policy.coverage。蜂窝不会因共享被“接受”到玻璃、百叶或设备工作面。

    python -B scripts/surface_coverage.py coverage.json --out coverage-check.json

full_surface漏一纹素也失败；每个目标面无采样也失败，需提高采样或明确重新划分实际承载面。partial允许局部图形，但越界、未映射或影响未批准共享者仍失败。退化/跨度过大的UV不再静默跳过。这里检查的是最终网格可采样的真实面，不能代替离线/游戏的抗锯齿、mip边缘观察。

窄压条、折边、框条应单独分组，报告各组样本和遗漏数。不要侵蚀遮罩“解决”冲突；先核实所有共享者，改实际布局或作本车明确取舍。不要把百叶叶片和它外面的实心框当一块面，也不要把“APS整组保护”当作后续所有壳体都不可改的永久禁令。

uv_coverage现检查保护区、可编辑区外、Alpha与未批准共享区的任何变化。缺共享mask不算通过；CLI允许--scope-record重新执行真实面审计，mask必须与本次编辑范围一致。vehicle_review的final入口汇总已通过覆盖声明并检查实际最终C及N。

全表面指该层声明的实际承载面。稀疏铭牌/微色标用partial；完整蜂窝板面若含透明间隙，应将底色与图形的实际作用域联合检查，不能把几根线的Alpha宣称为完整板面涂覆。


非目标面零中心采样时，也检查其包含1纹素线性过滤余量的保守UV足迹；与涂装相交则失败，不把极小玻璃/开口视为安全。此规则仍不是全部mip过滤无泄漏证明，最终DDS各级边缘保持单独检查。


## 原生退化面与共享冲突

A7HU真实同图原始面有267个UV塌缩项，原版无差别终止，无法审到贴纸。现在保留全部face ID，分别报告non_rendering_native_faces、collapsed_uv_native_faces；非目标塌缩UV仍以保守采样/过滤足迹检查与墨迹的关系。无影响可以继续，有影响明确失败。目标UV塌缩不自动推导可画范围。

完整面检查报缺失时，同时看未批准共享与有意保护；A7HU的931个火控样本同时影响其他UV使用者，直接补齐会误涂。不能把每个缺失数都解释成肉眼漏点，也不能用侵蚀mask或降低门槛掩盖冲突。

保护角色新增working_face，用于已实际核实的设备工作面，不通过节点名字自动生成分类。
