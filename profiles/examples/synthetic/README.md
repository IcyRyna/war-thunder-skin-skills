# 纯合成工程示例

本目录全部是人工构造的测试数据：一块 2×2 m 平面、64×64 颜色／数据图和一块矩形。`synthetic_plate_c*`、`synthetic_plate_n*` 是虚构资源名，不能装到任何真实游戏载具。本示例没有风格规范、已认可作品、真实载具映射或游戏通过声明。

`geometry.npz` 是 +Y 面向的平面，X/Z 各为 −1..1；U=(X+1)/2、V=(Z+1)/2。颜色图 alpha 随 X 变化，用来证明组装保留原 alpha；数据图四通道是任意测试数据，用来证明未编辑通道保持。`region-mask.png` 选择平面的中心区域，`design.json` 在对应 `primary_side` 图表画矩形。示例名字只说明语义映射，不代表飞机某个实际侧面。

从 Skill 根目录运行，结果放到全新临时目录：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
$demo = Join-Path $env:TEMP ('wt-build-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $demo | Out-Null
python -B scripts/vector_paint.py --geometry examples/synthetic/geometry.npz --design examples/synthetic/design.json --base examples/synthetic/template/color.tga --out "$demo/vector"
python -B scripts/build_skin.py --template examples/synthetic/template --paint "synthetic_plate_c*=$demo/vector/composite.png" --reference "synthetic_plate_c*=examples/synthetic/template/color.tga" --out "$demo/package"
python -B scripts/inspect_skins.py scan "$demo/package" --out "$demo/check" --hash --previews 1 --strict
```

这三个命令只证明矢量层求值、精确资源组装、通道保护与静态扫描可以协同工作。不会启动游戏，不运行 DDS 编码。`profile.json` 与 schema 可供独立检查工具读取；这三个旧 CLI 不直接消费 profile。

生成定义：平面由顶点 (−1,0,−1)、(1,0,−1)、(1,0,1)、(−1,0,1) 与三角 (0,2,1)、(0,3,2) 组成。底图 R=130+x、G=140+y、B=170、A=64+2x；数据图 RGBA=(31,73,127,191)。这些数值只用于测试字节保留，没有真实材质含义。
