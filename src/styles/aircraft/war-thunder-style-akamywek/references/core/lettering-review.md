# 外侧机位上的字向

涂装已经有文字，先写明**谁站在哪一侧、从哪一个机位读哪一组字**。两肩、两侧垂尾和左右平尾分别指定接近实际观看姿态的外侧相机。只在设计要求从该侧顺读时采用该目标。机背纵排、故意倾斜、左右不同内容，各用自己的阅读方向。

为每个机位保留 `scene_preview.py render` 的原 PNG、JSON 和深度／三角形归属 NPZ。准备与烘焙相同的设计、几何 NPZ，以及同一次 `vector_paint` 的 `receipt.json`。相机须能清楚看到该字所在表面。下例在左外侧要求主字向右并允许随肩线略斜，另一行有意采用沿画面向右上方 30° 的排列：

```json
{
  "views": {"port": "views/quarter-port.json"},
  "checks": [
    {"item":"port-shoulder-main", "view":"port", "baseline_deg":0, "tolerance_deg":40},
    {"item":"slanted-port-caption", "view":"port", "baseline_deg":-30, "tolerance_deg":20}
  ]
}
```

`item` 是设计稿的具体文字图元 ID。路径相对于计划文件，亦可用绝对路径。`baseline_deg` 从字首沿基线指向字尾，按图像屏幕坐标计，向右 0°、向下 90°；`tolerance_deg` 是容许的偏角，可取大于 0、小于 90 的度数。检查同图表中的特定接收面时可加 `"nodes":["wing_l"]`，匹配实际节点全名。

```text
python -B scripts/check_lettering.py --design design.json --geometry geometry.npz --plan reading.json --paint-receipt paint/receipt.json --out lettering.json
```

使用全新的输出文件。`--require-pass` 可让任何非 `pass` 方向结果返回非零退出码，仍保存报告。若烘焙回执记录了该字命中机械遮罩，再加 `--protect <烘焙时的原生遮罩>`。使用 `--proof-width` 的缩小校样会沿用原尺寸岛选择，并按校样尺寸复算保护和纹素归属；回执记录 `native_atlas` 与 `inspected_raster`。缺少烘焙回执时可先检查投影，覆盖栏会记录 `no_bake_receipt`。

工具沿用原生 UV frame、世界图表轴和文字的真实字体、旋转、翻转、剪裁与笔画轮廓；逐个屏幕像素核对相机可见三角形及字的基线和字头。回执记录 PNG、深度和相机绑定、肉眼复查用的框 `visible_box_xyxy`、有效笔画像素和横纵跨度。遇到纹素争用，工具以烘焙使用的规则重算 UV 所有权，只给可靠归属的可见笔画计票。

| 结果 | 接下来核对 |
| --- | --- |
| `pass`、`upside_down`、`mirrored`、`off_axis` | 依次表示可见笔画符合目标、整体倒置、字形镜像、基线偏出目标。核对未旋转的左右截图和报告中的角度，再改具体图元。 |
| `occluded`、`out_of_frame`、`undetermined` | 分别检查遮挡、画框、承载面、分辨率和有效笔画跨度。曲面或重叠面出现相互矛盾的方向时改用更合适的机位，或分别选择实际承载节点。 |
| `not_painted` | 绑定的烘焙回执报告该图元零命中。回查图表、岛、遮罩与图元位置。 |

方向、可见性与烘焙覆盖分别看。`coverage=partial` 表示该字有非归属或保护样本；仍能判断可见字的方向时会保留该判定。`visibility=partially_occluded` 表示投影中的部分笔画被前方表面挡住。看到 `pass` 后仍需在**最终 DDS 同机位实图**逐字看正反、缺笔、可读尺寸与间距。本工具按设计稿推导字形方向，不做 OCR；整机其他共享 UV 副本、用矢量轮廓画的字或嵌在位图里的字，须在对应的实际观看面另查。
