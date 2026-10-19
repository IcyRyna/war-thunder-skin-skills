# 终末地风格坦克涂装

用于 War Thunder 现代坦克的终末地工业风涂装。以 A7V / A7HU 适配为案例，整理了黑白黄分区、工业标志、粗细路线和设备标签的摆放方法。

Skill ID：`war-thunder-tank-style-endfield` · 当前版本：1.0

[下载](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-tank-style-endfield/v1.0) · [安装](../installation.md) · [更新记录](../changelog/war-thunder-tank-style-endfield.md)

## 能做什么

- 安排灰白装甲面、深色机械区、黄色路径与主次标志。
- 分开处理车体、炮塔、炮管、附加装甲和武器站的实际 UV。
- 检查字标阅读方向、接缝、孔口、共享 UV 和细墙采样。
- 处理颜色、结构法线与 AO，用原尺寸图和离线模型检查结果。

## 随包素材

安装包约 61 MB，共 48 个文件，其中 35 项为素材与参考：

| 内容 | 尺寸或数量 |
| --- | --- |
| 车体与炮塔 UV | 各 8192 × 8192 |
| 炮管 UV | 4096 × 2048 |
| 机枪座 UV | 1024 × 512 |
| 原作局部裁片 | 22 组，附坐标与阅读方向 |
| 标志与提取资料 | SVG / PNG、透明徽记、分层提取工程与元素图板 |

完整素材包含在 Release 的 `.skill.zip` 中。来源与处理方式见包内 `assets/manifest.json`，选用说明见 `references/assets.md`。

## 车型适配

换车时需要重新确认构件、UV 和采样关系。车名接近，不代表贴图可以直接套用；新增武器站、观瞄和附加装甲也需要单独安排。离线预览用于检查构图和贴图，最终显示效果仍需在游戏中确认。

随附工具包括 DDS RGB 展开、贴图检查、Composa 连接和离线模型预览。参考涂装与官方素材见[来源说明](../credits.md)。

[源码](../../skills/ground/war-thunder-tank-style-endfield/) · [返回首页](../../README.md)
