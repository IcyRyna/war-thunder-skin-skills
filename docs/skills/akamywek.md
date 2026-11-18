# Akamywek 风格飞机涂装

> **`war-thunder-style-akamywek`**：用于在《战争雷霆》喷气机原生 UV 上构造炭灰 `#333334`、单一或双指定签名色、中轴无缝锐角白形与翼尾三角马赛克的涂装制作 Skill。支持从**纯原教旨无人物**起步，或按需启用**终末地工业贴花联名变体**（随包内置 71 项精选素材）及**翼面人物分支**。

[← 返回首页](../../README.md) · [安装说明](../installation.md) · [更新记录](../changelog/war-thunder-style-akamywek.md) · [下载中心](../../releases/README.md)

---

## 一、版本选择与下载

| 版本线 | 状态 | 适用说明 | 下载 |
| --- | --- | --- | --- |
| **1.3.1** | **推荐正式版（Latest）** | 经 F-15EX 实机反馈校准；保留原 Release 字节不动，随时可用于稳定回退。 | [下载 1.3.1 (.skill.zip)](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/war-thunder-style-akamywek/v1.3.1/war-thunder-style-akamywek-v1.3.1.skill.zip) |
| **1.3.1 RC2** | **补丁测试（Pre-release）** | 基于 `1.3.1` 的工程补丁：新增内置贴纸短路径 `"endfield/..."` 回退、Windows 文件锁与无 `requests`/`matplotlib` 离线容错、`SKILL.md` 条理化重排、内置宽体示例对齐（`31/31` 脚本单元回归通过）。 | [查看 1.3.1 RC2 Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.3.1-rc2) |

---

## 二、先看对应认可作品

| 代表作品 | 已认可适用范围 | 制作时重点参考 |
| --- | --- | --- |
| **F-15EX「终末地」** | 双发双垂尾无人物<br><sub>工业贴花联名变体，含 CFT</sub> | 机鼻色场收进无缝实心白 `V`；平尾前缘锯齿对齐；双发后机背带剪影、长线、箭头与完整型号锁组；内翼根保留炭灰技术簇；内置 `Orbitron-VF.ttf` + `Michroma-Regular.ttf`；采用缎面金属 PBR（`R=163, B=188` + 平坦细节法线）与三段式深枪灰钛喷口/护罩。<br>**边界提示：** 原教旨路线只借其骨架与材质，终末地联名变体才调用随包 `assets/decals/endfield/`。 |
| **J-16「青色无人物」** | 双发重战无人物基线 | 双发肩部、负形与后机背接续；从 `j16-guide.json` 迁往机背平整的飞机时须合并 `idx 16/17/20` 为完整无洞白 `V`。 |
| **J-10C「青黄」/「祀」** | 三角翼与鸭翼布局 | 整块双翼连续渐变、两肩字距内收与三角翼双面人物布局。 |
| **F-16C Block 50「铜橙」** | 轻型单发无人物整机 | 单发窄机身翼尾分工与字标尺度控制。 |

---

## 三、核心特性一览（1.3.1 / 1.3.1 RC2）

- **内置宽体几何字体**：`assets/fonts/` 自带 `Orbitron-VF.ttf` + `Michroma-Regular.ttf` 与 `OFL.txt`，默认加载而不回退偏窄系统字体。
- **随包终末地工业贴纸库**：`assets/decals/endfield/` 收录 71 个精选文件（17 个矢量 SVG、9 张高分纯白阵营 PNG、28 张去重纯白工业厂标、9 张 254² 职业标、5 张透明底无黑块 UI 标牌含 `TALOS-II` 多色条及生成器）。`1.3.1 RC2` 起 `vector_paint.py` 支持 `"endfield/..."` 相对短路径自动回退；严禁仅用单挂件几何验收跨部件遮挡与深底实心黑块。
- **缎面高金属清漆与三段喷口**：`coat_material.py --preset metallic-satin`（`R=163, B=188, G/A=128`）、`--flat-detail-out` 中性细节法线消水波纹，以及 `apply_exhaust_finish` 压暗机腹护罩与双发收敛片。
- **防逼挤与几何净距检测**：`design_lint.py` 查同图幅重叠/逼挤并放宽双发对称计数；`surface_map.py` 检查 `< 2 m` 徽章和文字到表面边缘及 `SEAM` 的净距。

[风格源码](../../src/styles/aircraft/war-thunder-style-akamywek/) · [维护与候选构建](../maintaining.md) · [返回文档中心](../README.md)
