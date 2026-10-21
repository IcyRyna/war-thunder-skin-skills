# A7V 原作者范本解析

主要依据是 HK416の午夜福音的 [WT Live 1162771](https://live.warthunder.com/post/1162771/en/) A7V 作品，原包 SHA-256 为 `e1cc23b473a1707573e60c4d9776657d41421318ab48a5052b34f4758bfb2f10`。r11 是临摹对照，不取代这个基准。以下八条保留此前逐区分析的观察、解释、迁移提议与边界；它们不是对全部终末地作品的统计，也不证明作者本人的制作工序。

先看 [原作者展示 1](../assets/reference/a7v/author-01.jpeg)、[展示 2](../assets/reference/a7v/author-02.jpeg)，再看离线模型重现的 [左侧](../assets/reference/a7v/left.png)、[右侧](../assets/reference/a7v/right.png)、[前](../assets/reference/a7v/front.png)、[后](../assets/reference/a7v/rear.png)、[顶](../assets/reference/a7v/top.png)、[斜前](../assets/reference/a7v/iso.png)。模型渲染只是辅助对应承载面，不是游戏截图。

原作关系尤其体现在：车体长侧面的完整主工业徽记及宽黄色方向面；浅色炮塔前肩与较暗后顶的主次；肩部次级图文与短路线；车首偏置黄带、小型图形和设备信息；尾部机械区安静收束。不能把这些压成“每辆车两条细黄线＋一个小标”，也不能从原作推导前面必须对称 V 或尾面必须大 U。

## 八条分析与迁移条件

### LAYOUT-01 · 先分配物理表面的视觉职责

**观察：** 两侧裙板中后段承担大工业徽记；炮塔浅色前肩承担中等识别模块，暗色设备顶面承担低对比纹样和小标；炮管沿长轴延伸；机枪座/后部机械区不抢主视觉。

**解释：** 整车由主识别面、次识别面、方向延伸面和安静机械面共同成立，不能把同一张徽记铺到每个部件。

**迁移操作：** 新车先标出连续侧板、炮塔肩部、窄长覆板、设备密集区，再分配角色；缺少某类表面时缩减该层信息，不挤成同一张拼贴。

**证据：** [B01](../assets/legacy/reference-a7v/crops/B01.png)、[T01](../assets/legacy/reference-a7v/crops/T01.png)、[T05](../assets/legacy/reference-a7v/crops/T05.png)、[T09](../assets/legacy/reference-a7v/crops/T09.png)、[G01](../assets/legacy/reference-a7v/crops/G01.png)、[M01](../assets/legacy/reference-a7v/crops/M01.png)。定位把握：高：大表面可由原作者照片与模型视图交叉确认；未将裁片内每个小零件全部精确定位。

**适用／例外：** 这是该A7V原作的职责分配，不是所有终末地作品必须照搬的布局。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

### LAYOUT-02 · 黑白灰负责大块结构，黄色负责方向，小彩色只作点睛

**观察：** 炮塔后顶和设备集中区较暗，前部楔形装甲与车首以灰白为主；侧裙黑区给白色主徽记托底。黄带在灰白/黑面间形成高识别路线；青绿/品红主要是侧裙细线和暗顶微型色条。

**解释：** 识别主要来自大块明暗关系与黄色动线；彩色层级是主黄、微量辅彩，而非同权重多色拼贴。

**迁移操作：** 先画黑/灰白的大区，再给少量黄色方向面；青绿、品红作为可选的微标/细线系统。调色应在新车主要视角上判断，不使用UV空白面积或r11色板推整车比例。

**证据：** [B01](../assets/legacy/reference-a7v/crops/B01.png)、[B08](../assets/legacy/reference-a7v/crops/B08.png)、[B09](../assets/legacy/reference-a7v/crops/B09.png)、[T02](../assets/legacy/reference-a7v/crops/T02.png)、[T05](../assets/legacy/reference-a7v/crops/T05.png)、[T09](../assets/legacy/reference-a7v/crops/T09.png)。定位把握：高：大块明暗与辅彩尺度在照片/模型均可见。

**适用／例外：** 未测得真实表面积比例；不设固定黑白百分比、不声称r11十六进制色值是原作者配方。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

### LAYOUT-03 · 黄色是有主次的路径系统

**观察：** 原作同时使用宽色带、较细平行带、折转、圆端/圆节点；侧裙的斜向黄面与炮塔肩部路线相互呼应，炮管黄带沿长轴展开。

**解释：** 方向、端点、粗细和重复关系比小图案数量更能建立工业风格。

**迁移操作：** 配套素材提供直段、转角、圆端、节点与细伴随线的成组模块。每个主要视角先定一条主路径，再布置次路径；跨板按可见连续面安排，炮塔与车体的独立运动部件以方向呼应，不强求一条静止跨轴连线。

**证据：** [B08](../assets/legacy/reference-a7v/crops/B08.png)、[B10](../assets/legacy/reference-a7v/crops/B10.png)、[T02](../assets/legacy/reference-a7v/crops/T02.png)、[T03](../assets/legacy/reference-a7v/crops/T03.png)、[T04](../assets/legacy/reference-a7v/crops/T04.png)、[G01](../assets/legacy/reference-a7v/crops/G01.png)。定位把握：高：主要路径的表面归属明确；T03内部各笔的精确板件归属为中高。

**适用／例外：** 复用形态语汇和相对关系，不复用A7V像素坐标、固定转角位置或绝对线宽。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

### LAYOUT-04 · 建立远看标识、近看模块、贴近看信息的层级

**观察：** 侧裙的大工业三角/ENDFIELD为最醒目的身份；顶部VISUALIZE组合、侧面END/FIELD字标承担中层识别；CAUTION、EF10、车型铭牌、坐标和小编号分布在局部。

**解释：** 层级同时由尺寸、对比、成组关系和承载面决定，不能只靠缩字号。

**迁移操作：** 素材包按主徽记、次级组合字标、设备/警告模块三级组织；先给主徽记留完整阅读空间，再放功能小模块。一次主视角保留清楚的焦点，不让多个大标等面积竞争。

**证据：** [B01](../assets/legacy/reference-a7v/crops/B01.png)、[B03](../assets/legacy/reference-a7v/crops/B03.png)、[B04](../assets/legacy/reference-a7v/crops/B04.png)、[B05](../assets/legacy/reference-a7v/crops/B05.png)、[B07](../assets/legacy/reference-a7v/crops/B07.png)、[T01](../assets/legacy/reference-a7v/crops/T01.png)、[T04](../assets/legacy/reference-a7v/crops/T04.png)、[T06](../assets/legacy/reference-a7v/crops/T06.png)、[T07](../assets/legacy/reference-a7v/crops/T07.png)、[G02](../assets/legacy/reference-a7v/crops/G02.png)。定位把握：主徽记、T01、T04、G01为高；T06/T07具体附件为中，仅记录目录角色不冒充精确定位。

**适用／例外：** 不把每个元素复制成相同大小的贴花；主次数量随新车有效阅读面改变。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

### LAYOUT-05 · 把密度聚在少数模块，让大色面有喘息空间

**观察：** 大徽记、前翼板三角网络和工程小字是密集区；炮塔前斜面的许多区域仍是大片灰白。暗顶虽有等高线/十字/微标，但对比低，远看仍收为暗面。

**解释：** 留白是低图文密度的色面，不等于没有机械细节；局部密度反差使标签看起来有信息组织。

**迁移操作：** 为每个主阅读面同时规划图形聚集区和安静区；技术文本成块排，重复符号成组排。低对比背景线只在需要的色场内延续，避免随机碎线填满所有空处。

**证据：** [B02](../assets/legacy/reference-a7v/crops/B02.png)、[B03](../assets/legacy/reference-a7v/crops/B03.png)、[B06](../assets/legacy/reference-a7v/crops/B06.png)、[T01](../assets/legacy/reference-a7v/crops/T01.png)、[T05](../assets/legacy/reference-a7v/crops/T05.png)、[T09](../assets/legacy/reference-a7v/crops/T09.png)、[G02](../assets/legacy/reference-a7v/crops/G02.png)。定位把握：高：密集/安静关系可见；哪些灰影属于物件材料不能仅凭平面图决定。

**适用／例外：** 没有测量全车密度阈值；不提出固定贴花数量或全图纹理覆盖率。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

### LAYOUT-06 · 素材按几何家族和用途组织，而不是混成一袋装饰

**观察：** 原作反复使用三角徽记/实空三角网络、圆端带/圆节点、斜纹块、十字与刻度、低对比等高线，以及极小CMY色条。各家族在不同尺寸重复，但承担不同职责。

**解释：** 一致性来自少数家族跨部位复现；等高线与工程微标是设计语汇，不能与污渍或机械阴影混为一类。

**迁移操作：** 准备六组可编辑素材：品牌徽记与字标；路径/节点；三角网络/方向标；斜纹/十字/刻度；低对比轮廓线；CMY微标。每组给大、中、小用途示例，明确它适合当主形、节奏或背景。

**证据：** [B01](../assets/legacy/reference-a7v/crops/B01.png)、[B02](../assets/legacy/reference-a7v/crops/B02.png)、[B03](../assets/legacy/reference-a7v/crops/B03.png)、[B06](../assets/legacy/reference-a7v/crops/B06.png)、[B09](../assets/legacy/reference-a7v/crops/B09.png)、[T02](../assets/legacy/reference-a7v/crops/T02.png)、[T03](../assets/legacy/reference-a7v/crops/T03.png)、[T05](../assets/legacy/reference-a7v/crops/T05.png)、[T09](../assets/legacy/reference-a7v/crops/T09.png)、[G02](../assets/legacy/reference-a7v/crops/G02.png)。定位把握：家族形态确定度高；单个灰形是印刷还是机械结构应独立注明，T08不当作通用装饰素材。

**适用／例外：** 这不是要求每辆车同时使用全部家族，更不是把原作带底图的裁片当透明独立素材。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

### LAYOUT-07 · 保持跨面呼应，允许局部不对称

**观察：** 左右侧都能认出同一黑白黄/工业徽记系统，但文字按各自阅读方向排。俯视的前徽记、黄色长带、顶部文字/路线并不按中轴完全镜像；车首图案跨多个实际板片成立。

**解释：** 整体平衡依靠视觉重量和方向呼应，局部不对称提供节奏。

**迁移操作：** 新车型左右侧共用同一视觉语言和相近主次强度，局部文字、编号、路径可按板面改变；跨板图案先在整体视图构图，再拆成属于各承载面的部分。

**证据：** [B01](../assets/legacy/reference-a7v/crops/B01.png)、[B02](../assets/legacy/reference-a7v/crops/B02.png)、[B03](../assets/legacy/reference-a7v/crops/B03.png)、[B07](../assets/legacy/reference-a7v/crops/B07.png)、[B11](../assets/legacy/reference-a7v/crops/B11.png)、[B12](../assets/legacy/reference-a7v/crops/B12.png)、[B13](../assets/legacy/reference-a7v/crops/B13.png)、[T01](../assets/legacy/reference-a7v/crops/T01.png)、[T02](../assets/legacy/reference-a7v/crops/T02.png)。定位把握：大方向与前部跨板关系高；全套跨板邻接不由UV裁框单独证明。

**适用／例外：** 允许不对称不是随机左右不同；阅读旋转仅属于源裁图，不能作为新车型的默认旋转。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

### LAYOUT-08 · 把品牌字形与可换设备信息分开

**观察：** ENDFIELD等品牌字形有特定几何切口和组合关系；VISUALIZE等模块采用紧凑大字与疏排小字；CAUTION、EF10、05、LEOPARD2A7等形成工程/设备信息层。

**解释：** 品牌身份依赖可辨字形，工业感还依赖大小字、短横线、数字和载具信息的排版关系。

**迁移操作：** 保留已核实的品牌母版与组合示例；另做可编辑的警告块、设备编号、车型铭牌、短工程说明和坐标模块。换车型改车辆身份字段，保持对齐/间距/层级，不把A7名字固化为风格。

**证据：** [B03](../assets/legacy/reference-a7v/crops/B03.png)、[B04](../assets/legacy/reference-a7v/crops/B04.png)、[B05](../assets/legacy/reference-a7v/crops/B05.png)、[T01](../assets/legacy/reference-a7v/crops/T01.png)、[T04](../assets/legacy/reference-a7v/crops/T04.png)、[T05](../assets/legacy/reference-a7v/crops/T05.png)、[T06](../assets/legacy/reference-a7v/crops/T06.png)、[G01](../assets/legacy/reference-a7v/crops/G01.png)、[G02](../assets/legacy/reference-a7v/crops/G02.png)。定位把握：主要字标承载区高；微字语义以原文记录，不推定真实功能。

**适用／例外：** 未识别到的字体/官方锁定版式不能凭相似无衬线字体冒充；EF10/05作为可换模块是设计提案，不是已证明作者意图。

**状态：** 原作观察已记录；迁移规则为设计建议，未宣称跨车型生产或用户美术认可。

## 原始观察与真实 PS 证据

完整机器可读规则见 [a7v-observations.json](a7v-observations.json)，保留原观察的八条完整字段；证据源哈希见来源表。9 处 MCP 原尺寸裁区见 [a7v-ps-study.json](a7v-ps-study.json)，位置仅属于 A7V 源 UV。25 裁片全保留，不把框选矩形认作精确构件遮罩。
