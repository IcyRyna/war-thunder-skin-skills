# 原尺寸边缘与模型观看尺度

在最终包的颜色 DDS 上看边缘，在挂这张 DDS 的目标机模型上看主次。记录使用的贴图、机型、相机和实测比例。如果使用 PNG 做过程检查，交付前在同一部位用最终 DDS 复查。

## 原图裁切

`detail_sheet.py --color <最终颜色.dds> --region echo=x,y,width --zoom 1 --out <新目录>` 从贴图左上角计数，截出宽度为 `width`、高度为 `floor(2 × width / 3)` 的完整 RGB 矩形。用 `crops/echo.png` 看主形边缘、留黑接缝和独立细回声。记录实际岛上的位置；自动选区会选到细节丰富的机械件。回执写入输入 SHA-256 与裁切框。使用 `--composa-copy` 时，编辑器副本保留输入颜色图的透明通道。

若有参考原图，分别给出两图在**这个部位、这个方向**上的实测纹素密度。先用 `crops/*-ref.png` 对照同样的米制粗细，再用 `ref-native/*.png` 核对参考的真像素边缘。展示列为统一尺寸可能经过 Lanczos 重采样，`ref-native` 保留参考的 RGB 原像素。没有两侧密度时，回执的 `metric_comparison` 为 `false`。若缺少原作者贴图，记录“原作同尺度对照未检查”，继续核对自己的 DDS 和模型。

## 实模标尺

在实际机背选两个可见点，取模型世界坐标，确认世界单位为米。坐标可由外蒙皮三角形顶点或重心插值取得。标尺报告两点的直线长度；跨弯折、遮挡或不同朝向的部位换一对点，垂尾用能看清其侧面的相机。下面这个 4 米平面段是输入格式示例，实作时替换两端、相机方向和中心。

```json
{
  "eye": [-0.55, 1.0, 0.3],
  "up": [1, 0, 0],
  "width": 900,
  "height": 900,
  "target_world": [0, 0.7, 0],
  "meter_ruler": {
    "start_world_m": [-2, 0.7, 0],
    "end_world_m": [2, 0.7, 0],
    "target_px_per_m": 100
  }
}
```

`scene_preview.py render --scene scene.json --view iso --mode layout --camera camera.json --out spine.png` 会沿该段校准比例。回执的 `ruler_measurement` 给出端点屏幕坐标、米数、像素数、实际 px/m 和是否在画框内。复看旧截图时，在冻结的原相机参数（`basis/center/scale/width/height`）中仅加标尺端点，即可测量既有取景。新构图显式校准时去掉 `zoom`。

按原始 PNG 的像素大小检查，记录目标区域的主形、留黑孔洞和细回声能否分开。图上可见性要结合模型遮挡和表面朝向判断，`endpoints_in_frame` 只说明两个坐标落在画框内。该比例模拟屏幕上的观看大小，实际游戏相机、纹理过滤与光照仍需在对应游戏截图中核对。
