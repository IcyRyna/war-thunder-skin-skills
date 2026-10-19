# 战雷二次元喷气机痛涂 Skill

这里存放全部痛涂 Skill。每个 Skill 是一条独立的版本线，各自编号、各自发布；以后新增别的涂装类型 Skill，就加一条新线。

| Skill | 类型 | 内容 | 当前版本 | 更新记录 |
| --- | --- | --- | --- | --- |
| `war-thunder-user-skins` | 通用制作流程 | 素材、原 UV、材质、工具、打包和验收；不带特定画风 | [3.12](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.12) | [changelog/war-thunder-user-skins.md](changelog/war-thunder-user-skins.md) |
| `war-thunder-style-akamywek` | Akamywek 风格 | 先照作者 F-2A 学基本布局（深炭底和签名色两大块、白色焦点、三角马赛克），再放立绘；自带通用脚本和制作参考，可单独安装 | [1.12](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.12) | [changelog/war-thunder-style-akamywek.md](changelog/war-thunder-style-akamywek.md) |

## 目录

- `skills/<skill>/`：每个 Skill 的当前源码，和最新发布包内容一致。
- `changelog/<skill>.md`：该版本线的全部版本、日期和改动。
- `history/`：研究修订的发布收据和发布脚本，只作记录。

## 版本与标签

- 每条线独立编号，主版本号表示阶段：通用 Skill 的 1.x 只有规则文档，2.x 加入公共脚本，3.x 是审美体系重写之后；风格 Skill 从 1.0 开始。
- 标签是 `<skill>/v<版本>`，例如 `war-thunder-user-skins/v3.9`；查看某条线的提交历史，打开对应 `skills/<skill>/` 目录的 History。
- 每个版本的安装包在 Releases 里，文件名 `<skill>-v<版本>.skill.zip`。通用 Skill 的 1.x 和 2.x 各合成一个归档 Release。

## 安装

下载对应 Release 的 `.skill.zip`，解压后把 `<skill>/` 文件夹放进 Codex 的 `~/.codex/skills/` 或 Claude 的 skills 目录。
