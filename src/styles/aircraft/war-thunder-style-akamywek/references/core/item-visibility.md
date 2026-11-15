# 判断指定图元在某个相机里能否看见

原 UV 的 `sample_hits` 说明颜料写入了贴图。要查一条腹线有没有出现在某个已渲染的仰视画面，可以对原设计做一次对照：烘完整设计，再只移除那条线重新烘焙。对同一相机中最靠前的三角形，分别取两份合成贴图的 RGB。两次 RGB 的差值就是这项装饰在该校样中的屏幕贡献。同色蒙皮、遮挡物和后面覆盖的其他图层都会影响结果。

```powershell
python -B scripts/item_visibility.py --design design.json --geometry geometry.npz --base clean-base.png --protect mechanical-mask.png --material "该颜色贴图绑定的材质名" --view views/belly.json --item "左腹线ID" --item "右腹线ID" --width 2048 --out 新建目录/腹线.json
```

使用真实的设计、底色和机械罩。若原来没有保护罩，可省略 `--protect`。输入视图是 `scene_preview.py render --mode layout` 的相机 JSON，需要对应的 PNG、depth NPZ 与原 scene JSON。工具核对图像、几何、深度、相机与场景哈希。材质名在 `scene.json` 中查，同一颜色文件被其他材质共用时也检查它们。每个 ID 必须唯一。支持原生多边形、描边、图片与文字，保留原设计的渐变、图案、裁切、合成顺序和遮罩。一次挑少数疑点，每项需要额外烘焙一次；过程文件位于系统 TEMP。输入损坏、目标缺失、不支持的类型或材质着色视图会以 `uninspected` 非零退出。

`--width` 为核验用 atlas 宽度。默认优先选不超过 1536 px 且能保持原比例的宽度。指定原宽可在原 atlas 尺寸复烘，需要相应内存与时间。查看 `comparison_scope`：若 `full_proof_differs_from_saved_gt1` 非零，屏幕计数仅代表按输入重建的校样，另在原记录或最终 DDS 上核查实际局部。

| 结果字段 | 如何判断 |
| --- | --- |
| `paint_sample_hits`、`changed_atlas_texels` | 分别是进入合成的子采样数、移除该图元后最终 RGB 改变的纹素数。后者为零时可由同色或后续层完整覆盖造成。 |
| `on_carrier`、`other_shared_surface` | 报告落在目标图表的可见面、以及同一张颜色贴图映射在其他图表上的像素数、包围框、纵向行数和最大通道差。 |
| `no_paint_hits`／`no_composite_rgb_difference`／`no_screen_difference` | 分别对应没有绘制样本、没有最终涂层色差、贴图有色差但在本相机无屏幕差。 |
| `only_other_surface`／`trace_only`／`visible_rgb_difference` | 分别代表只在别的共用面出现、本面仅一像素或最多一个色阶，以及本面可测到更明显的 RGB 差。还要在实际尺寸观察持续长度、对比和遮挡，数量本身不判美术认可。 |

结论只适用于该相机、这组贴图及当前采样尺寸。缩小校样可能吞掉极细边缘。需要区分“相同 RGB”和“形状根本没画上去”时，一起看图元绘制回执和同机原尺寸局部。
