# War Thunder 涂装 Skills

用于制作 War Thunder 用户涂装的三个独立 Skill，支持 Codex 和 Claude Code。飞机部分面向二次元固定翼喷气机痛涂；坦克部分目前提供终末地工业风。

## 飞机涂装

### 喷气机涂装工作流

用于新作和已有涂装的修改，包含立绘裁切、机身与机翼布局、原生 UV 作画、线条配色、材质和模型检查工具。可输出分层设计源、DDS / TGA 贴图和 BLK 配置。

[下载 3.14](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.14) · [详细说明](docs/skills/jet-liveries.md) · [更新记录](docs/changelog/war-thunder-user-skins.md)

### Akamywek 风格飞机涂装

按 Akamywek 的公开涂装整理，主要特征是深炭底、单一签名色、锐利几何和三角马赛克。先完成色块与几何布局，再放人物。包内自带制作工具和参考资料，可单独安装。

[下载 1.14](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-style-akamywek/v1.14) · [详细说明](docs/skills/akamywek.md) · [更新记录](docs/changelog/war-thunder-style-akamywek.md)

## 坦克涂装

### 终末地风格坦克涂装

用于现代坦克的终末地工业风涂装，包含黑白黄分区、工业标志、路线节点和设备标签的布局方法，以及车型之间的 UV 与材质适配。

安装包约 61 MB，带有 4 张原尺寸 UV、22 组元素裁片、标志 SVG / PNG 和提取工程。素材随包提供。

[下载 1.0](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-tank-style-endfield/v1.0) · [详细说明](docs/skills/endfield-tanks.md) · [更新记录](docs/changelog/war-thunder-tank-style-endfield.md)

## 安装

在对应 Release 的 **Assets** 中下载 `.skill.zip`，解压后把整个 Skill 文件夹放入 Codex 或 Claude Code 的 Skills 目录。目录位置和工具依赖见[安装说明](docs/installation.md)。

## 目录

- [`skills/aircraft/`](skills/aircraft/)：飞机涂装 Skill。
- [`skills/ground/`](skills/ground/)：地面载具涂装 Skill。
- [`docs/`](docs/)：功能说明、安装、版本记录和[素材来源](docs/credits.md)。
