# 安装指南

## 选择正式版或候选

| 目的 | 获取方式 |
| --- | --- |
| 使用已有正式工作流 | 从[当前推荐下载](../releases/README.md)进入对应 Release，下载 `.skill.zip` |
| 检查新研究、工程模块或源码改动 | 按[维护指南](maintaining.md)构建 `dist/<skill-id>-candidate.zip`，先检查和审查完整包 |

仓库中的 `src/` 保存创作源码，公共脚本与部分大型素材由构建器装配。直接复制某个源码子目录可能缺少运行依赖。GitHub 自动提供的 Source code ZIP 用于获取源码；正式安装使用 Release 的独立附件。

`wt-skin-study` 与 `wt-skin-build` 目前是开发候选，没有正式发布版。需要试用候选时，使用与日常工作流隔离的测试位置，并避免同名 Skill 同时被发现；候选审查完成前不要替换正式安装。

## 下载正式安装包

从[当前推荐下载](../releases/README.md)选择工作流，进入对应 Release，在 **Assets** 中下载以 `.skill.zip` 结尾的独立安装包。解压后保留整个 Skill 文件夹，`SKILL.md`、`references/`、`scripts/` 和已有的 `assets/` 保持在同一层级。

```text
war-thunder-user-skins/
├── SKILL.md
├── agents/
├── references/
├── scripts/
└── assets/
```

Release 的独立安装包包含该版本的工具与素材，安装后不需要克隆本仓库或另装其他 Skill。

## 放入 Skills 目录

| 平台 | 个人使用 | 项目内使用 |
| --- | --- | --- |
| Codex | `~/.agents/skills/<skill-id>/` | `<项目>/.agents/skills/<skill-id>/` |
| Claude Code | `~/.claude/skills/<skill-id>/` | `<项目>/.claude/skills/<skill-id>/` |

Windows 下 `~` 表示用户主目录，可在资源管理器中使用 `%USERPROFILE%`。目录名保留安装包中的 Skill ID。若使用自定义 Skills 位置，将整个文件夹放入实际启用的目录。

Codex 的本地发现路径依据 [OpenAI 官方 Skills 文档](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)；Claude Code 路径依据 [Claude 官方 Skills 文档](https://code.claude.com/docs/en/skills#choose-where-skills-load)。添加后可在助手的技能选择器中查找，未显示时重新打开会话或重启对应应用。

## 调用技能

在 Codex 中明确指定 Skill，例如：

```text
使用 $war-thunder-user-skins，为指定喷气机制作角色主题涂装。
```

Claude Code 可用 `/war-thunder-user-skins` 调用，或在对话中说明需要使用的工作流。当前推荐正式包的 Skill ID 为：

- `war-thunder-user-skins`
- `war-thunder-style-akamywek`
历史兼容包另见[历史版本](history/README.md)；旧包仍按其原 Skill ID 识别。

提供目标载具、原始模板或 DDS、参考图片与期望输出，会帮助助手选择对应的制作分支。

## 运行环境

阅读工作流不需要先安装图形处理依赖。执行工具时，按具体脚本准备环境：

| 工具范围 | 环境 |
| --- | --- |
| Python 工具 | Python 3.10 或更高版本 |
| 纹理读取、裁切、比较与绘制 | Pillow、NumPy |
| 飞机几何、UV 运算和离线渲染 | Numba，并按脚本说明准备模型资源 |
| 坦克离线预览 | ModernGL、可用的 OpenGL 3.3 上下文 |
| 坦克逐纹素表面转移（按需） | OpenCV、Numba、ModernGL、可用的 OpenGL 4.3 上下文 |
| Composa 分层编辑器 | 已安装 Composa，并在编辑器中启用 `Help > Allow AI Control` |

纹理、模型和字体等项目资源由具体制作任务提供。各工具的实际参数以安装包内脚本的 `--help` 为准；脚本输出保存在制作目录。

## 更新与检查

下载同一 Skill 的新版本，保留制作项目后替换其安装目录。打开新的会话并确认技能名称可见，再开始制作。校验文件随相应 Release 提供，可用于核对下载内容。
