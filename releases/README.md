# 下载中心 · Releases

> 按**「当前推荐正式版 → 补丁与发布候选 → 工具包体说明 → 历史版本」**分类整理。需要回退旧版或核对逐文件 SHA-256 时，请查阅 [历史版本索引](../docs/history/README.md)、[`index.json`](index.json) 与 [`content-lock.json`](content-lock.json)。

[← 返回首页](../README.md) · [快速上手](../docs/quick-start.md) · [安装与环境依赖](../docs/installation.md) · [更新记录总览](../docs/changelog/README.md)

---

## 一、当前推荐正式版（Stable Official）

| 分类 | 工具 / Skill | 最新正式版 | 直接下载附件 | 发布页与说明 |
| --- | --- | --- | --- | --- |
| ✈ **飞机风格** | **Akamywek 风格飞机涂装**<br>`war-thunder-style-akamywek` | **1.21**<br>`2026-11-15` | [war-thunder-style-akamywek-v1.21.skill.zip](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/war-thunder-style-akamywek/v1.21/war-thunder-style-akamywek-v1.21.skill.zip)<br><sub>5.65 MB · 147 文件 · 稳定无人物及双翼人物基线</sub> | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.21) · [介绍](../docs/skills/akamywek.md) · [日志](../docs/changelog/war-thunder-style-akamywek.md) |
| 🛡 **地面风格** | **炭灰工业涂装（AZUR 基准）**<br>`wt-style-charcoal-industrial` | **0.2.0**<br>`2026-10-30` | · Skill 本体：[v0.2.0.skill.zip](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-style-charcoal-industrial/v0.2.0/wt-style-charcoal-industrial-v0.2.0.skill.zip)（350 KB）<br>· 独立素材包（32 项）：[assets-v0.2.0.zip](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-style-charcoal-industrial/v0.2.0/wt-charcoal-industrial-assets-v0.2.0.zip)（72.65 MB）<br>· **一键合集包**：[bundle-v0.2.0.zip](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-style-charcoal-industrial/v0.2.0/wt-charcoal-industrial-bundle-v0.2.0.zip)（73.00 MB） | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-charcoal-industrial/v0.2.0) · [介绍](../docs/skills/charcoal-industrial.md) · [日志](../docs/changelog/wt-style-charcoal-industrial.md) |
| 🛠 **配套工具** | **本地涂装工作台**<br>`wt-paint-workbench` | **1.0.0**<br>`2026-10-25` | [wt-paint-workbench-windows-x64.zip](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-paint-workbench/v1.0.0/wt-paint-workbench-windows-x64.zip)<br><sub>Windows x64 绿色便携包 · 免装 Python/Git/Blender</sub> | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-paint-workbench/v1.0.0) · [使用说明](../docs/web-preview.md) |

---

## 二、发布候选（Pre-release）

下列版本为待独立复现或进一步实机验证的重制候选，**均独立打标、不覆盖上方正式版本**，方便随时回退：

| 分类 | Skill ID | 版本与标签 | 状态与变更说明 | 下载与详情 |
| --- | --- | --- | --- | --- |
| 🛡 **地面候选** | `wt-style-endfield` | **0.2.0**<br>`wt-style-endfield/v0.2.0` | 按 A7V/A7HU/EMBT 重建的终末地黑白黄工业涂装（内置 23 透明 PNG + 22 SVG；独立复现待回传，游戏实测 `not_run`） | [Pre-release 下载页](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-endfield/v0.2.0) · [可选素材包](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-style-endfield/v0.2.0/wt-style-endfield-v0.2.0.assets.zip) · [介绍](../docs/skills/wt-style-endfield-0.2.0.md) |

---

## 三、附件命名与安装说明

- **`<skill-id>-v<版本>.skill.zip`**：标准独立安装包，完整解压至 AI 助手 Skills 目录即可调用（不要在解压时丢掉最外层 `<skill-id>/` 目录）。
- **`.assets.zip` / `-bundle-.zip`**：地面大体积涂装素材包或“Skill + 素材”合集；下载 `bundle` 时解压得到两个并列文件夹，工具会自动识别。
- **GitHub 自动生成的 `Source code (zip)`**：是仓库研发快照，**不是**可直接安装进助手的 `.skill.zip`。如需从源码装配，请使用 [`tools/repository.py`](../tools/repository.py)。

---

## 四、旧版归档与历史回退

<details>
<summary><b>🗄 点击展开：已迭代或已封存的历史 Release</b></summary>

| Skill | 历史版本 | 说明与归档状态 | 直达标签 |
| --- | --- | --- | --- |
| **Akamywek 1.3x 分支** | `1.30` / `1.3.1` / `1.3.1-rc2` | 2026-11-19 封存退役，已回退恢复 `v1.21` 稳定基线 | [v1.3.1-rc2 (已封存)](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.3.1-rc2) · [v1.3.1 (已封存)](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.3.1) · [v1.30 (已封存)](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.30) |
| **喷气机通用痛涂工作流** | `3.14` / `2.x` / `1.x` | 2026-11-18 封存退役，新飞机涂装请使用 `Akamywek 1.21` | [v3.14](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.14) · [说明](../docs/skills/jet-liveries.md) |
| **Akamywek 历史早期版** | `1.16` / `1.14` 等 | 已被 `1.21` 取代，保留历史追溯入口 | [v1.16](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.16) · [更新记录](../docs/changelog/war-thunder-style-akamywek.md) |
| **Akamywek 飞机布局** | `0.2.0` | 独立实验线，已归档只读 | [wt-style-akamywek/v0.2.0](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-akamywek/v0.2.0) |
| **炭灰工业涂装** | `0.1.6` / `0.1.5` / `S42 0.1.1` | 早期版本与更名前归档 | [v0.1.6](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-charcoal-industrial/v0.1.6) · [v0.1.5](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-charcoal-industrial/v0.1.5) · [S42 0.1.1](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-spectre42/v0.1.1) |
| **终末地坦克旧版** | `0.1.1` / `0.1.0` / `1.4` | 永久封存，仅用于旧工程追溯与资产校验 | [0.1.1](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-endfield/v0.1.1) · [1.4](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-tank-style-endfield/v1.4) · [封存索引](../docs/history/README.md) |

</details>
