# 安装与环境依赖

[← 返回首页](../README.md) · [快速上手](quick-start.md) · [下载中心](../releases/README.md) · [本地涂装工作台](web-preview.md)

---

## 一、获取独立安装包

> [!IMPORTANT]
> 请从 [Releases](https://github.com/IcyRyna/war-thunder-skin-skills/releases) 或 [下载中心](../releases/README.md) 下载名称以 **`.skill.zip`** 结尾的安装包。GitHub 页面自带的 `Source code (zip)` 是仓库开发目录快照，**不能直接当作完整 Skill 导入**（缺少构建器装配的公共脚本或精选素材布局）。

---

## 二、解压并放入 AI 助手目录

下载 `.skill.zip` 后完整解压，确认保留 `<skill-id>/` 目录及内部 `SKILL.md`、`scripts/`、`references/`、`assets/`（若含）。目录名应与 Skill ID 一致，例如：

- ✈ `war-thunder-style-akamywek/`（1.3.1 或 1.3.1 RC2）
- 🛡 `wt-style-charcoal-industrial/`（0.2.0）

| AI 助手 | 默认全局 Skills 目录 | 说明 |
| --- | --- | --- |
| **Codex** | `~/.agents/skills/` | 完整支持目录型 Skill 与脚本调用 |
| **Claude Code** | `~/.claude/skills/` | 可放在全局目录或项目 `.claude/skills/` |
| **Antigravity / Gemini CLI** | 对应全局或工作区 `skills/` | 解压为同名子目录后在对话引用 `<skill-id>` |

> [!TIP]
> **`wt-style-charcoal-industrial` 0.2.0 素材定位**：若单独下载了 `wt-style-charcoal-industrial-v0.2.0.skill.zip` 与 `wt-charcoal-industrial-assets-v0.2.0.zip`，建议直接将 `wt-style-charcoal-industrial` 与 `wt-charcoal-industrial-assets` **放在同一上级目录下并排解压**（下载合集包 `bundle` 时已自动并排）；若放别处，可设置环境变量 `WT_CHARCOAL_ASSETS`。安装完可在目录内运行 `python -B scripts/verify_release.py` 自检。

---

## 三、基础运行环境

### 1. 纯免配置用户（本地 3D 查看与改色）

如果主要通过图形界面看模、导入现成涂装加层调色，直接下载 **[本地涂装工作台 `v1.0.0`](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-paint-workbench/v1.0.0/wt-paint-workbench-windows-x64.zip)** 并双击 **`启动工作台.cmd`**，包内已集成 Python 运行时与依赖，无需本机额外安装环境。

### 2. AI 制作主力脚本（Python 3.10+）

各个飞机/地面 Skill 的底层绘图与净距校验脚本基于 **Python 3.10+**，标准核心依赖包括：

```bash
pip install numpy pillow scipy numba
```

| 依赖类别 | 用途 | 可选 / 注意事项 |
| --- | --- | --- |
| `numpy` / `pillow` / `scipy` / `numba` | 原生 UV 矢量渲染、抗锯齿缩放、马赛克与 PBR 贴图生成 | **必需**；推荐配合 `python -B` 与系统 TEMP `NUMBA_CACHE_DIR` 运行 |
| **内置字体（`assets/fonts/`）** | Akamywek 默认标配 `Orbitron-VF.ttf` 与 `Michroma-Regular.ttf` | **1.3.1+ 已随包内置**，自动优先加载，不再强制依赖本机系统字体或手配 `WT_SKIN_FONT` |
| **Blender / Composa / Photoshop** | 真实 3D 模型场景导出、拼装跨部件检查与分层图编辑 | 按具体任务启用；工作台亦可承担便携 3D 与局部编辑检查 |
| `requests` / `matplotlib` / `moderngl` | 远端拉取素材、多边形快速点检或离屏渲染 | **1.3.1 RC2 已为 `fetch_asset.py` 与 `replica_check.py` 补足标准库/NumPy 离线回退**；`moderngl` 仅离屏预览需要 |

---

## 四、安装后快速核对清单

- [ ] `SKILL.md` 位于 `<skills目录>/<skill-id>/SKILL.md` 根目录，没有多嵌套一层同名文件夹。
- [ ] `python -B -c "import numpy, PIL, scipy, numba; print('OK')"` 返回 `OK`。
- [ ] 如已下载本地涂装工作台 `wt-paint-workbench`，在发起涂装任务时把**完整解压路径**与目标战雷目录告知 AI 助手。
