# 喷气式飞机的原 UV 正交制作

流程为真实几何与原 UV → 配对参考 → 分方向设计 → 可见性回烘 → 实际模型检查。直接 UV 编辑可跳过投射；二维 atlas 本身不能恢复三维关系。

## 几何与资源

核对实际可渲染网格、节点／部件变换、原 UV 和材质，明确互斥挂载与静态显示状态。解包容器不等于网格或 DDS 已解码。

`surface_preview.py prepare` 从目标颜色资源筛选静态几何。解码器依次取 `--tools`、`WT_ASSET_TOOLS`、所属项目 `.skin-workshop.json` 的 `tools.asset_decoder`；相对路径以项目根为准，目录需含 `wt_assets.py` 和 `dae_backend.py`。解码器不内置，缺失时使用适用的已有 geometry.npz 或受支持入口。

NPZ 使用 triangles、uvs、node_ids、names，进入投射前校验形状、索引、数值和缩放参数。保留姿态、原装配坐标与材质关系。当前回烘只支持首个 0–1 UV tile，重复或跨 tile 输入会拒绝；静态 prepare 不模拟全部动画。

## 多材质整机场景与补充相机

`scene_preview.py` 保留座舱、喷口和附件的独立材质。prepare 读取标准解码目录的 parts.json、materials.json、逐部件三角 OBJ 与纹理，用 selection JSON 的 schema_version、description、include_nodes 明确真实节点选择。不要把互斥挂载叠在一起或按节点名猜状态。

```powershell
python scripts/scene_preview.py prepare --asset output/decoded-aircraft --selection design/scene-selection.json --out output/scene
python scripts/scene_preview.py render --scene output/scene/scene.json --view reverse-iso --mode layout --out output/scene-views/reverse-iso.png
```

输出逐三角 material_ids、material_names、资源槽、geometry.npz、scene.json 和 prepare-receipt.json。scene schema_version=1，材质连续 id/name 与几何对应，纹理及几何引用带 path/sha256，display_state 记录状态。selection 可按现有材质名覆盖颜色／packed 或显式常量代理；缺真实数据时保留 proxy 警告，代理不证明玻璃透明度或游戏材质。

标准七视图之外可用 reverse-iso、scene 命名 cameras 或 `--camera` JSON。相机提供 eye/up，按需给 fit_nodes、target_world、zoom、尺寸，或已确认的 basis/center/scale/width/height。局部相机只改变观察，完整场景继续遮挡。

场景显示可登记重复 UV，不增加回烘支持。完整场景的 depth/owners 不能配投射子集；为实际投射几何重新生成配对数据，不能只改哈希。

## 正交参考与绘制

```powershell
python scripts/surface_preview.py render --geometry output/geometry/geometry.npz --texture textures/body.tga --view top --view bottom --view left --view right --view front --view rear --view iso --width 2048 --height 2048 --out output/guides
```

参考、相机 JSON 与深度作为同组使用。schema_version=2 绑定完整几何 SHA256、basis/center/scale/画布指纹及深度 SHA256；深度 NPZ 保存逐像素三角形 owners 和身份。路径相同不代表内容相同，几何／相机改变或旧无绑定引导都需重建。

编辑器保留参考尺寸、位置与方向，隐藏底图和诊断层后导出透明设计层。提高分辨率从原素材和可编辑源按同一模型空间布局重建，并重配相机／深度；沿“原素材 → overlay → UV”检查有效局部采样，不能把插值像素数算作独立细节。先检查画布与内存边界，需要时使用已验证分块入口。

多方向稿为每块连续表面确定主导来源和承载域，用同一模型空间锚点核对色场与路径。重叠稿需表达一致设计，或按真实表面／遮罩互斥；各稿单独流畅不证明合成正确。圆周图表的角度轴与站位轴未必等物理比例，旋转文字前先补偿局部尺度。

承载遮罩按真实可见表面建立，不把三角边、节点名或粗选区当设计轮廓。出现源矢量没有的齿边、台阶或假孔时，先查 carrier alpha 和映射。区分外轮廓、真实间隙与像素归属裂隙；直接侵蚀带裂隙遮罩会把裂隙扩成切穿头发或肩颈的假孔。依据原几何恢复真实连续域，保留真实空隙，不靠全局模糊或填满间隙修饰。

人物放置依据 [美术设计](art-direction.md)，几何命中只防误投。固定面与静态闭合控制面的使用需记录状态，不外推活动或损伤状态。

## 投射与共享纹素

```powershell
python scripts/surface_preview.py bake --geometry output/geometry/geometry.npz --base textures/body.tga --overlay output/guides/top.json=design/top-overlay.png --out output/body-painted.png
```

覆盖图、画布、相机、几何与深度／owners 精确配对。可见三角归属、深度与有符号面朝向共同排除后方近面和薄翼背面。`--min-facing` 限制掠射拉伸；剔除导致需要的路径断开时，用补充相机、连续表面图表或直接 UV 接续，再复核遮挡和禁区，不能只降低阈值或膨胀遮罩。

含有效 alpha 的任一覆盖图零命中即整批失败；全透明稿记录 no_op、保留基底及零遮罩。主输出和派生遮罩／JSON 均不得覆盖输入或已有资产。

当前 UV 取样以 `u×(W−1)`、`(1−v)×(H−1)` 对应整数 texel 中心，屏幕光栅在 x+0.5/y+0.5。主回烘后仅从实际可见 owners 枚举最多四个权重大于 1e-7 的 bilinear 支撑 texel 补未覆盖部分，不膨胀 UV、不放宽可见性。sampling 收据记录补齐、颜色竞争及中心重叠；支撑齐全只证明该相机取样贡献，不保证颜色重建或其他视角。

共享纹素无法保存独立颜色。当前 facing×alpha 选源是采样优先级，不协调矛盾设计，可能造成宏观三角切色；先统一来源或表面归属。UV 中心重叠是内部覆盖下界，bilinear footprint 可能读取更多共享 texel，零统计不证明独立。顶底共享时，清空底视人物层也不能消除底面人物；调整位置、裁切、承载面或一致图案。

## 回烘后检查

先看只有色场和路径的真实合成模型，按同一位置对比单方向与合并稿，定位三角切色、边界错位或重复裁切；再恢复人物、文字和材质，检查顶底、两侧、前后及斜视，并为被遮尾面补视角。

疑似截断先区分原图缺失、永久裁切、真实遮挡与透明材质代理异常。保持相机／几何／贴图做局部诊断，透明显示未知时单列，不因代理不透明反复裁人。确认实体遮挡损害预期阅读时返回布局，并非要求每角度无遮挡。

### 人物 UV 遮罩诊断

可将全部实际人物贡献单独回烘成亮色人物／黑 RGB 背景的诊断图，再用底视和两个相反腹斜视查看。只清 alpha 留白 RGB 会误导只读 RGB 的渲染器。没有可靠语义遮罩时，直接检查最终颜色图，不用自动分割证明无人物。

禁区不能简单取所有朝下三角 UV 并集：辅助面可能用小面积读取整 atlas。结合完整场景的可见 owners 与真实部件职责定位；不同投射子集需明确三角对应。排除辅助面保留依据，不删原几何或改 UV。

发现真实禁区冲突时改布局／裁切／承载面，再看全部人物、尾面和副像。不能静默减掉人物 UV 来凑零交集而切坏头肩。极弱边缘与可辨人物残片分开记录，有限视角不外推未知 mip、活动或损伤状态。

回烘默认保持颜色 alpha；材质用已确认数据或显式修改通道。布局预览与实际受光的验证范围见 [UV 与材质](materials-and-uv.md#质感检查)。
