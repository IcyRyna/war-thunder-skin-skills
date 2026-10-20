# 仓库维护与候选构建

构建输入统一登记在根目录 [`catalog.json`](../catalog.json)。源码按研究、工程、风格和兼容职责维护；发布包由 [`tools/repository.py`](../tools/repository.py) 装配。完整目录约定见[仓库结构](workflow/repository-layout.md)。

## 列表与检查

仓库管理命令使用 Python 3.10 或更新版本，无需先安装图形处理依赖。在仓库根目录运行：

```bash
python -B tools/repository.py list
python -B tools/repository.py list --json
python -B tools/repository.py check
python -B tools/repository.py check wt-skin-study wt-skin-build --json
```

`list` 显示可构建 ID 与状态。`check` 检查选定包或全部包的源码和装配关系；外部素材未提供时，会报告素材缺口。需要确保完整资源齐备时使用 `--require-assets`。

检查范围以命令输出为准。仓库检查与工作流记录检查分别运行；前者不能证明后者的实验已经完成，也不能证明视觉效果或真实游戏表现。

## 构建候选

```bash
python -B tools/repository.py build wt-skin-study
python -B tools/repository.py build wt-skin-build
python -B tools/repository.py build war-thunder-user-skins
python -B tools/repository.py build war-thunder-style-akamywek
```

默认输出为 `dist/<skill-id>-candidate.zip`，ZIP 顶层是单个 `<skill-id>/` 目录。可以用 `--output-dir dist/<子目录>` 分类保存构建；输出位置必须位于仓库已忽略的 `dist/` 内。仅在确定要替换该位置已有候选时使用 `--force`。

构建器按清单装入专属说明、公共脚本与必要参考，保留包内运行路径。审查与测试针对装配后的完整包进行，不能直接复制 `src/` 中的一段目录作为安装包。

候选 ZIP 用于检查和审查。构建操作不安装 Skill，不创建正式版本，不上传 Release。

## 补齐 ENDFIELD 的发布素材

地面风格的大型素材通过原 1.4 安装包提供。先从[固定 Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-tank-style-endfield/v1.4)下载 `.skill.zip` 到 `.cache/releases/`，也可使用已登录且有仓库读取权限的 GitHub CLI：

```bash
gh release download 'war-thunder-tank-style-endfield/v1.4' --repo IcyRyna/war-thunder-skin-skills --pattern '*.skill.zip' --dir .cache/releases
```

然后把下载文件作为素材来源传给检查器和构建器：

```bash
python -B tools/repository.py check war-thunder-tank-style-endfield --asset-archive .cache/releases/war-thunder-tank-style-endfield-v1.4.skill.zip --require-assets
python -B tools/repository.py build war-thunder-tank-style-endfield --asset-archive .cache/releases/war-thunder-tank-style-endfield-v1.4.skill.zip
```

素材以仓库清单记录的身份进行核验。不能用其他版本的相似文件补齐，也不能以一份缺素材的包替代完整候选。`.cache/` 与 `dist/` 留在本地，不进入 Git 历史。

## 修改与评测

| 修改对象 | 源码位置 | 需要核对 |
| --- | --- | --- |
| 研究流程、实验与规则契约 | `src/study/`、`evals/` | 记录能否定位来源、规则、运行和审查范围 |
| 中性工程流程 | `src/build/` | 输入、UV、通道、导出与交付边界 |
| 飞机公共工具 | `toolkits/aircraft/scripts/` | 所有引用包的装配与既有运行契约 |
| 风格说明与专属工具 | `src/styles/` | 适用范围、规则差异、基线对照与失败边界 |
| 载具配置 | `profiles/` | 资源身份、表面映射及实际载具验证状态 |
| 兼容工作流 | `src/legacy/` | 旧 Skill ID、参考链接与运行路径 |

评测记录字段和检查器用法见 [`evals/CONTRACT.md`](../evals/CONTRACT.md)。技术效果、视觉质量、游戏表现、重复与迁移分别记录，未执行项写明 `not_run`。合成示例只验证契约用法，不能作为真实载具适配成果。

改公共实现时只维护单一源码，再重新装配受影响的包。检查、测试和候选构建完成后，提交具体结果与规则差异供审查。仓库 CI 提供自动检查，其结果不替代上述人工审查。

## 正式发布

每条 Skill 版本线独立递增，标签使用 `<skill-id>/v<版本>`，安装包命名为 `<skill-id>-v<版本>.skill.zip`。发布决定应指定候选、文件、目标版本线与允许采用的范围。

1. 固定获准候选的输入、工具版本、素材身份与输出清单。
2. 完成包内路径、必要资源、相关回归与独立使用检查，并保存 SHA-256。
3. 更新该 Skill 的功能说明、逐版更新记录、首页下载入口和发布索引。
4. 按获准范围创建标签与 Release，上传独立安装包。
5. 回读远端标签并重新核对附件内容，确认与审查过的产物一致。

已有正式版本通过 [`releases/index.json`](../releases/index.json) 与[下载页](../releases/README.md)索引。仓库结构调整保留历史标签、附件和逐版记录；新目录与新的构建尝试不自动产生新 Skill 版本。

## 文档与素材

首页说明研发流程、实际状态、源码入口和已发布下载。功能页描述对应正式版本，更新记录描述真实的版本变化。机器环境、完整对话、未公开作品评价和中间审计留在制作或研究环境；仓库仅保存适合分发的结论、来源与必要资料。

大型参考图留在 Release 安装包，来源与哈希保留在素材清单中。素材的使用和处理方式见[来源说明](credits.md)。

[返回首页](../README.md) · [研发流程](workflow/README.md) · [安装指南](installation.md)
