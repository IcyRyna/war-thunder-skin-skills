---
name: war-thunder-user-skins
description: 设计、制作、修订和研究 War Thunder 二次元固定翼喷气式飞机痛涂，处理立绘布局、线条配色、原 UV、分层工程、模型检查及 BLK/DDS/TGA 交付。不用于其他载具或非二次元主题。
---

# 战雷二次元喷气机痛涂

根据当前机型、角色和指定参考完成实际可编辑的成果。自行处理普通素材与设计选择，按任务需要使用已有工具；图像模型是可选路线。

## 先确定本次工作

| 请求 | 执行范围与入口 |
| --- | --- |
| 新作 | 素材 → 整机构图 → 分层制作 → UV／材质 → 模型修订 → 交付；没做过的机型先按 [新机型上手](references/new-airframe.md) 走一遍 |
| 局部修订 | 保留已接受部分，只修改问题域并复查受影响的表面与输出 |
| 点评、选型、讨论 | 回答指定问题，按需看参考，不自动制作或采集素材包 |
| 学习、复刻、审计 | 按 [研究与审计](references/research-and-audit.md) 确认来源、范围、实验和关闭条件；复刻作者图形、要求线条和作者一样干净时，先读 [原 UV 作画与逐组复刻](references/uv-native-replica.md) |
| 清晰度、发白或质感故障 | 按 [输出与检查](references/packaging-and-validation.md#模型与实际效果) 追踪实际输入和受影响位置，再查采样或材质 |
| Skill 修订 | 只更新可迁移方法与必要工具说明；制作任务按原状态保留 |

有工作区登记时先定位所属项目与任务，再读取相应 `.skin-workshop.json`。需求按“技能默认 → 项目 → 当前任务 → 当前对话明确覆盖”应用，未覆盖项继续继承。历史方案和代理自写配置是资料，不能替代用户要求或淡化未解决缺陷。指定作者、作品或线型时，实际查看对应参考；角色主题不自动授权重选其线条语言。

## 按需读取参考

新作、换底和任何美术修订先读 [审美基线](references/aesthetics.md)：默认风格、配色面积、线条构造、人物尺度、质感、在编辑器里逐岛看展开图的方法和常见失败表。没有用户指定时按它做。同时读 [审美纠偏](references/taste-corrections.md)：模型在字体、配色、布局上的固定偏向和改法；设计稿写好后跑 `scripts/design_lint.py`，交付前过它的闸门。用户点名某种风格或作者、且装有该风格的独立 skill 时，改用那个 skill：它自带完整流程和工具，不和本 skill 同时加载。

- [素材与布局](references/assets-and-layout.md)：找图、来源、有效细节和原图适配。
- [美术设计](references/art-direction.md)：人物动作、尺度、各面职责、尾面及图文嵌合。
- [从真实资源制作飞机标记](references/resource-markings.md)：机型资源 ID、只读检索游戏 UI 包、和参考作品的图标配准（位图复用）、找不到同款时如实记录或标为游戏模型派生、放到原 UV。
- [新机型上手](references/new-airframe.md)：从模型到第一版基本布局的可复刻清单：已用纹素里的两种假覆盖（别的贴图、UV 铺满整图的辅助件），岛地图和每纹素机体坐标，左右共用的岛，每块 UV 连通岛的米制 frame（残差判断能否当平面画）与展开机身的站位 × 周长坐标，按岛的干净底色和机械件遮罩，平面形与法向宽度，每岛一个图表的设计稿，试画循环（面积比、lint、1:1），窄圆机背；数字来自 J-10C。
- [原 UV 作画与逐组复刻](references/uv-native-replica.md)：判断作者在 UV 上还是在模型上作画，岛、材质与实际使用纹素，构造线，参数拟合，按元素测颜色与马赛克（逐块相位、边缘证据、镜像），区分原厂部件，字样和图标，一次只验证一组与整机组装，工具流程，诚实区分测量重建和独立构形，以及前几轮失败的原因。
- [线条与配色](references/linework-and-color.md)：母形、分支带、序列、伴线的构造顺序，`vector_paint.py` 设计稿与颜色。
- [UV 与材质](references/materials-and-uv.md)：干净重涂、整机一层涂层、完整承载面、结构、通道和受光。
- [编辑工作流](references/editor-workflow.md)：原生工程、SVG 导入和 Composa 会话恢复。
- [图像辅助编辑](references/image-assisted-editing.md)：任务需要图像模型时的输入、保护域和输出检查。
- [正交制作](references/orthographic-workflow.md)：几何、相机、可见性回烘、共享 UV 与模型诊断。
- [打包与验证](references/packaging-and-validation.md)：文件保护、TGA/DDS、工程重开和验收状态。

只读取本次需要的分支；直接 UV 编辑不强制投射，普通局部修订不强制全套研究或材质实验。

## 制作中的关键决策

1. **先确定素材和真实承载面。** 保护角色识别与所选动作连接，同时在整机尺度取得足够主视觉重量。按 [美术设计](references/art-direction.md) 安排表面分工；指定双翼人物、尾面或线条密度逐项落实。
2. **先大形后细节。** 先用深、中、亮三档色块定大形，眯眼检查通过再放人物、构线、加纹理和字；初稿即看模型和全图粗漏。每轮都在编辑器里打开参考与当前展开图逐岛对照，见 [审美基线](references/aesthetics.md#在编辑器里逐岛看展开图)。
3. **保存制作源。** 按 [图层结构](references/aesthetics.md#图层结构) 分层；线条和色场保存 `vector_paint.py` 设计稿与 SVG，人物保存原图。全部线条合成一张栅格层不算可编辑。
4. **保留资源契约。** 从 BLK 确认资源和 wildcard；保留原 UV、比例、部件变换与材质分组。RGB、颜色 alpha 与打包材质分别处理；完整重涂的材质默认是整机一层光滑均匀的涂层（`coat_material.py`），颜色里不压面板线。共享纹素通过图案一致性、裁切、位置或来源优先级解决，不重排原 UV。
5. **用实际输出关闭问题。** atlas 检查形状与采样，模型检查表面、遮挡和构图，材质检查对应受光；线条、边缘和立绘边在 [原尺寸检查](references/packaging-and-validation.md#原尺寸检查) 里按 1:1 和参考并排看，缩小的预览图不能代替。每项要求保留通过、失败或未检查及具体证据；必需项能补看就补看，已知缺陷修好再复查。
6. **交付并保留评价边界。** 原生工程、实际贴图、BLK 和预览相互对应。技术合规、基本识别／构图、用户美术评价分别记录；作品状态与当前版本遵循项目登记，不把文件存在、局部通过或自评分当成整套认可。

原素材与历史证据独立保存。内部配置和研究留在工作区，交付说明聚焦实际结果、用法、来源 credit 与未验证范围。安装、发布和游戏检查按用户授权执行；禁止启动游戏时保持离线。

## 可选工具

先用 `--help` 查看当前参数，工具实现和实时 schema 优先于示例。运行脚本时用 `python -B`；Numba 缓存默认写到系统临时目录（可用 `NUMBA_CACHE_DIR` 改），不要留在 Skill 目录里。输出一律写到当前任务目录，不写进 Skill 目录。依赖缺失时报告具体缺口并使用可行替代入口，不擅自安装服务或修改环境配置。

| 脚本 | 职责／主要依赖 |
| --- | --- |
| `scripts/inspect_skins.py` | BLK 与贴图检查；Python 3.10+，预览需 Pillow |
| `scripts/compare_skin.py` | 通道与 UV 覆盖区比较；Pillow、NumPy |
| `scripts/composa_mcp.py` | Composa 工具发现与顺序调用；Python 标准库 |
| `scripts/fetch_asset.py` | 下载已选图片与来源记录；requests、Pillow |
| `scripts/design_lint.py` | 只读设计稿，查默认或装饰字体、缺字、凑数英文、字号太接近、纯黑纯白、屏幕原色、多个饱和色族、色相渐变、等粗宽线、白色细长线（开放细条即使叫 echo 也查）、游戏距离下过细的白描边、孤立描边框、叠线发光、角度太多、立绘重复；Python 标准库，查缺字需 Pillow |
| `scripts/surface_map.py` | 按设计稿的每个图表画平整／弯曲／拉伸／机械件／共用 UV 被抢／被别的表面盖住／接缝（如凸起背鳍条侧壁）的分区图，并列出压到这些区域或跨过接缝的图元；NumPy、Pillow、Numba |
| `scripts/vector_paint.py` | 机体米制设计稿直接在原 UV 子纹素上求值：色场、渐尖线、马赛克与半调；NumPy、Pillow、Numba |
| `scripts/airframe_setup.py` | 新机型准备：岛地图与每纹素机体坐标（map）、每块 UV 连通岛的米制 frame 与残差（frames）、按岛的干净底色和机械件遮罩（clean）、渲染图的深底／签名色／淡染／白面积比（shares）；NumPy、Pillow、SciPy、Numba |
| `scripts/uv_frame.py` | 给一块 UV 岛拟合直线框架（atlas 上笔直的设计坐标），写进图表的 `frame`，并检查展开误差；NumPy |
| `scripts/arrangement.py` | 构造线切格：少数几条直线把图表切成格子，图形是格子或格子的描边（`holes`），可镜像（`halves: separate` 两半各用本半边的线）；`region` + `cuts` 把一整块白色用等宽深色切缝切开，自动得到白块（机背焦点的默认写法）；Python 标准库 |
| `scripts/replica_measure.py` | 学习参考涂装时在展开图上逐组测量：描直边轮廓、按元素测渐变、拟合马赛克（格距、方向、相位、缝、明暗档、边缘证据）、高通放大读格子、游戏图标配准、整区自动测量并跳过原厂部件；NumPy、Pillow、SciPy、OpenCV |
| `scripts/replica_check.py` | 实际使用纹素掩膜（多张颜色贴图时 `--texture` 指名）、计划编辑（马赛克、镜像轴）、计划转 atlas 框架设计稿（马赛克可直接写参数，`--provenance` 写明来源）、一组一验（同相机、1:1 对照）、整机组装对照；NumPy、Pillow、SciPy |
| `scripts/coat_material.py` | 完整重涂的整机一层涂层材质：常量光滑度与金属度、法线压平，可保留少量凹槽只在反光里出现；NumPy、Pillow |
| `scripts/detail_sheet.py` | 原尺寸检查：从最终颜色图按 1:1 截取各部位（或自动挑细节最多的区域），和参考贴图按同样的米制比例并排，另出 Composa 调用清单；NumPy、Pillow |
| `scripts/panel_lines.py` | 面板发丝线，默认不用。从原厂颜色贴图描出分块线和铆钉排；描线质量不过闸门（短线、台阶、折角）时 `apply` 拒绝画；NumPy、Pillow、Numba |
| `scripts/structure_layer.py` | 从原机法线通道提取模糊的面板线与铆钉结构层，只用于用户要的旧化或写实机械感；NumPy、Pillow |
| `scripts/atlas_palette.py` | 多张展开图同一归一化区域的色族面积对照；NumPy、Pillow |
| `scripts/style_board.py` | 整机渲染与参考同尺寸并排：原色、明暗、眯眼三行；NumPy、Pillow |
| `scripts/surface_preview.py` | 单材质原 UV 预览与回烘；NumPy、Pillow、Numba，prepare 需外置解码器 |
| `scripts/scene_preview.py` | 多材质整机场景与补充相机；NumPy、Pillow、Numba |
| `scripts/finish_preview.py` | 两环境与法线隔离的近似材质对照；NumPy、Pillow、Numba |
| `scripts/build_skin.py` | TGA／BLK 组装；Pillow、NumPy |
| `scripts/dds_variant.py` | DDS 与实际 mip 验证；Pillow、NumPy、受支持的官方 texconv |
