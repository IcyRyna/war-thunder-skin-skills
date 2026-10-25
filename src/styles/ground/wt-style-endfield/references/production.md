# 制作工具与工程入口

随包 `scripts/` 带固定版本地面工具，来源哈希见 [tool-provenance.json](../tool-provenance.json)。它们提供检查、语义过滤、DDS、模型预览和 Composa 客户端，不自动构图、不含编辑器／游戏／模型。Python 3.12；图像与 DDS 用 Pillow、NumPy，离线 OpenGL 预览另需 ModernGL。查看 [requirements.txt](../requirements.txt)；texconv 仅 BC3 路径需要，二进制另行提供并在配置中声明。

先读命令帮助与本车输入，不能仅凭入口存在声称生产通过：

```text
python -B scripts/asset_pack.py check
python -B scripts/asset_pack.py sheet --out <TEMP>/endfield-assets.jpg
python -B scripts/asset_pack.py budget <预览1.jpg> <必要局部.png>
python -B scripts/place_decal.py --help
python -B scripts/inspect_skin.py --help
python -B scripts/ground_dds.py --help
python -B scripts/tank_preview.py --help
python -B scripts/composa_mcp.py --help
```

`asset_pack.py budget` 对本批实际文件按 Base64 长度加 128 KiB 固定预留估算，超过 18,000,000 B 返回非零；它不知道会话既有图像、客户端重试和协议开销，不能声称实际总请求已受硬限制。常规每批尽量 1–3 MB。

`place_decal.py` 的 `--x/--y` 是输出有效墨迹左上角，`--ink-width` 是目标有效墨迹宽度，单位均为输出像素。只生成透明叠加层；不做 UV 自动遮罩，也不改原资产。默认拒绝可见墨迹出画布，用户明确需要局部贴花时再使用 `--allow-clipping`；完整主徽记不要裁。先读取回执中的变换与放大警告，再把图层置于本车承载区并复查。

`ground_dds.py` 使用真实 input、manifest、profile、config 和 out；各字段来自本车，不把示例占位替成路径后直接当生产配置。`inspect_skin.py` 核对最终目录与可选 materials／manifest／profile。共享代码继承的能力与限制不因重建风格包扩大。

编辑器优先沿用当前任务可用入口。Composa 的 Allow AI Control 已启用且处于已授权任务时直接连接，以实时 schema 为准。只关闭本批自有文档，未保存修改先存检查点；测试重开工程使用副本，保护原先文档。正常看模型优先复用本地轻量预览的实际场景，先核对车型；无此环境才用当前可用离线工具。七视图需要该次明确授权。

生产按层保存：基底／明暗／路径／品牌／设备／纹样／表面效果。最终输出后从实际 DDS 读回并回到模型，源工程用副本重开；不能只验证源 PNG 后声明交付 DDS 正确。


## 显式真实面映射

`native_plane_map.py --model <本车NPZ> --profile <本车JSON> --design <完整RGBA-PNG> --out <新SVG>` 把完整母版投影到明确选择的真实三角与原生 UV。NPZ 使用 `positions[N,3,3]`、`uvs[N,3,2]`、`material_ids[N]`；本车表面 JSON 明确 `triangles`、`atlas_size`、`uv_origin=bottom_left`、`normal`、`horizontal_hint`、`up_hint`、`anchor_world`、`design_width_m`，可选原生 `crop_box` 与模型文件 SHA-256。坐标、图集与模型单位必须来自本车，包内不提供跨车型坐标。

它保留原 PNG 的 RGB/Alpha 和投影平面内的统一比例；不会自动挑面、处理共享 UV、绕开遮挡或保证弯曲面沿面等比。默认拒绝任何有效墨迹离开所选承载面；默认不裁切。明确跨真实内部窄板缝的图形，可在核对整体轮廓与关键字形后设置 `allow_artwork_clipping=true`，记录损失像素与实际缝隙；还须证明源墨迹没有越过承载面外边界。完整母版不得拆裁，文字保持可读，不能把外边界裁断伪装成板缝。

可选 `rasterize_native_map.py <该脚本生成的SVG> <新PNG>` 使用 Skia 将这个受限格式栅格化，输出裁区透明层；它不是通用 SVG 解析器，也不渲染任意文字 SVG。需要 `requirements-preview.txt`。栅格化后还要合成本车基底、按正确 Alpha 语义生成 DDS，并回到完整模型检查可见性。SVG 与图层来源应随作品源码保存。

本机 Composa 1.4.0 曾不显示 SVG2 `href` 的嵌入图片／use；映射器采用已实测的 `xlink:href`。仍须检查实际墨迹，而非仅检查图层存在。当前部分编辑工具仅以页签号寻址；本轮遇到其他任务开关文档造成的竞争。并发状态无法隔离时，不对共享编辑会话继续做位置性写入；使用当前任务的独立文件合成流程，保留失败与检查点，不能关闭其他任务文档。
