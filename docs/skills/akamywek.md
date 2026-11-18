# Akamywek 风格喷气机涂装

`war-thunder-style-akamywek` **1.3.1** 用于在《战争雷霆》喷气机的原生 UV 上制作炭灰、签名色与锐角白形组成的涂装。可从整机无人物布局起步，也可在选定的布局上安排角色。[下载 1.3.1 安装包](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/war-thunder-style-akamywek/v1.3.1/war-thunder-style-akamywek-v1.3.1.skill.zip) · [安装说明](../installation.md) · [版本记录](../changelog/war-thunder-style-akamywek.md)

## 先看对应作品

| 作品 | 已认可范围 | 制作时看哪里 |
| --- | --- | --- |
| F-15C MSIP II「青锋」 | 无人物整机终稿 | 机鼻色场从座舱两侧收进白形。双发后段分左右机舱与中间窄面安排图形，分别收在裸金属边界前。斜俯看两片垂尾的内外面及字标与细框的间距。 |
| F-15C MSIP II「莱万汀」 | 两张不同立绘、双翼脸肩同向的整体构图 | 以同一张机鼻朝上的正俯图比较眼线、下巴和露肩，左右翼按相同尺度查看。清晰度修复时固定人物在翼面上的位置、大小和裁切。 |

「莱万汀」右翼利用同姿势官方近景恢复眼脸和额发细节。左翼保留回身立绘，用超分处理已有图像。修复前后均从实际游戏包解码 DDS，按原尺寸比对眼线、睫毛和发丝。构图已获认可，高清修复效果仍待美术评价。[视觉素材来源](../credits.md)

## 换机型时

已有的 J-16、J-10C 及 F-16C 案例分别展示双发宽机背、窄机身和单垂尾的处理。按目标机重新确定可绘制的蒙皮、活动面和共享 UV。机身、主翼、翼尖和平尾的色块按目标轮廓落位，三角马赛克和双色渐变沿对应机体表面接续。包内的原生绘制、机位标定、模型检查与封包脚本，可用于从设计稿一直复核到安装的 DDS。

[风格源码](../../src/styles/aircraft/war-thunder-style-akamywek/) · [维护指南](../maintaining.md) · [返回首页](../../README.md)

## 1.3.1 材质与排布更新

- 新增缎面高金属清漆预设 `coat_material.py --preset metallic-satin`（`R=163, B=188, G/A=128, 128`）及 `--flat-detail-out` 中性平铺细节法线，消除高反光下的“水波纹”。
- 在 `design_lint.py` 新增同图幅重叠与净距防逼挤检查（`overlapping-placement` / `crowded-placement`），结合 F-15EX 实机经验明确平尾内收、垂尾徽章居中与删减拥挤小副标原则。
