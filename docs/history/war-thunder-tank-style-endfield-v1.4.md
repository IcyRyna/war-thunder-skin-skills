# 终末地风格坦克涂装 1.4（历史兼容版）

用于 War Thunder 现代坦克的终末地工业风涂装。结合 A7V / A7HU / A6HEL 的适配方法，整理了黑白黄分区、工业标志、粗细路线和设备标签的摆放方法。

Skill ID：`war-thunder-tank-style-endfield` · 已发布版本：1.4

本页保留已发布 1.4 的历史说明。该版本已移出首页与推荐下载；原 Release、标签、附件和下载地址继续保留。风格源码与领域工具现位于 `src/styles/ground/`；完整大型素材仍随原 Release 提供，源码候选构建需按清单补齐。

[下载](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-tank-style-endfield/v1.4) · [安装](../installation.md) · [更新记录](../changelog/war-thunder-tank-style-endfield.md)

当前布局研究与演示见 [A7V 范本、部件分区和五车型方向](../skills/endfield-layout-guide.md)。历史包用于追溯与兼容核验，不作为当前推荐安装包。

## 能做什么

- 安排灰白装甲面、深色机械区、黄色路径与主次标志。
- 分开处理车体、炮塔、炮管、附加装甲和武器站的实际 UV，识别混用图集的载具并分别选择保留或重画。
- 检查字标阅读方向、接缝、孔口、共享 UV 和细墙采样。
- 相关车型在确认表面对应后，逐纹素转入目标原生 UV，处理平铺小件与共享纹素的写入归属。
- 分开处理颜色、结构法线、AO 与粗糙度；清洁涂层保留目标车的螺钉和接缝，消除旧车结构残影。
- 从目标承载面重新布局，限制图形投射范围，检查圆筒文字、字体层级与设备遮挡。
- 从最终 DDS 生成七视图与同相机细节对照，核对小字、线条、漆面和材质；按材质保留网格裁切轮廓。

## 原作复刻与材质

结构确实对应且要保留原作材质时，可转移颜色、完整法线和 AO。清洁漆面分别检查颜色中的旧机械印记，并按目标结构核对法线与 AO。结构不同的附件单独适配。原生法线里的表面噪点与机械结构需要区分，不能把通道一致当作清洁漆面的证据。

## 随包素材

安装包约 62 MB，共 58 个文件，其中 39 项为素材、参考与来源记录：

| 内容 | 尺寸或数量 |
| --- | --- |
| 车体与炮塔 UV | 各 8192 × 8192 |
| 炮管 UV | 4096 × 2048 |
| 机枪座 UV | 1024 × 512 |
| 原作局部裁片 | 22 组图形元素，另加 3 组车首分板 UV，附坐标与来源 |
| 标志与提取资料 | SVG / PNG、透明徽记、分层提取工程与元素图板 |

完整素材包含在 Release 的 `.skill.zip` 中。来源与处理方式见包内 `assets/manifest.json`，选用说明见 `references/assets.md`。

跨板图案先在完整 UV 中定位各片，包含窄倒角，按承载面直接复用原像素。生图可辅助实际缺损的候选修复；原作复刻保留该位置的字形与副标题。

## 车型适配

换车时需要重新确认构件、UV 和采样关系。车名接近，不代表贴图可以直接套用；新增武器站、观瞄和附加装甲也需要单独安排。离线预览用于检查构图和贴图，最终显示效果仍需在游戏中确认。

跨到勒克莱尔等不同车系时，按主徽记、装甲分区、黄色路线和技术标注的职责重新布局。A7 系坐标不作为其他车型的模板。

随附工具包括 DDS RGB 展开、贴图检查、Composa 连接、离线模型预览，以及相关车型的逐纹素表面转移与回归检查。后者按需使用 OpenGL 4.3、OpenCV 和 Numba。参考涂装与官方素材见[来源说明](../credits.md)。

[风格源码](../../src/styles/ground/war-thunder-tank-style-endfield/) · [候选构建与素材补齐](../maintaining.md) · [返回首页](../../README.md)


## 历史基线的素材补齐与构建

地面风格的大型素材通过原 1.4 安装包提供。先从[固定 Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-tank-style-endfield/v1.4)下载 `.skill.zip` 到 `.cache/releases/`，也可使用已登录且有仓库读取权限的 GitHub CLI：

```bash
gh release download 'war-thunder-tank-style-endfield/v1.4' --repo IcyRyna/war-thunder-skin-skills --pattern '*.skill.zip' --dir .cache/releases
```

然后把下载文件作为素材来源传给检查器和构建器：

```bash
python -B tools/repository.py check war-thunder-tank-style-endfield --asset-archive .cache/releases/war-thunder-tank-style-endfield-v1.4.skill.zip --require-assets
python -B tools/repository.py build war-thunder-tank-style-endfield --asset-archive .cache/releases/war-thunder-tank-style-endfield-v1.4.skill.zip
```

素材以仓库清单记录的身份进行核验。不能用其他版本的相似文件补齐，也不能以一份缺素材的包替代完整候选。`.cache/` 与 `dist/` 留在本地，不进入 Git 历史。


[历史版本索引](README.md) · [当前推荐下载](../../releases/README.md)
