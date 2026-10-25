# 涂装工作台：4K、人工校准与自动导入

从战雷安装文件夹读取真实模型，在浏览器查看原生 UV 并修改颜色。无需启动游戏或 Blender。固定 Three.js 0.180.0 随包提供，查看时无需 CDN。这是独立的网页预览工具，不改变正式 Skill 的版本、安装包和发行记录。

## 在线交互预览

打开 [涂装作品集](https://icyryna.github.io/war-thunder-liveries/)，进入每套作品的介绍，直接查看对应车型的三维预览。在线版只提供旋转缩放、反射开关与强度、接缝凹凸、512–4K 清晰度、视角切换和保存预览图；“展开查看”仍是纯预览页。

在线发布包使用独立的 `preview.js`，通过 `python -B tools/build_online.py --out 新目录` 生成白名单文件；不分发编辑器、图层、区域改色、贴图替换或工程导入导出代码。旧的 `app.js`、`editor.js` 等地址不会进入在线发布目录，也不能通过网址参数开启编辑。

涂装 ZIP／文件夹导入、游戏目录提取、装饰与图层编辑、区域改色、部件分类修正、工程及贴图导入导出均保留在本地工作台。下方本地启动和使用方法保持不变。

## Windows 一键启动（推荐）

**[下载 Windows x64 便携包](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-paint-workbench/v1.0.0/wt-paint-workbench-windows-x64.zip)** · [本地版发行说明](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-paint-workbench/v1.0.0)

完整解压 ZIP，双击 **启动工作台.cmd**，浏览器自动打开。无需预装 Python、Git、Blender 或管理员权限。包内自带 Python；首次联网下载约 70 MB 固定依赖并校验 SHA-256，之后可离线使用。自动识别战雷安装目录，找不到时弹窗选择。换目录前先停止服务，再双击 **选择战雷目录.cmd**。启动窗口按 Ctrl+C 结束本次服务。

**制作前先告诉 AI：可以使用这个本地工作台预览模型和检查涂装，并给它完整解压路径。** 包内 [先读我](先读我.md) 有可复制提示词，[给AI的说明](给AI的说明.md) 给出启动、车型初始化、读取本机 URL 和检查流程。网页左侧也显示提醒。

源码运行仍支持 Python 3.10+：首次 `./extractor/setup.ps1`，再执行 `python -B preview.py serve`。源码方式要求系统 Python 和 Git；便携包不需要。资源解码目前支持 Windows x64。可用 `--game-dir` 指定安装目录，`--work-dir` 指定导入输出；默认输出 `%LOCALAPPDATA%/WT-Paint-Workbench/imports`。多个安装副本时明确选择；服务仅监听 127.0.0.1。

自行构建：`python -B tools/build_windows.py --out 新包.zip`。运行时二进制仅作为 Release 附件，不进入 Git 历史；固定来源、哈希和第三方说明见 portable-lock.json 与 THIRD-PARTY.md。

## 导入现成涂装

点击“打开涂装 ZIP”或“打开涂装文件夹”。文件夹支持已经解压的 UserSkins 目录；浏览器把需要的文件交给本机服务，不上传外网。解析 BLK 的 replace_tex / set_tex，读取实际 `.grp` 模型目录匹配车型，再提取并绑定颜色贴图。

- 普通涂装：从已安装游戏读取配套模型。
- 带配套 `.grp` 的包：优先读包内匹配模型，保留其 UV；必要描述文件从游戏复制到工作目录。不会替换游戏文件。
- 包含多套配置或多个可能子型号：列出真实候选供选择，不随意猜一个。
- 现有 DDS/TGA/PNG 是合并底图，无法可靠恢复作者以前贴上的每个装饰；新加图案和 AI 分层工程可以逐层编辑。

源 ZIP/文件夹始终只读。包中脚本不会执行，路径越界、链接、重复路径等输入拒绝。支持 ZIP（含一层 ZIP 包装），不支持 RAR/7z。服务上传上限 512 MiB，解压总量上限 1 GiB/1024 成员；网页文件夹入口最多 64 个相关文件、总计 256 MiB，只读取 BLK/DDS/TGA/PNG/GRP。较大的目录可用命令行入口。

```powershell
# 在已准备解码依赖的 Python 中运行；--out 必须为新路径
python -B skin_import.py import --input './涂装.zip' --out './work/skin-01' --game-dir 'D:/Games/War Thunder' --extractor './extractor/wt_assets.py'
# --input 也接受解压目录。若返回 needs_selection，按 discovery 与实际候选继续：
python -B skin_import.py build --discovery './work/skin-01/scan/discovery.json' --out './work/skin-01-selected' --vehicle ztz_99a --blk 'UserSkins/99A/cn_ztz_99a.blk'
```

`--extractor` 必须指向真实的资源导出器；独立包 setup 后入口具体路径以 doctor 输出为准。准备结果的 scene/scene.json 可传给 `preview.py serve --scene PATH`。导入日志、原文件副本、配置及来源哈希保存在工作目录中；它们不是可公开分发的素材。

## 直接提取或打开已有模型

```powershell
python -B preview.py init --vehicle ztz_99a --out ./work/99a --serve
python -B preview.py prepare --model-dir ./native-model --bindings ./bindings.json --out ./scene-new
python -B preview.py serve --scene ./scene-new
```

默认提取 LOD1，`--lod 0` 选全精度。保留所选 LOD 的节点、三角面、材质关系和原生 UV，不自动减面。prepare 接受资源工具导出的 assembly.obj、materials.json、summary.json。bindings 例：`{"materials":{"ztz_99a_body_ussr_camo_green":"textures/body_c.dds"}}`，路径相对该 JSON，名称必须匹配实际材质。也可在页面打开自包含 GLB，或同时选择 OBJ、MTL 和颜色图；OBJ 需已经在整车装配坐标。GLB 不允许隐含外部网络资源。

## 512 到 4K

“模型显示清晰度”调整真实渲染缓冲和显示纹理上限：512、1K、2K、4K；像素比固定 1，不乘设备缩放比例，硬件上限不足时显示实际尺寸。按需渲染，无持续动画、后处理或动态阴影。档位不改变模型面数；大模型仍需选择合适 LOD。

“这张贴图的画布”独立决定输出长边：跟随原图或 512/1K/2K/4K，保留原图宽高比例。2048×1024 调到 4K 输出 4096×2048，方图为 4096×4096。低清预览不会降低最终 PNG；原底图始终保留，导出时重画到目标尺寸。放大低清底图不会产生新细节，新增文字、形状和高分辨率装饰则按输出尺寸绘制。

## 人工操作

1. 在模型或左侧分类中选部件，右侧切换要改的贴图。中文类别由模型名字推测，能够修改名称、分类并人工确认；展开详情查看原始名字，不把推测说成模型语义识别。
2. “加装饰图”导入透明 PNG；“加文字”“加色块”新增独立层。点模型落位，在平面贴图拖动或输入位置百分比、宽度、角度精调。图案按不透明区域选中，透明空白会跳过。每层有缩略图、类型、来源和是否手动改过，支持锁定、显隐、翻转、复制、重排及删除。
3. “框选改色”拖框，“圈选改色”逐点围选后完成。可保留明暗、直接盖色或加深底色；可给选中部件整体改色。关联部件后可限制在它的 UV 区域，但共享/重叠 UV 仍会联动其它面，需要反查 3D。
4. “画笔修补”在平面贴图绘制；“擦图层”只擦当前层，保留底图。每材质最多 64 层、32 步撤销历史。图案最大 8192 边长、16 MiB PNG，工程最大 128 MiB。
5. “保存可编辑工程”保存基底、内嵌图案、全部图层、分辨率和部件分类，重新打开时校验模型与底图身份。“导出这张贴图”保存 PNG，“导出改过的贴图 ZIP”包含全部已编辑颜色图。

当前编辑器输出 RGB 颜色图，尚未回写游戏 C Alpha、N/AO，尚未直接生成可安装 DDS/BLK 游戏包。游戏生产须回到该车型已核实的材质契约。不能把这些 PNG 或 ZIP 称作完整游戏包。

## AI 保留可接手的图层

AI 应直接执行初始化/导入，不把调用模型的工作交给用户。取得场景后生成方案，而不是把所有装饰烘成一张图：

```powershell
python -B project.py template --scene ./scene/scene.json --out ./plan.json
python -B project.py build --scene ./scene/scene.json --plan ./plan.json --out ./AI可编辑工程.json
```

template 给出真实模型身份与可编辑材质。给目标材质填写 layers；透明 PNG 的 file 相对方案目录或 `--assets-root`。示例：

```json
{"name":"真实材质名","layers":[
  {"type":"decal","name":"炮塔徽记","file":"assets/emblem.png","x":0.5,"y":0.4,"width":0.15,"rotation":0},
  {"type":"text","name":"车号","text":"217","x":0.4,"y":0.5,"fontSize":0.03,"color":"#ffffff"},
  {"type":"tint","name":"小区域试色","points":[[0.1,0.1],[0.2,0.1],[0.2,0.2]],"color":"#d6ad41","blend":"color"}
]}
```

x/y 是图像左上角起算的归一化中心，width 为图宽比例，fontSize 相对图宽。shape 使用 width/height，brush 使用 strokes（points、width、color）；erasures 保存擦除轨迹。图层可带 part_refs/clipParts，以页面导出的“给AI的部件与贴图清单”中稳定编号关联。parts 可保存中文 label/category 建议；AI 建议强制未确认，由人工核对。

build 校验模型、源图哈希、素材路径与尺寸，标记 origin=ai、manually_adjusted=false，内嵌原图与素材，生成自包含工程。网页可打开并继续校准；人为修改保留 AI 来源并标记“手动改过”。工程模型与材质身份不符时拒绝载入。不要将 AI 建议当作用户认可，也不要在未审候选中写回正式 Skill。

## 原车外观与反射支持范围

直接显示原车 masked C 的 RGB 会露出未覆盖底层，出现像残骸的外观。默认已结合真实迷彩槽平均 RGB 与原 C Alpha 生成标为 stock-camo-approx 的正常涂层近似；没有完整第二套迷彩 UV，不复现多色平铺、损伤和完整 Dagor shader。固定用户颜色绑定不会再被刷绿。资源提取优先高分辨率；仅找到 `$tq` 缩略级的小件明确标记，编辑前要求补正确底图。

已读取真实 N 贴图中的反射数据：R 为反向粗糙度，B 为金属度，G/A 为法线 X/Y，转换成线性 glTF PBR 材质。涂装 `replace_tex` 的 N 贴图优先，没有替换时从游戏文件夹读取配套资源。中文面板可开关反射、调节反射强度、开关接缝凹凸，内嵌预览也有反射开关。环境反射采用本地生成的柔光棚，无需下载 HDR。512–4K 档位同时控制颜色与材质图显示；2K/4K 按需读取并校验原尺寸展示材质。未能读取的小附件保留模型原设置。颜色编辑不改动反射贴图，暂不回写 N/AO；完整 Dagor 着色器、AO、特殊材质和游戏光照以游戏内为准。

通道依据：[War Thunder 官方 Custom skins](https://wiki.warthunder.com/cdk/creation_camo)。`prepare` 的 bindings 支持 `"surface_materials":{"实际材质名":"textures/body_n.dds"}`。N 的 Alpha 是法线数据，不作为透明度。

## GitHub 与依赖

静态 web/ 可作为在线查看器；普通托管网页不能直接搜索本机战雷文件夹。自动 ZIP/文件夹导入必须使用本地服务；线上静态页会明确提示。网页随仓库部署到 GitHub Pages；正式 Skill 与历史交付保持各自的发行版本。

- Three.js 0.180.0（MIT），来源与校验见 provenance.json，保留 vendor/LICENSE.txt。
- 原生资源解码基于 [Dagor Asset Explorer](https://github.com/quentin-dh/Dagor-Asset-Explorer) 固定 revision `1f0d1e04ded04bf9b28e8d5be93cb79714f505d3`。资源封装适配来自本工作区维护的 war-thunder-assets，候选独立复制，不回写旧工具。
- 不分发游戏模型/纹理、不包含本机路径或研究工程。没有编译 Gaijin 完整引擎，也未证明所有车型、浏览器、低配设备适用。

测试：`python -B -m unittest discover -s tests -v`；纯编辑逻辑：`node --test tests/editor-core.test.mjs`。两者不代替真实浏览器与游戏验收。
