# 终末地风格 · 地面载具

**正式版本：0.1.1** · Skill ID：`wt-style-endfield`

以终末地主题的黑白黄工业视觉为基础，理解原作的明暗分区、黄色路径、工业徽记和密度关系，再在目标载具的原生 UV 上重新构图。

**[下载正式安装包](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-endfield/v0.1.1) · [安装指南](../installation.md) · [更新记录](../changelog/wt-style-endfield.md)**

![A7V 参考作品的终末地整车效果](../../assets/endfield/reference/a7v/iso.png)

## 包含什么

| 内容 | 中文解读 |
| --- | --- |
| A7V 参考解析 | 解释色面、路径、工业标识与细节密度怎样配合 |
| 五车型家族建议 | 提供不同外形的四向布局方向，供目标车型调整 |
| 部件与子区 | 区分车体、炮塔、炮管和局部可阅读表面 |
| 可编辑素材与可选预设 | 作为重新构图的素材和起点 |
| 独立工具 | 支持布局准备、纹理处理、检查和离线预览 |

## 模型与 UV 对照

Blender先确认真实构件、材质槽和UV岛，再在PS／Composa以1:1核对对应纹素；修改后重新载回同一模型，交付前读回最终DDS在两边复查。

[完整方法](../../src/styles/ground/wt-style-endfield/references/model-uv-cross-check.md)。成对检查关联同一资源、部件、像素区域和检查ID；缺少任一侧标为 `not_run`，UV对应不明标为 `unresolved`。随包 ModernGL 预览不计作 Blender 检查。

## 使用顺序

1. 核对目标车型、模型、原始纹理和材质通道。
2. 先确定整车明暗和主路径，再安排徽记、字标及局部模块。
3. 在模型上检查主要视角、共享 UV、接缝与部件运动关系。
4. 保存分层工程，导出游戏包，分别记录技术、视觉与实机检查。

车型方向图用于理解和选择，具体 UV／DDS 生产与游戏验证按目标车执行。新版本采用原生 UV 流程。

[五车型详细图解](endfield-layout-guide.md) · [0.1.1 全部规则、素材与工具](wt-style-endfield-0.1.1.md) · [历史兼容版本](../history/README.md)

[返回选用指南](../../README.md) · [中文术语](../terminology.md)
