# Akamywek 风格飞机涂装 · 更新记录

> 以炭灰 `#333334`、指定色场、中轴锐角白形与三角马赛克构成的喷气机涂装工作流。当前推荐正式版本为 **1.21**。
>
> **2026-11-19 封存回退：** `1.30`、`1.3.1` 与 `1.3.1 RC2` 已正式封存退役、停止维护，正式主线恢复并锁定为 **`1.21`**（原 Git 标签与 `.skill.zip` 附件继续保留以便追溯）。

[← 返回首页](../../README.md) · [功能介绍](../skills/akamywek.md) · [当前推荐 1.21](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.21) · [历史归档](../history/README.md)

---

## 一、现行版本与有效基线

| 版本 | 状态 / 更新内容 | 下载 |
| --- | --- | --- |
| **1.21** | **当前推荐正式版（Latest · 2026-11-19 恢复主线）：** 收录 F-15C「青锋」双发无人物范本与「莱万汀」双翼布局，对照双翼眼线、下巴与露肩方向，补充最终 DDS 的眼部清晰度检查。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.21) |
| **1.16** | 汇总 J-16、J-10C 已认可无人物基线；整块双色渐变、窄机身文字内收、分岛覆盖与局部修改；人物放置标为未验证。未采用 1.15 候选。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.16) |

---

## 二、已封存退役的 1.3x 分支（2026-11-19 退役 · 不再维护）

<details>
<summary><b>🗄 点击展开：已封存的 1.30 / 1.3.1 / 1.3.1 RC2 历史记录</b></summary>

| 版本 | 归档状态与历史变更摘要 | 原 Release（只读追溯） |
| --- | --- | --- |
| ~~1.3.1 RC2~~ | **已封存退役（2026-11-19，已撤销 Pre-release）：** ① `vector_paint.py` 为随包 `assets/decals/` 增加相对短路径自动回退；② 修复 `replica_check.py` Windows 句柄与无 `matplotlib` 回退；③ `fetch_asset.py` 增加 `urllib` 回退；④ 对齐示例宽体字体并重排 `SKILL.md` 结构（已因后续结构回归整体退役并回退 `1.21`）。 | [v1.3.1-rc2](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.3.1-rc2) |
| ~~1.3.1~~ | **已封存退役（2026-11-19，已撤销 Latest）：** 内置宽体字体、`assets/decals/endfield/` 71 项终末地贴花、`f15ex-endfield.md` 案例与净距/喷口调整（已退役回退至 `1.21`）。 | [v1.3.1](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.3.1) |
| ~~1.30~~ | **已封存退役（2026-11-19）：** 缎面高金属反光清漆预设、`--flat-detail-out` 平坦细节法线、CFT 与钛护罩分级及 `design_lint.py` 扩展（已退役回退至 `1.21`）。 | [v1.30](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.30) |

</details>

---

## 三、更早历史版本（1.14 – 1.0）

| 版本 | 更新内容 | 下载 |
| --- | --- | --- |
| **1.14** | 完善人物素材准备、辅助生成与干净抠图流程。补充三角翼与单垂尾的人物布局，更新随附制作工具和参考资料。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.14) |
| **1.13** | 完善嵌套 V 的整块切缝构造、镜像与游戏距离可读性检查。增加白色图形、描边和切缝的尺度要求。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.13) |
| **1.12** | 补充新机型的部位布局、面积分配与角度族规则。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.12) |
| **1.11** | 补充 F-2A 的部位尺度、马赛克格距、前缘图形和参考标记处理。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.11) |
| **1.10** | 加入完整基本布局参考，明确先构图、后人物的制作顺序。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.10) |
| **1.9** | 改进机背渐尖图形、凸起结构留白、鸭翼箭头与机型字标。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.9) |
| **1.8** | 完善统一亮漆材质、白色图形比例和嵌套 V 示例。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.8) |
| **1.7** | 改进缓存管理、字体检查与自定义字体配置。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.7) |
| **1.6** | 随包提供完整制作脚本和参考资料，支持独立安装。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.6) |
| **1.5** | 加入风格偏差检查表及设计稿检查工具。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.5) |
| **1.4** | 完善参考构图尺寸与比例规范。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.4) |
| **1.3** | 改进制作流程、自查表、字阶和完整设计示例。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.3) |
| **1.2** | 补充共享 UV、平整区域与垂尾楔形的布局方法。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.2) |
| **1.1** | 完善垂尾外侧人物布局与素材多样性。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.1) |
| **1.0** | 建立深炭底、单一签名色、白色几何与三角马赛克的风格工作流。 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.0) |
