# 《明日方舟：终末地》机壳贴纸与矢量素材库

> **风格边界（先读）**：本目录供制作 **F-15EX「终末地」同款工业贴花联名变体** 使用。做**纯原教旨 Akamywek** 无人物作品时**不要强塞本目录贴花**，应只保留真实飞机制造商/机体原厂技术英文标；只有在用户明确指定《明日方舟：终末地》题材或此类工业联名变体时调用。

## 目录结构（共 71 个文件）

### 1. `factions/` — 阵营与机构高清纯白透明 PNG（9 张，1024–1400 px，`vector_paint.py` 可直接加载）
由矢量 SVG 高分渲染，透明底无黑框，直接适配炭灰 `#333334` 蒙皮：
- `endfield-industries-white.png`（1024 px）：终末地工业三角徽标（适合垂尾外侧居中、大翼根）
- `endfield-logo-en-white.png` / `endfield-logo-zh-white.png`（1400 / 1200 px）：`ARKNIGHTS ENDFIELD` / `明日方舟：终末地` 宽体主字标（适合进气道/CFT 外侧大平面）
- `endfield-icon-en-white.png` / `endfield-icon-zh-white.png`（1024 px）：紧凑方形徽记（适合垂尾内侧底部、翼尖深带、机背负形）
- `has-white.png`（1024 px）：宏山科学院徽标
- `rhodes-island-white.png`（1024 px）：罗德岛塔楼徽标
- `tgcc-white.png`（1024 px）：环塔商会徽标（TGCC）
- `uwst-white.png`（1024 px）：塔洛斯 II 联合工团徽标（U.W.S.T.）

### 2. `presets/` — 透明底高精度工业 UI 标牌与生成脚本（5 张 + `render_endfield_presets.py`）
基于内置 `Orbitron-VF.ttf` 与 `Michroma-Regular.ttf` 仅依赖 Pillow + NumPy 生成，可跑 `python -B render_endfield_presets.py --title ... --subline ...` 自定义文案，**全部透明底无实心黑矩形补丁**：
- `talos_wiki_bar_dark.png`（1600×320）：斜纹 `TALOS-II` 底字 + `// ARKNIGHTS: ENDFIELD` + `[ ENDFIELD INDUSTRIES ]` + 黄/品红/青绿/斜纹多色状态条 + `┐ ■` 角标（进气道侧壁、CFT 中后段、肩部通道外缘）
- `protocol_reclamation.png`（1280×310）：透明斜条 `/////` + `PROTOCOL // RECLAMATION` + 条码 + `AIC-LINK ACTIVE`
- `aic_dijiang.png`（1240×300）：`AIC // ENDFIELD` + `DIJIANG` + 交替刻度条
- `originium_seal.png`（720×720）：镂空 `TALOS-II` 菱形源石印章
- `caution_no_step.png`（1120×170）：透明隙黄斜纹 `CAUTION // ORIGINIUM PROTOCOL // NO STEP` 长条（主翼根/襟副翼前缘炭灰区）

### 3. `brands/` — 工业装备厂标纯白透明 PNG（28 张去重精选）
来自游戏装备/零件品牌序列的纯白高反差标志（`icon_pack_*` / `icon_suit_*`，涵盖 `STRIKER RAYTHEAN`、`MARTHE`、`ÆTHERTECH LAB`、`Hongshan Swordmancers`、`Northmarch`、`SECURITY Mieszko`、`Endfield × Engineering` 等），尺寸 ~254×145，适合作为**辅助技术细节点缀**置于内翼根、垂尾内侧、机腹及口盖旁。

### 4. `professions/` — 干员职业纯白透明图标（9 张，254×254）
`icon_profession_0.png` .. `icon_profession_8.png`，高清纯白透明徽标，适合作为尾翼、机鼻侧或编队标识小点缀。

### 5. `svg/` — 矢量源文件（17 个）
含官方主标与 4 语种图标（9 个 `endfield-*`）、四大阵营矢量（`has.svg`、`rhodes-island.svg`、`tgcc.svg`、`uwst.svg`、`endfield-en.svg`、`endfield-zh.svg`）及终末地官网等高线底纹（`contour-a.svg`、`contour-b.svg`），可用于无损改色与超分辨率导出。

## 使用与排布红线
1. **跨部件遮挡必须整机检查**：挂载件（CFT、副油箱）上的贴花禁止仅用单挂件场景验收；必须放到包含机身与主翼的完整组装场景检查，防止被翼根边条或挂架挡掉半块徽章。
2. **禁止黑色矩形底垫**：炭灰蒙皮（`#333334`）上的 PNG 贴花保持底图全透明（`alpha = 0`），不要填充 `#000000/#16171a` 方块背景。
3. **有效字高控制**：4096 级子图贴花内的辅助副行字高不宜低于 ~2.5–3 cm，小尺寸图元只放简化图形或粗笔画字组。
4. **控制密度留出呼吸底**：仍应保证全机安静炭灰底与大色场占主导；辅助工业贴花成簇落在进气道、CFT、翼根技术区或垂尾/机腹留白，不撒满翼面与平尾。
