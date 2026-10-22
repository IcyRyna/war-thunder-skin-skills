# 仓库与装配结构

仓库保存创作源码、公共工具、配置契约和评测代码。根目录 [`catalog.json`](../../catalog.json) 记录可构建包及其装配关系；[`tools/repository.py`](../../tools/repository.py) 是统一的列表、检查与构建入口。

## 目录职责

| 路径 | 保存内容 | 约束 |
| --- | --- | --- |
| [`src/study/wt-skin-study/`](../../src/study/wt-skin-study/) | 研究、实验、规则提炼与独立评测候选 | 无正式版本号；不嵌入具体制作任务 |
| [`src/build/wt-skin-build/`](../../src/build/wt-skin-build/) | 中性工程流程候选 | 通过清单接入领域工具，不宣称已统一所有载具 |
| [`src/styles/aircraft/`](../../src/styles/aircraft/) | 飞机风格说明与参考 | 公共脚本由构建器装入 |
| [`src/styles/ground/`](../../src/styles/ground/) | 地面风格、领域专用工具和素材清单 | 大型素材从固定 Release 补齐 |
| [`src/legacy/war-thunder-user-skins/`](../../src/legacy/war-thunder-user-skins/) | 3.14 兼容工作流与参考 | 保留旧 Skill ID 与包内运行路径 |
| [`toolkits/aircraft/scripts/`](../../toolkits/aircraft/scripts/) | 飞机公共脚本的唯一维护位置 | 不在各创作源码目录中手工维护副本 |
| [`profiles/`](../../profiles/) | 通用 schema、合成示例与地面家族诊断参考 | 家族四视不代替生产 UV 或游戏验证 |
| [`toolkits/ground/`](../../toolkits/ground/) | 十个公共脚本、固定依赖与技术回归 | 装入 0.1.1 后可独立运行 |
| [`assets/endfield/`](../../assets/endfield/) | 运行包精选透明素材与参考 | 全套旧大素材只作为可选 Release 附件 |
| [`evals/`](../../evals/) | 评测契约、检查器和回归测试 | 结构检查不代替人工视觉及游戏验证 |
| [`releases/`](../../releases/) | 已有正式发布的导航和索引 | 保留原标签、附件和各自版本线 |
| [`docs/`](../README.md) | 流程、安装、维护与发布版功能说明 | 更新记录按各 Skill 独立维护 |
| [`.github/workflows/`](../../.github/workflows/) | 仓库自动检查 | 自动检查不产生审美认可或发布授权 |

`dist/` 是本地构建输出，`.cache/` 可用于下载的原版素材包；二者均不属于源码。制作任务的原图、模型、完整编辑工程和交付另行保存，不复制到仓库的公共目录。

## 构建与发布索引

[`catalog.json`](../../catalog.json) 是构建输入的唯一索引，记录包定义、源码位置、状态和装配关系。[`releases/index.json`](../../releases/index.json) 保存已有正式版本与下载入口。文档中的模块和下载表应与这两个入口一致；不再维护一份独立的文档目录 JSON。

开发候选与正式发布分别标记。`development` 表示开发候选，`released_baseline` 表示已有发布版内容的源码基线；这两个字段都不表达作品的美术评价。

## 从创作源码到独立包

```text
catalog.json
  ├── src/<职责>/<skill-id>/        说明与专属文件
  ├── toolkits/aircraft/scripts/    清单选用的公共脚本
  └── 固定 Release 素材包          按需补齐并校验
                 ↓
       tools/repository.py build <skill-id>
                 ↓
       dist/<skill-id>-candidate.zip
                 └── <skill-id>/
                     ├── SKILL.md
                     ├── scripts/       按包内容装配
                     ├── references/    按包内容装配
                     └── assets/        按包内容装配
```

包内运行路径保留原有契约；需要的脚本与参考实际进入单个包。运行时不依赖仓库里的相邻 Skill 目录。研究模块等说明包只包含自身需要的文件，工程候选另带配置契约。

飞机公共脚本发生变更时，检查所有引用它的包，并比较重新装配后的内容。地面专用工具保持独立；统一接口或迁移实现需要单独的测试与审查。

## 历史版本与兼容

原 `skills/aircraft/` 与 `skills/ground/` 的创作入口已按职责迁入 `src/`；源码维护路径改变，已有 Release 的下载地址与安装目录名继续有效。仓库的 Source code ZIP 是源码快照，正式安装仍使用 `.skill.zip` 附件。

每条 Skill 独立编号，标签继续使用 `<skill-id>/v<版本>`。候选 ZIP 的 `candidate` 名称表示构建用途，不授予新正式版本。旧标签、Release 附件和逐版更新记录保留。

新正式发布需要固定输入、输出文件清单、摘要、检查结果，以及明确的采用和发布范围。发布后核对远端标签与下载内容；提交源码成功不替代附件核验。

[维护与构建命令](../maintaining.md) · [流程](README.md) · [下载](../../releases/README.md)
