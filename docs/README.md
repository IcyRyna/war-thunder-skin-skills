# 文档中心

> 按**「新手入门 → 主力 Skill 文档 → 候选测试 → 版本与合规 → 源码研发与归档」**清晰分类。找不到概念先看术语表；想直接下载请去 [下载中心](../releases/README.md)。

[← 返回首页](../README.md) · [下载中心](../releases/README.md) · [更新记录](changelog/README.md)

---

## 一、新手入门（先读这 3 篇）

| 文档 | 内容与用途 |
| --- | --- |
| [**快速开始**](quick-start.md) | 1 分钟按「飞机 / 坦克 / 工作台」选对 Skill 并走通制作流程 |
| [**安装与环境依赖**](installation.md) | AI 助手的 Skills 安装路径（Codex / Claude / Antigravity）、Python 依赖与字体验证 |
| [**中文术语表**](terminology.md) | UV、Atlas、Texel、DDS、Packed N/AO、CMPS、SHA-256 等常见术语大白话解释 |

---

## 二、主力 Skill 与本地工作台

### ✈ 飞机涂装（Aircraft）

| 文档 | 当前版本 | 涵盖范围 |
| --- | --- | --- |
| [**Akamywek 风格飞机涂装**](skills/akamywek.md) | **1.3.1**（正式）<br>1.3.1 RC2（补丁） | 炭灰 + 签名色 + 无缝白 `V` + 三段式深枪灰喷口 + 缎面金属 PBR；F-15EX / J-16 / J-10C / F-16C 案例与终末地联名贴花库 |
| [**通用二次元喷气机工作流**](skills/jet-liveries.md) | **3.14** | 不限风格的固定翼痛涂工作流：纯色人物抠图、原生 UV 绘制、模型对比与游戏封包 |

### 🛡 地面载具与工具（Ground & Workbench）

| 文档 | 当前版本 | 涵盖范围 |
| --- | --- | --- |
| [**炭灰工业涂装（AZUR 基准）**](skills/charcoal-industrial.md) | **0.2.0** | 勒克莱尔 AZUR v29 实测审美体系、三层装饰预算、32 项工业贴花与防滑素材拆分机制 |
| [**在线预览与本地涂装工作台**](web-preview.md) | **1.0.0** | [在线 3D 作品集](https://icyryna.github.io/war-thunder-liveries/) 说明 + Windows 便携版导出游戏模型、交互加层与 AI 工程接口 |

---

## 三、补丁与发布候选文档（Pre-release）

| 文档 | 状态 | 说明 |
| --- | --- | --- |
| [**终末地工业涂装 0.2.0**](skills/wt-style-endfield-0.2.0.md) | Pre-release | 以 A7V / A7HU / EMBT 重构的黑白黄坦克涂装，内置透明 PNG/SVG；独立复现待回传、游戏实测 `not_run` |

---

## 四、更新记录、来源与版权边界

| 文档 | 内容 |
| --- | --- |
| [**全部更新记录**](changelog/README.md) | 各 Skill 历史版本的完整功能变更与修复明细 |
| [**公开浏览与包分发说明**](distribution.md) | 游戏安装 ZIP、可编辑工程与 `.skill.zip` 的边界区分 |
| [**素材与参考来源**](credits.md) | Akamywek、终末地、AZUR、官方原画与社区资源引用索引 |
| [**开源许可与授权边界**](licensing.md) | 代码/文档的 MIT 协议及外部游戏资源/立绘/商标的使用范围 |

---

## 五、研发规范与历史封存（维护者 / 回退专用）

| 类别 | 文档 | 说明 |
| --- | --- | --- |
| **研发运维** | [**七阶段研发流程**](workflow/README.md) | 研究 → 实验 → 规则 → 候选 → 评测 → 审查 → 发布 |
| **研发运维** | [**仓库目录与装配结构**](workflow/repository-layout.md) | `src/`、`toolkits/`、`catalog.json`、`releases/` 的维护与装配契约 |
| **研发运维** | [**证据记录与评测细则**](workflow/evidence-and-evaluation.md) | 实验字段、对照边界与技术/审美分离原则 |
| **研发运维** | [**本地构建与发版维护**](maintaining.md) | `tools/repository.py` 检查/构建命令与发版校验清单 |
| **历史封存** | [**已停更 / 历史版本归档**](history/README.md) | 封存的终末地 0.1.x / 1.4、`wt-style-akamywek 0.2.0`、`S42` 与旧版四视图（[A7V 五车型图解](skills/endfield-layout-guide.md) · [0.1.1 全览](skills/wt-style-endfield-0.1.1.md) · [终末地封存范围](history/endfield-archived.md)） |
