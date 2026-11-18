# Akamywek 风格喷气机涂装

`war-thunder-style-akamywek` **1.3.1** 用于在《战争雷霆》喷气机的原生 UV 上制作炭灰、签名色与锐角白形组成的涂装。可从整机原教旨无人物布局起步，或按需接入主题工业贴花（内置 `assets/decals/endfield/` 终末地素材库）及翼面人物。[下载 1.3.1 安装包](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/war-thunder-style-akamywek/v1.3.1/war-thunder-style-akamywek-v1.3.1.skill.zip) · [安装说明](../installation.md) · [版本记录](../changelog/war-thunder-style-akamywek.md)

## 先看对应作品

| 作品 | 已认可范围 | 制作时看哪里 |
| --- | --- | --- |
| F-15EX「终末地」 | 双发双垂尾无人物（工业贴花联名变体，含 CFT） | 机鼻色场收进无缝实心白 V；平尾前缘锯齿对齐；双发后机背带剪影、长线、箭头与完整型号锁组；内翼根保留炭灰技术簇；内置 `Orbitron-VF.ttf` + `Michroma-Regular.ttf`；采用缎面金属 PBR（`R=163, B=188`+平坦细节法线）与三段式深枪灰钛喷口/护罩。原教旨路线仅借骨架，终末地变体可调用随包 `assets/decals/endfield/`。 |
| J-16「青色无人物」 | 双发重战无人物基线 | 双发肩部、负形与后机背接续。从 `j16-guide.json` 迁往机背平整的飞机时须合并 `idx 16/17/20` 为完整白 V。 |
| J-10C 青黄 / 祀 | 三角翼与鸭翼布局 | 整块双翼连续渐变、两肩字距内收与三角翼人物布局。 |
| F-16C Block 50「铜橙」 | 轻型单发无人物整机 | 单发窄机身翼尾分工与字标尺度。 |

## 1.3.1 材质、内置字体与终末地贴纸库

- **内置宽体几何字体**：`assets/fonts/` 自带 `Orbitron-VF.ttf` + `Michroma-Regular.ttf` 与 `OFL.txt`，默认加载而不回退偏窄 `Bahnschrift`。
- **随包终末地工业贴纸库**：`assets/decals/endfield/` 收录 71 个精选文件（17 个矢量 SVG、9 张高分纯白阵营 PNG、28 张去重纯白工业厂标、9 张 254² 职业标、5 张透明底无黑块 UI 标牌含 `TALOS-II` 多色条及生成器），严禁仅用单挂件几何验收跨部件遮挡与深底实心黑块。
- **缎面高金属清漆与三段喷口**：`coat_material.py --preset metallic-satin`（`R=163, B=188, G/A=128`）、`--flat-detail-out` 中性细节法线消波纹，以及 `apply_exhaust_finish` 压暗机腹护罩与双发收敛片。
- **防逼挤与几何净距检测**：`design_lint.py` 查同图幅重叠/逼挤并放宽双发对称计数；`surface_map.py` 检查 `< 2 m` 徽章和文字到表面边缘及 `SEAM` 的净距。

[风格源码](../../src/styles/aircraft/war-thunder-style-akamywek/) · [维护指南](../maintaining.md) · [返回首页](../../README.md)
