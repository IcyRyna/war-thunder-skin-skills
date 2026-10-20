# 已发布版本与下载

已有三个 Skill 继续沿用各自的正式版本线。进入对应 Release，在 **Assets** 中下载 `.skill.zip`；包内带有该版本运行所需的脚本与参考资料，可单独安装。

| Skill | 已发布版本 | 使用说明 | 完整更新记录 |
| --- | --- | --- | --- |
| `war-thunder-user-skins` | **[3.14](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.14)** | [喷气机涂装](../docs/skills/jet-liveries.md) | [历史](../docs/changelog/war-thunder-user-skins.md) |
| `war-thunder-style-akamywek` | **[1.14](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.14)** | [Akamywek 风格](../docs/skills/akamywek.md) | [历史](../docs/changelog/war-thunder-style-akamywek.md) |
| `war-thunder-tank-style-endfield` | **[1.4](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-tank-style-endfield/v1.4)** | [ENDFIELD 坦克](../docs/skills/endfield-tanks.md) | [历史](../docs/changelog/war-thunder-tank-style-endfield.md) |

**[全部历史 Releases](https://github.com/IcyRyna/war-thunder-skin-skills/releases) · [机器可读发布索引](index.json) · [安装步骤](../docs/installation.md)**

## 选择正确的文件

- **正式使用**：下载上述 Release 的 `.skill.zip` 附件。解压后的顶层目录就是 Skill ID，保留其中的说明、脚本、参考与素材。
- **研究源码**：查看仓库的 `src/`、`toolkits/`、`profiles/` 和 `evals/`。GitHub 自动生成的 Source code ZIP 是这一源码树的快照。
- **候选审查**：按[维护指南](../docs/maintaining.md)构建 `dist/<skill-id>-candidate.zip`，检查和审查装配后的完整内容。

新的 `wt-skin-study` 与 `wt-skin-build` 尚无正式 Release。候选构建不沿用或冒充旧安装包的正式版本身份；源码重新布局也不改变旧附件的内容。

## 版本保留

旧版本的标签、Release 与附件保留在原地址。每条 Skill 独立编号；飞机通用工作流、飞机风格与地面风格的版本号互不比较。需要历史安装包时，按发布索引或全部 Releases 中的对应标签定位。

[返回仓库首页](../README.md) · [版本记录导航](../docs/changelog/README.md)
