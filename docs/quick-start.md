# 快速上手指南

> 1 分钟选对工具与 Skill，按标准化顺序走完一次《战争雷霆》用户涂装制作。

[← 返回首页](../README.md) · [安装与环境依赖](installation.md) · [下载中心](../releases/README.md) · [中文术语表](terminology.md)

---

## 第一步：选对你要用的工具和 Skill

| 你的目标 | 推荐选择的包 | 对应说明 |
| --- | --- | --- |
| **做 Akamywek 风格喷气机涂装**<br><sub>含原教旨无人物、终末地工业联名变体、双翼人物</sub> | **`war-thunder-style-akamywek`**<br>正式版 **`1.3.1`** · 补丁测试 [`1.3.1 RC2`](../releases/README.md#二补丁与发布候选pre-release) | [Akamywek 功能介绍](skills/akamywek.md) |
| **做通用二次元固定翼喷气机痛涂**<br><sub>不限定 Akamywek 画风</sub> | **`war-thunder-user-skins`**<br>正式版 **`3.14`** | [喷气机工作流](skills/jet-liveries.md) |
| **做现代坦克 / 地面载具涂装**<br><sub>深炭灰斜切碎片、蜂窝格与高密度工业贴花</sub> | **`wt-style-charcoal-industrial`**<br>正式版 **`0.2.0`**（含独立 32 项素材包） | [炭灰工业功能介绍](skills/charcoal-industrial.md) |
| **做终末地黑白黄地面工业涂装（试行）**<br><sub>Pre-release 重构版本</sub> | **`wt-style-endfield`**<br>发布候选 **`0.2.0`**（独立复现待回传） | [终末地 0.2.0 候选说明](skills/wt-style-endfield-0.2.0.md) |
| **直接看车模 / 加贴花 / 局部改色 / AI 辅助预览** | **`wt-paint-workbench`**<br>Windows 绿色工作台 **`1.0.0`** | [在线预览与本地工作台](web-preview.md) |

---

## 第二步：装进你的 AI 助手

1. 从 [下载中心](../releases/README.md) 下载对应 `.skill.zip`。
2. 完整解压，保证文件夹里最外层有 `SKILL.md` 与随附的 `scripts/`、`references/`、`assets/`（炭灰工业还需确保素材目录并排存放或设置环境变量）。
3. 放到助手对应 Skills 目录并装好基础 Python 依赖，详见 [安装指南](installation.md)。

---

## 第三步：制作时给 AI 的必备输入

| 输入项 | 说明 |
| --- | --- |
| **目标机型 / 车型与游戏模型** | 原包 BLK、颜色（`c`）/ 材质（`n`）贴图，或**直接把本地工作台路径交给 AI** 让它自动从战雷目录提取 |
| **参考方向与角色/贴花素材** | 指定参考图、配色与角色立绘；做终端联动工业风可启用内置 `endfield` 贴花（需明确区分于纯原教旨 Akamywek） |
| **编辑与校验环境** | 本机可用 Composa / Photoshop，以及支持 PBR 预览的本地工作台（`http://127.0.0.1`） |

---

## 第四步：按标准流程出图与核对

1. **绑定真实 UV 与材质**：识别可涂外皮、机械遮挡区、镜像/共享纹素，不猜测岛号。
2. **先定大形与配色，再加字符与人物**：先跑低清或全尺寸布局预览与 `design_lint.py` / `surface_map.py` 净距排查，再放字标、徽记或人物。
3. **跨部件与同尺度复查**：外挂载荷（如 CFT）必须在整机拼装场景查遮挡；本地 3D 预览配合最终 DDS 1:1 裁图核对眼部/字高清晰度。
4. **独立游戏封包与实机核验**：导出游戏 `UserSkins` 所需贴图与 BLK，在游戏内实机查看最终高光、接缝与色调。

> [!NOTE]
> 离线预览、脚本检查通过与用户在游戏实机审美认可**分开记录**。最终效果始终以《战争雷霆》游戏内实机渲染与作者确认为准。
