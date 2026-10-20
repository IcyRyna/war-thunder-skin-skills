# 工程操作与数据边界

以下命令的 `$SkillRoot` 指构建后的独立包目录，`$TaskRoot` 指当前已登记任务目录。路径和资源名来自实际任务，示例变量不构成可执行的真实载具配置。完整参数以同一工具快照的 `--help` 与实现为准；命令检查记录保存在执行任务中。

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B "$SkillRoot/scripts/inspect_skins.py" scan "$TaskRoot/assets/template" --out "$TaskRoot/verification/v1-template" --hash --previews 1 --strict
```

普通扫描是 BLK 与头部范围；`--previews` 才增加选中纹理解码。检查器不查询游戏资源库、不执行 include、不验证 UV。保持原模板只读，使用精确 `from` 资源名；不要用重写输出掩盖原 BLK 歧义。

## 从模板到几何

已有适用且哈希可追溯的 `geometry.npz` 可直接使用。否则 `surface_preview.py prepare` 需要外置解码器目录，其中应包含 `wt_assets.py` 与 `dae_backend.py`；先查 `prepare --help`，用明确的 `--tools` 指定经过核对的适配器。解码器不包含在本包，解包完成不等于网格或纹理已解码。

多材质场景的入口是标准解码目录，包含 `parts.json`、`materials.json`、部件 OBJ 与纹理；用 selection JSON 的 `schema_version`、`description`、`include_nodes` 明确显示节点：

```powershell
python -B "$SkillRoot/scripts/scene_preview.py" prepare --asset "$TaskRoot/assets/decoded" --selection "$TaskRoot/design/scene-selection.json" --out "$TaskRoot/workbase/v1/scene"
python -B "$SkillRoot/scripts/airframe_setup.py" map --geometry "$TaskRoot/workbase/v1/scene/geometry.npz" --scene "$TaskRoot/workbase/v1/scene/scene.json" --texture $SceneTextureSelector --out "$TaskRoot/workbase/v1/map"
python -B "$SkillRoot/scripts/airframe_setup.py" frames --geometry "$TaskRoot/workbase/v1/scene/geometry.npz" --scene "$TaskRoot/workbase/v1/scene/scene.json" --texture $SceneTextureSelector --out "$TaskRoot/workbase/v1/frames.json"
```

`$SceneTextureSelector` 是场景内的颜色文件或材质名片段，按帮助与真实记录选择；它不是下文组装命令使用的精确 BLK `from`（`$ColorResource`）。轴向从几何／定位结果确认；不能假定鼻尖沿 +X、左右沿 ±Z。几何数组契约为 `triangles (N,3,3)`、`uvs (N,3,2)`、合法索引与名字；保留原装配变换、UV、材质分组和真实显示状态。排除辅助面要有证据，不能任意删几何。

`map` 产生岛与坐标资料，`frames` 产生局部框架与拟合残差。残差大说明平面框架不适合该区域，不说明工具会自动修正圆周展开。`clean` 和 `shares` 带历史风格假设，不属于上述通用准备步骤。

## 直接 UV 与矢量路径

真实 UV 上使用编辑器时保存独立文字、形状、图案与像素层。使用 `vector_paint.py` 时，保存 `schema_version: 1` 设计 JSON：

- `atlas` 规定尺寸，`palette` 给明确颜色；颜色来自当前设计。
- `charts` 用 `u/v` 轴、`nodes/materials`、`normal/where/facing` 等选择实际表面；`island` 用像素种子选择 UV 连通岛。
- `frame` 以 atlas 像素原点与每设计单位的两个向量定义坐标；单位与拟合证据来自 profile。可用 `uv_frame.py` 拟合。
- `layers` 中的 `items` 是 polygon/stroke；`images` 可放源图或文字。文字需要真实字体路径，图文比例与位置来自设计。
- 同一三角按第一个匹配图表分配；共享纹素的优先级不是独立颜色能力。顺序必须由区域与共享关系决定，不存在通用“某部位永远优先”规则。

```powershell
python -B "$SkillRoot/scripts/surface_map.py" --geometry "$TaskRoot/workbase/v1/scene/geometry.npz" --design "$TaskRoot/design/design.json" --protect "$TaskRoot/assets/protect.png" --out "$TaskRoot/workbase/v1/surface-map"
python -B "$SkillRoot/scripts/vector_paint.py" --geometry "$TaskRoot/workbase/v1/scene/geometry.npz" --design "$TaskRoot/design/design.json" --base "$TaskRoot/assets/base.png" --protect "$TaskRoot/assets/protect.png" --out "$TaskRoot/workbase/v1/vector"
```

遮罩白／非零表示保护。检查每层 `painted_texels`、`zero_hit_items` 及视觉结果；图元命中不证明可见。surface-map 对 frame 图表的世界轴可见性可能不适用，结合真实模型检查。出血和 supersampling 是采样配置，按本区域密度与边界验证，不从像素边长推断有效细节。

## 正交投射路径

```powershell
python -B "$SkillRoot/scripts/surface_preview.py" render --geometry "$TaskRoot/workbase/v1/scene/geometry.npz" --texture "$TaskRoot/assets/base.png" --view top --view bottom --view left --view right --view front --view rear --view iso --width 2048 --height 2048 --out "$TaskRoot/workbase/v1/guides"
python -B "$SkillRoot/scripts/surface_preview.py" bake --geometry "$TaskRoot/workbase/v1/scene/geometry.npz" --base "$TaskRoot/assets/base.png" --overlay "$TaskRoot/workbase/v1/guides/top.json=$TaskRoot/design/top-overlay.png" --out "$TaskRoot/workbase/v1/painted.png"
```

相机、深度、owners、几何与 overlay 尺寸必须精确配对。guides schema 2 绑定几何／深度哈希与相机指纹；几何或相机变化后重建。不能拿完整场景深度配投射子集。当前回烘只支持首个 0–1 UV tile；场景显示支持部分重复 UV 不扩大回烘支持。

有 alpha 的覆盖图零命中会失败，全透明图明确记 no-op。深度、可见 owners 和朝向检查共同限制投射；掠射区域用新相机或直接 UV 接续。共享纹素冲突通过设计一致性、位置、裁切或明确来源解决，不能重排原 UV 或靠优先级覆盖来声称两侧独立。

## 组装 TGA 与 BLK

```powershell
python -B "$SkillRoot/scripts/build_skin.py" --template "$TaskRoot/assets/template" --paint "$ColorResource=$TaskRoot/workbase/v1/vector/composite.png" --reference "$ColorResource=$TaskRoot/assets/original-color.tga" --out "$TaskRoot/delivery/v1/tga"
python -B "$SkillRoot/scripts/inspect_skins.py" scan "$TaskRoot/delivery/v1/tga" --out "$TaskRoot/verification/v1-package" --hash --previews 1 --strict
```

`--paint` 替换指定颜色资源，默认保持原颜色 alpha。`--reference` 指向真实原贴图；可重复传参。`--channel "确切from:R=灰度.png"` 等只在 profile 已验证该资源通道及本次修改意图时使用。输出目录须是模板外的新／空目录；构建使用事务、32-bit TGA、BLK、ZIP 和组装收据，核验像素往返。

DDS 是另外的变体：

```powershell
python -B "$SkillRoot/scripts/dds_variant.py" --input "$TaskRoot/delivery/v1/tga" --out "$TaskRoot/delivery/v1/dds" --texconv $VerifiedTexconv --format rgba8 --role "$ColorResource=color"
```

脚本钉住 DirectXTex `may2026` 的 `texconv version 2026.5.8.1`，SHA-256 为 `dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06`；这是当前代码要求，不表示已验证任何其他版本。二进制未内置。未知资源角色必须显式确认；data 线性过滤，color RGB 在线性光下过滤、alpha 独立过滤。RGBA8 逐像素核对顶层及实际 mip；BC3 只作明确的有损变体。数值 mip 验证不证明目标游戏的运行时过滤。

## 检查、编辑器与交付

```powershell
python -B "$SkillRoot/scripts/scene_preview.py" render --scene "$TaskRoot/workbase/v1/scene/scene.json" --view top --mode layout --out "$TaskRoot/previews/v1/top.png"
python -B "$SkillRoot/scripts/detail_sheet.py" --color "$TaskRoot/workbase/v1/vector/composite.png" --region "critical=120,120,240" --auto 4 --out "$TaskRoot/verification/v1-detail"
python -B "$SkillRoot/scripts/composa_mcp.py" --out "$TaskRoot/verification/v1-editor-discovery"
```

详情坐标换成本区域实际位置。Composa 需要用户已有允许 AI 控制的环境；默认只发现实时 schema，调用文件用 `--calls` 顺序执行。客户端不自动开启控制权限，不重试状态不明的写调用，需查会话收据再恢复。重开测试先复制工程。

以完整可见面、规定尺度、特写与不同光照验收；模型渲染、近似材质、实际游戏分别记录。运动、损伤、透明玻璃和运行时 LOD 未测即保留未知。最终哈希绑定交付包和对应截图；人工修订、失败与重试同样保留。
