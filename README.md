<div align="center">

# War Thunder Skin Skills

**面向《战争雷霆》玩家涂装与 AI 辅助制作的 Skill 仓库与本地工作台**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![3D 预览作品集](https://img.shields.io/badge/3D_作品集-在线浏览-0ea5e9)](https://icyryna.github.io/war-thunder-liveries/)
[![Akamywek](https://img.shields.io/badge/✈_Akamywek-v1.21-f59e0b)](releases/README.md)
[![Charcoal](https://img.shields.io/badge/🛡_炭灰工业-v0.2.0-475569)](releases/README.md)
[![Workbench](https://img.shields.io/badge/🛠_本地工作台-v1.0.0-10b981)](docs/web-preview.md)

[按载具选包](#-一按载具与风格选包) · [3D 预览与本地工作台](#-二在线-3d-预览与本地涂装工作台) · [四步快速上手](#-三四步快速上手) · [候选与研发](#-四发布候选与研发分支) · [文档与源码结构](#-五文档中心与仓库目录)

</div>

---

> [!IMPORTANT]
> **新手先看这句：** 每个独立发行的 `.skill.zip` **自包含运行所需全部说明、脚本与内置素材**，直接下载即可用，不需要手动克隆整个仓库。仓库中的 `src/study`、`src/build` 与 `Pre-release` 标签属于研发或待验证候选，与下方推荐正式版严格区分。

---

## 一、按载具与风格选包

### ✈ 固定翼喷气机（Aircraft）

| Skill 包 | 版本与状态 | 适用场景与特点 | 立即获取与文档 |
| --- | --- | --- | --- |
| **Akamywek 风格飞机涂装**<br>`war-thunder-style-akamywek` | **v1.21**（当前推荐正式版） | 炭灰 `#333334` + 指定签名色 + 无缝白 `V` + 翼尾三角马赛克；收录 J-16「青色无人物」、J-10C、F-16C 与 F-15C MSIP II（「青锋」无人物 /「莱万汀」双翼人物）完整案例，支持原生 UV、净距校验与 DDS 1:1 复核。（`1.30` / `1.3.1` / `1.3.1-rc2` 已于 2026-11-19 封存退役并回退至 `1.21` 稳定基线。） | [下载 1.21](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/war-thunder-style-akamywek/v1.21/war-thunder-style-akamywek-v1.21.skill.zip) · [功能](docs/skills/akamywek.md) · [日志](docs/changelog/war-thunder-style-akamywek.md) |

### 🛡 地面载具 / 坦克（Ground）

| Skill 包 | 版本与状态 | 适用场景与特点 | 立即获取与文档 |
| --- | --- | --- | --- |
| **炭灰工业涂装**<br>`wt-style-charcoal-industrial` | **v0.2.0**（当前主力正式版） | 以勒克莱尔 AZUR v29 为实测范本：深浅大斜切碎片、侧裙亮格蜂窝、炮塔满铺数码与渐散簇、身份铭牌、黑底琥珀警示；Skill 与 32 项高分防滑/贴纸素材独立打包。 | [下载合集 / 分包](docs/skills/charcoal-industrial.md#-下载) · [功能](docs/skills/charcoal-industrial.md) · [日志](docs/changelog/wt-style-charcoal-industrial.md) |

---

## 二、在线 3D 预览与本地涂装工作台

无需启动游戏或手动配置 Blender，即可在浏览器中以 512–4K 清晰度、PBR 反射/金属度与接缝凹凸检查涂装效果。

| 工具入口 | 定位与适用场景 | 核心能力 | 使用方式 |
| --- | --- | --- | --- |
| **[涂装作品集 · 在线 3D 预览](https://icyryna.github.io/war-thunder-liveries/)** | **纯展示与看效果** | 多视角切换、512–4K 切换、反射强度/接缝凹凸开关、保存高清预览图 | 浏览器直接打开（无编辑器功能） |
| **[本地涂装工作台 v1.0.0](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-paint-workbench/v1.0.0/wt-paint-workbench-windows-x64.zip)** | **日常制作、导入与人工精调**（Windows x64 便携包） | 自动识别战雷目录导出 `.grp` 模型、直接打开涂装 ZIP/文件夹、加贴花/文字/框选改色、保存 AI 可接手的分层工程 | 解压后双击 **`启动工作台.cmd`**，首次联网自动准备依赖（详情见 [工具文档](docs/web-preview.md)） |

> [!TIP]
> 让 AI 帮你做涂装前，请顺手把**本地工作台解压路径**告诉它——AI 可直接提取游戏原模型并生成可由你在网页端微调的分层工程（见 [AI 协同说明](toolkits/web-preview/给AI的说明.md)）。

---

## 三、四步快速上手

1. **选包下载**：前往上方推荐表或 [完整下载中心](releases/README.md)，按车型与画风下载 `.skill.zip` 安装包。
2. **解压装入助手**：将 ZIP **完整解压**（保留外层 `<skill-id>/` 目录与其中的 `SKILL.md`、`scripts/`、`references/`、`assets/`），放进你所用 AI 助手的 Skills 目录（具体路径与依赖见 [安装指南](docs/installation.md)）。
3. **准备输入与工作台**：确定目标机型，告知 AI 你的需求（风格分支、配色、是否带人物/联名贴花）以及本地工作台/原皮所在路径。
4. **预览与实装验证**：使用模型预览与原尺寸局部检查构图、字向和材质通道；导出游览/游戏包后解压至游戏 `UserSkins` 目录，进游戏确认最终表现。

详细分流指引见 [**快速上手指南**](docs/quick-start.md) · 不懂术语先查 [**中文术语表**](docs/terminology.md)。

---

## 四、发布候选与研发分支

以下内容尚未正式取代上方主力版本，或专为研究与重构测试设计——**状态、未验证范围与正式版严格分开：**

| 类别 | 模块 / 版本 | 当前状态 | 说明与边界 |
| --- | --- | --- | --- |
| **地面候选** | `wt-style-endfield` **`0.2.0`** | **Pre-release** | 以 A7V / A7HU / EMBT 重建的终末地黑白黄工业涂装（内置 23 透明 PNG + 22 SVG）；**同 brief 独立复现待回传，游戏实测 `not_run`**。[查看候选详情](docs/skills/wt-style-endfield-0.2.0.md) |
| **研发源码** | [`wt-skin-study`](src/study/wt-skin-study/) · [`wt-skin-build`](src/build/wt-skin-build/) | **Development** | 内部「研究 → 实验 → 规则 → 评测」工程基座与中性流程探索，无正式版本号。[查看研发流程](docs/workflow/README.md) |

---

## 五、文档中心与仓库目录

<details>
<summary><b>📂 点击展开：仓库源码分类与目录结构（开发者 / 维护者视图）</b></summary>

```text
war-thunder-skin-skills/
├── catalog.json                # 唯一构建清单：声明包 ID、源码、公共脚本注入与基线校验
├── docs/                       # 中文文档中心（入门 / 功能介绍 / 更新记录 / 维护 / 历史）
├── releases/                   # 正式发行导航、index.json 与逐文件 content-lock.json
├── src/
│   ├── styles/aircraft/        # 飞机风格 Skill 源码（Akamywek 1.21 正式基线、旧版 0.2.0）
│   ├── styles/ground/          # 地面风格 Skill 源码（炭灰工业 0.2.0、终末地 0.2.0/1.4）
│   ├── legacy/                 # 已封存退役源码（war-thunder-user-skins 3.14）
│   ├── study/ & build/         # 研发与中性工程流源码候选
├── toolkits/
│   ├── aircraft/scripts/       # 飞机公共脚本单一真源（由 repository.py 装配入包）
│   ├── ground/                 # 地面领域脚本与技术回归
│   └── web-preview/            # 本地涂装工作台 & 在线 3D 预览导出源码
├── assets/                     # 共享精选素材库（终末地 / 炭灰 / 参考图）
├── profiles/ & evals/          # 载具配置契约（schema/合成示例）与评测检查器
└── tools/ & tests/             # repository.py 构建器、CI 校验脚本与仓库自测
```

常用运维命令见 [仓库维护与构建指南](docs/maintaining.md) 与 [仓库装配结构](docs/workflow/repository-layout.md)。

</details>

<details>
<summary><b>🗄 点击展开：已停更 / 历史封存版本（仅供追溯与回退）</b></summary>

这些版本已移出主力推荐列表，原 Git 标签、附件与校验值保持原样以便追溯：

| 版本线 | 停更 / 封存说明 | 历史入口 |
| --- | --- | --- |
| `war-thunder-style-akamywek` **1.30 / 1.3.1 / 1.3.1-rc2** | 2026-11-19 封存退役；后续衍生分支停止维护并回退至 `v1.21` 稳定基线 | [v1.3.1 (已封存)](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.3.1) · [v1.30 (已封存)](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.30) · [更新记录](docs/changelog/war-thunder-style-akamywek.md) |
| `war-thunder-user-skins` **3.14** | 2026-11-18 封存退役；通用固定翼旧线，新飞机涂装统一使用 `war-thunder-style-akamywek`（`1.21`） | [历史说明](docs/skills/jet-liveries.md) · [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.14) |
| `wt-style-akamywek` **0.2.0** | 早期「四步映射」实验分支；现统一使用 `war-thunder-style-akamywek` 主线（`1.21`） | [历史说明](docs/skills/wt-style-akamywek.md) · [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-akamywek/v0.2.0) |
| `wt-style-endfield` **0.1.0 / 0.1.1** | 2026-10-25 永久封存；由 0.2.0 重构取代 | [封存范围](docs/history/endfield-archived.md) · [0.1.1 全览](docs/skills/wt-style-endfield-0.1.1.md) |
| `war-thunder-tank-style-endfield` **1.0–1.4** | 初代终末地坦克线（62 MB 内嵌素材）；已停止维护 | [1.4 历史说明](docs/history/war-thunder-tank-style-endfield-v1.4.md) · [历史索引](docs/history/README.md) |
| `wt-style-spectre42` **0.1.1** | 已更名为 `wt-style-charcoal-industrial`（现已迭代至 `0.2.0`） | [更名说明](docs/skills/spectre42.md) · [更新记录](docs/changelog/wt-style-spectre42.md) |

</details>

### 常用文档直达

[文档总览](docs/README.md) · [下载中心](releases/README.md) · [全部更新记录](docs/changelog/README.md) · [素材来源](docs/credits.md) · [许可说明 (MIT & 第三方界限)](docs/licensing.md)
