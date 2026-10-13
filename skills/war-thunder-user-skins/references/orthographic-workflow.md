# 喷气式飞机的原 UV 正交制作

路径为“模型与原 UV → 正交参考 → 分方向设计 → 可见性投射 → 回烘原 atlas → 模型检查”。保留模型姿态、原 UV、部件变换和材质分组。仅有二维 atlas 无法恢复准确的三维投射关系。

## 几何与资源

使用实际可渲染的网格、原 UV 和材质关系。资源检索核对内容，按需要优先使用更新资源；容器解压不等于网格解码或 DDS 转换。将节点、骨架/部件变换、材质与 UV 清单留在工作区，控制互斥挂载和显示状态。

`scripts/surface_preview.py prepare` 通过配置的解码器筛选目标颜色资源对应的静态几何。`--tools` 指定含 `wt_assets.py` 与 `dae_backend.py` 的工具目录；也可设置 `WT_ASSET_TOOLS`，或放在工作区 `tools/war-thunder-assets`。解码器不是此 Skill 的内置模块；缺少它时使用已有 `geometry.npz` 或取得受支持的解码器。

几何 NPZ 使用 `triangles`、`uvs`、`node_ids` 和 `names`，三角形及坐标需为有限数值。模型坐标与导入姿态要保持一致。prepare 支持节点 glob 排除，生成原 UV 静态布局数据，不模拟全部动画和游戏着色器。

## 正交参考与绘制

```powershell
python scripts/surface_preview.py render --geometry output/geometry/geometry.npz --texture textures/body.tga --view top --view bottom --view left --view right --view front --view rear --view iso --width 2048 --height 2048 --out output/guides
```

参考图、相机 JSON 和深度数据作为同一组使用。各方向由同一模型姿态生成；独立画布的比例与缩放记录保留在相机数据中。校验相机横轴、竖轴和朝向的旋向，文字应在侧视与斜视保持一致。

在编辑器保持每张参考的尺寸、位置和方向。参考底图单独隐藏，导出透明设计层；裁切或重新缩放画布会使投射失配。直接 UV 局部编辑可跳过正交投射。

人物试放之前识别部件边界和真实连续表面。需要时根据深度归属、节点或实际 UV 制作单独的主翼/垂尾范围参考；这些范围用于检查和限制误投，不用于把已经跨空隙的大人物硬切成碎片。先移动、缩小或主动裁切人物，使脸、颈肩与关键手势落在安全区域，再回烘。垂尾与翼面使用各自的构图，底视设计只含线条、色面与材质。

## 投射与共享纹素

```powershell
python scripts/surface_preview.py bake --geometry output/geometry/geometry.npz --base textures/body.tga --overlay output/guides/top.json=design/top-overlay.png --out output/body-painted.png
```

覆盖图与相机 JSON 精确配对，投射使用深度可见性与有符号面朝向。薄翼背面不得因深度容差或取绝对法线误接受前侧图案。提高 `--min-facing` 可减少近乎侧视表面的拉伸，随后检查相关表面覆盖。

共享 UV 的多个方向可能竞争同一像素。辅助脚本按 facing×alpha 选择候选，不能代替图案冲突判断。保持连接面的大形连续，非连续表面另行安排，不能将正交图按矩形拼到 atlas。

垂尾内面可能被另一片尾面遮住，主侧视的深度投射不一定覆盖。检查部件与 UV 后，使用能观察该面的相机、单独部件投射或直接 UV 编辑；保留与原模型一致的坐标和方向。不要将外侧投射已命中当作两片垂尾全部完成。

## 回烘后检查

重新渲染顶底、两侧、前后与斜视，并补看反向斜视或尾面局部，检查文字、人物轮廓、接缝、尾面、镜像和配件。重点确认脸与肩线没有被结构切开、主翼人物没有残片落到平尾或机腹、垂尾确实有人物，以及机背路径能在整体尺寸读出层级。跨部件的人物或字标受到遮挡时，缩小、裁切舍弃、移动或换承载面后重新回烘。投射命中数量和遮罩完整不等于构图通过。

投射默认保留原颜色 alpha；打包材质使用已确认的原图或明确编辑过的通道。近似漫反射渲染用于布局观察，实际材质光照按项目要求另行验证。
