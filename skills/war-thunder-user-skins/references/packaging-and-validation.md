# 二次元喷气机涂装的输出与检查

工作区保留工程、来源、原始通道和修改记录；游戏包只放 BLK 及其实际引用贴图。改型、分辨率或格式版本分别检查。

写入前枚举主文件及派生预览、遮罩、深度、JSON、ZIP、来源收据，拒绝输入／已有资产冲突。构建与转换用同盘暂存、校验后提交；失败只撤本次未提交内容并留失败收据。恢复先查实际文件状态，不复用旧成功记录。

## 构建辅助

`build_skin.py` 读取单机模板、编辑器导出及确认原贴图，输出全新空目录，必须在模板外。先解决输入 BLK 重复、歧义或结构错误，不能用重写输出掩盖它。

`--paint` 为“精确 from=图片”，`--reference` 指定真实原贴图，`--channel` 为“精确 from:RGBA字母=8-bit灰度图”。保持原 UV 比例，未编辑数据保留，颜色默认保持原 alpha。输出 32-bit TGA、BLK、ZIP 和组装记录并核对像素往返；DDS 单独构建。

## DDS 与实际 mip

`dds_variant.py` 接受已检查 TGA／BLK 目录，`--texconv` 指向受支持的官方 DirectXTex。当前代码校验固定 May 2026 二进制与哈希，二进制不内置；缺依赖或版本不符明确失败。

```powershell
python scripts/dds_variant.py --input output/tga-skin --out output/dds-rgba8 --texconv tools/texconv.exe --format rgba8
```

默认 rgba8 保留顶层像素，bc3 只作另包有损实验；不覆盖 TGA 主包。资源按已确认 color／data 用途处理，未知用途拒猜，可用 `--role "精确from=color"` 或 data 显式声明。

实际流程逐通道以浮点 BOX 生成 mip，再让 texconv 保留各级编码：RGB 由 sRGB 解码到线性过滤后编码，颜色 alpha 独立数值过滤不预乘，材质 RGBA 各通道按线性数据过滤。读取实际 DDS 至 1×1，与预生成链核对并输出 .dds.json／.mips.zip；RGBA8逐像素比，有损版记通道误差。G/A 是数值 mip 基线，不宣称向量感知过滤或游戏 shader 正确。

同尺度看脸、字、细线、透明边与接缝，未验证压缩不替代主包。离线 mip 不证明游戏运行时 mip／LOD 选择。

## 静态检查

`inspect_skins.py` 只读源目录，输出在源目录外。头部／BLK 扫描需 Python 3.10+，图片预览需 Pillow；`--hash` 读取全字节。`--strict` 对静态错误和显式请求的解码失败返回非零。未请求解码的扫描只说明头部／配置范围。

```powershell
python scripts/inspect_skins.py scan output/skin-package --out output/skin-check --strict
python scripts/inspect_skins.py preview textures/body.tga --out output/texture-check
```

工具不查游戏资源库、不执行 include、不验证 UV、不自动修复。普通二维顶层预览上限8192²；DDS 数组／体／立方体不生成该预览。

## 模型与实际效果

沿用项目约定的七视图相机、画布、机腹方向、图格与显示比例；近景和新角度另出。按本次要求建立“表面／要求 → 实际视角／尺度 → pass／fail／uninspected → 复查”台账。补看能取得的必需面，修已知可离线修正的缺陷；能力限制可交受限候选，但不得标全通过。具体构图标准见 [美术设计](art-direction.md)。

清晰度按同一位置追查“原素材 → 源层 → 编辑器导出 → atlas → 包内实际解码 → 安装文件”，定位首次损失。复现可取得的问题视向和机体屏幕占比，沿完整受影响路径看线宽、负形与脸部阅读；8K文件头、局部放大或更有利视角不能关闭原问题。

发白与质感按 [材质检查](materials-and-uv.md#质感检查) 固定变量对照，实际环境图、投诉近景及输入收据随当前版保留。无人物机腹检查最终贴图的模型映射，必要时用 [人物遮罩诊断](orthographic-workflow.md#人物-uv-遮罩诊断)；底视源稿无人物不足以通过。

安装效果与预览不同时，先读现用 checkpoint 和实际重建入口，核对加载模块／runtime、参数、BLK、贴图身份、尺寸与编码。公开源码或 Skill 已同步不证明任务私有 bundle 已用修复；新输出须绑定真实入口和当前输入。源码可能新于最后已建 SVG，不能用浮动源替代旧快照结论。

按用户约定做离线或游戏检查，未实机、未知透明度、活动／损伤状态和运行时过滤明确保留范围。交付说明给实际位置、安装方式、变更、检查与限制；发布与第三方发送按授权。

## 原尺寸检查

8192 的颜色图缩到 1600 px 看，2 px 的线、断线、台阶锯齿、立绘边上的灰雾和原厂贴图碎片都看不出来；莱万汀 v3 就是这样带着脏线交付的。交付前在原尺寸下看每个部位：

```powershell
python -B scripts/detail_sheet.py --color output/paint/color.png --px-per-m 520 --region spine=3900,3300,480 --region wingtip=1200,5600,480 --auto 4 --ref F-2A=reference/f_2a.dds --ref-px-per-m 550 --ref-region spine=2700,3550,480 --out output/detail-v1
python -B scripts/composa_mcp.py --calls output/detail-v1/composa-calls.json --out output/composa-detail-v1
```

- 区域写成 `名字=x,y,宽`（像素，高取宽的 2/3）。每个部位至少一处：主图形、翼面、尾面、侧面细线、字、立绘边缘；`--auto N` 再加 N 处细节最多的地方，那里最先暴露问题。
- 给了 `--px-per-m` 和 `--ref-px-per-m`，参考截图会缩放到同样的毫米／像素，两边并排时同样宽的线看起来一样宽。贴图密度从几何算：UV 面积乘贴图边长平方，除以表面面积，再开方。
- `composa-calls.json` 在 Composa 里打开颜色图并按原尺寸渲染每个区域；颜色图是 TGA 或 DDS 时加 `--composa-copy` 先出一张 PNG。
- 看：边缘是否只有 1–2 px 抗锯齿，同类线是否一样宽，有没有断线、台阶、散点、灰雾、原厂贴图碎片和漏色边。有就回到设计稿或素材改，不靠缩小图交付。

## 工程可继续编辑

将保存工程复制到新路径，核对复制品身份后重开，保护交付原件。检查关键图层、文字与像素，做一次实际可逆的文字编辑或位置变换并撤销，重新导出比较；无对应能力时说明替代操作与限制。保存／ZIP成功不证明可编辑。

分别说明原生文字／形状、独立 SVG 和栅格层的范围。转换后实际检查 clip、mask、alpha、关键图形与位置，非空不等于正确。正式修订须进入真实工程导出和模型；采纳输出前确认 straight／premultiplied 与量化合同，记录允许差异，解释不了的丢层或导出变化先修复。

## 验收状态

技术合规、基本识别／构图、用户美术评价分开。每项通过绑定本版输入、完整受审对象及对应视角、尺度、受光；格式、字节、采样、局部重建、近似材质和目标游戏结果分别命名。局部改善旁保留既有 fail／uninspected，不用重新缩窄范围撤销真实失败。

用户否定版保留失败含义，不列成功范本；有限认可不升级，独立审查与实物冲突时按具体漏检修订。完成操作不自动形成用户认可。

按要求整理当前工程、必要素材和研究，清理可再生解包、临时导出和重复包。删除旧版／失败归档前先保留当前依赖并更新路径，随后按授权删除，不另囤失败包。研究与历史记录不进入公开 Skill。
