# 包内素材选择与来源

本包携带素材，不依赖制作任务的本机路径。完整文件清单、尺寸、来源与 SHA-256 在 `assets/manifest.json`；A7V 原作的逐项坐标和阅读方向在 `assets/reference-a7v/element-catalog.json`。

## 找素材

| 路径 | 内容 | 使用判断 |
|---|---|---|
| `assets/official/endfield-industries-cn.png` | 官网原文件，430×372，透明 PNG；中文终末地工业徽记 | 官方图形母版，按目标尺寸检查等高线是否仍可见 |
| `assets/official/endfield-title-en.svg` | 从官网页头提取的官方英文游戏标题 SVG 路径；只增加显示尺寸 | 形状可缩放；是游戏标题，与工业组织徽记的字标有区别 |
| `assets/official/endfield-title-en.png` | 上项经 Composa 渲染的透明 1483×740 PNG | 位图工具用；矢量源仍保留 |
| `assets/official/site-color-bar.png` | 官网原彩条资源，18×113 | 参考官方配色语汇；不能据此断言原作者的彩线来自同一文件 |
| `assets/decals/endfield-industries-en-native.png` | 原 DDS 小徽记在 Composa 中按白色印刷层提取，400×400 透明画布 | 实际有效徽记约 122×122；可供小标或结构核对，不能冒充高清官方英文母版 |
| `assets/reference-a7v/uv/*.png` | 车体、炮塔、炮管和机枪座的完整原尺寸 RGB 图集 | 查原作构图与裁片；仍含机械结构、磨损与烘焙阴影；不是可直接套用的目标车贴图 |
| `assets/reference-a7v/crops/B01.png` 等 | 22 个原图裁片，部分为便于阅读旋转 | 看具体标识和配色关系；裁片里螺钉、边框、孔口需要与图形分离 |
| `assets/study/UV-study-overview.png` | 四张图集与来源对应总览 | 快速定位，不作为最终贴图输入 |
| `assets/study/element-vocabulary.png` | 12 组代表性元素板 | 看视觉层级，不把板上的研究标题当作涂装文字 |

四张 RGB 图集的每个像素都与原 DDS 的 RGB 核对过，总计 143,130,624 像素，差异为 0。原 DDS 的 Alpha 全零；查看副本只显示 RGB，不代表游戏 Alpha 应改为不透明。

## 选用次序

先按用途找素材：主徽记、次级字标、方向路线或微型设备标签。已取得的官方清晰母版适合直接放置；原作裁片适合研究字体大小、位置和层级；带结构的裁片要先提取图形。需要新载具名时重新排设备铭牌，不能把 LEOPARD2A7 当作终末地通用品牌文字。

标志方向按模型上的承载面确定。不要因为 UV 图里某个字标倒置就旋转整张图集，也不要把两侧的阅读方向合成一个“双重徽记”。坐标仅属于这套 A7V UV。

素材归原权利人：终末地官方内容归鹰角 / GRYPHLINE 等相应权利人；坦克涂装编排与原图来自 HK416の午夜福音的 WT Live 1162771。包内记录来源，不为这些素材另行声明开放许可证。
