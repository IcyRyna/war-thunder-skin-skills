# Skill 研究清单校验器 v1

`checks/workflow_check.py` 只校验一个本地 JSON 清单的结构、文件字节与声明之间的关系。它不制作涂装，不评价审美，不安装 Skill，不上传、不发布。Python 3.10+，仅标准库。下列命令从仓库根运行；`$StudyManifest` 和 `$StudyRoot` 分别设为实际研究清单与其文件根目录。

```powershell
python -B evals/checks/workflow_check.py --manifest "$StudyManifest" --root "$StudyRoot" --json
python -B -m unittest discover -s evals/tests -p "test_*.py" -v
```

`--root` 默认为清单文件所在目录。退出码 `0` 表示结构及已声明事实之间的关联有效；`1` 表示非法 JSON、缺文件、哈希不符、状态与证据冲突等。**退出码 0 不等于待审结束或可发布**：必须分别查看 `structural_valid`、`ready_for_publication` 和 `readiness_gaps`。

## 顶层

| 字段 | 类型与约束 |
| --- | --- |
| `schema_version` | 整数 `1` |
| `study_id` | 非空字符串 |
| `candidate` | `{version, files}`；候选版本名，完整候选文件清单 |
| `evidence` | 证据对象数组；ID 唯一 |
| `production_inputs` | 实际进入生产/提炼的证据 ID 数组 |
| `rules` | 规则数组；允许为空，但不能成为可发布状态 |
| `runs` | 实际完成或部分完成的运行数组；未执行时用 `[]` |
| `publication` | `{required_test_cases, authorization}` |

路径是相对于 `--root` 的 POSIX 路径。禁止绝对路径、反斜线、`.`、`..`、空路径段、盘符/NTFS ADS，以及越界的符号链接。所有文件必须存在，SHA-256 必须是小写 64 位十六进制，并与本次读取的真实字节一致。JSON 重复键报错。未知字段保留，允许补充来源、理由与限制。

普通文件引用为 `{path, sha256}`。版本化文件引用为 `{path, sha256, version}`。

`candidate.files` 应枚举完整展开后的候选源文件，包含规则、脚本、资源、模板与参考；不要只登记一个 ZIP，把包内输入藏到工具无法核对的位置。清单本身和评价记录不放进 `candidate.files`，避免自引用。

## 证据

每项含 `id`、`path`、`sha256`、`role`、`kind`。

- `role`：`study`、`development`、`holdout`。
- `kind`：`reference`、`observation`、`run_record`、`technical_result`、`visual_result`、`game_result`、`game_capture`、`user_review`、`publication_authorization`、`other`。
- 参考、观察和其他证据可以是普通文件。运行、结果、评审和授权证据必须是下述 JSON 回执。
- `holdout` 不得进入顶层生产输入、运行输入、上下文输入、候选源或规则提炼证据。文件改名但 SHA-256 相同，仍算泄漏。
- 用过的留出样本应诚实变更为 `development`，保留变更记录，并为后续泛化测试选择新留出样本。工具无法识别未声明的泄漏或从记忆中带入的答案。

## 规则

| 字段 | 约束 |
| --- | --- |
| `id` | 非空且唯一 |
| `scope` | 非空字符串数组，如 `["style:akamywek", "layout"]`；适用运行必须包含全部标签 |
| `claim` | 有边界的具体规则陈述 |
| `required_checks` | 非空子集：`technical`、`visual`、`game` |
| `evidence` | 非空证据 ID 数组 |
| `validation` | `unverified`、`tested_local`、`tested_transfer` |
| `review` | `{status, evidence}`；状态为 `pending`、`accepted`、`rejected` |

技术规则可只要求 `technical`；视觉或游戏内规则应列出真实需要的检查。工具不通过文字猜测规则属于哪一类，也不强制色彩比例或 4/5 审美阈值。明确的视觉量表保存在版本化 `rubric` 文件中。

`tested_local` 要有当前候选在 T01-A/B/C 中至少一个适用运行的成功检查，且规则 `evidence` 引用了该运行最终尝试中所有所需检查的结果回执。`tested_transfer` 还要有 T02 或 T03 的适用成功运行。普通运行日志、文件存在、旧候选的成功记录都不能将规则晋升。

`accepted` 和 `rejected` 必须有 `user_review` JSON 回执：

| 字段 | 约束 |
| --- | --- |
| `decision` | 与规则评审状态相同 |
| `candidate_digest` | 与当前候选文件清单摘要相同 |
| `rule_ids` | 包含本规则 ID |
| `rule_digest` | 由 `rule_digest(rule, evidence_by_id)` 计算，绑定本条规则的正文、范围、所需检查、验证状态和证据身份 |
| `reviewer` | 实际评审人标识 |
| `provenance` | 指向真实用户反馈、会话或评审记录的可核对说明 |

待审规则可以通过结构校验，不能获得发布就绪状态。每个评审回执绑定一条规则定义；涉及多条规则时分别记录回执。局部认可只覆盖对应规则。换候选文件、修改规则正文或扩大范围后，旧回执不再自动认可新版本。

## 运行与输入

每个运行包含：

| 字段 | 约束 |
| --- | --- |
| `run_id` | 唯一非空标识 |
| `test_case` | `T00`、`T01-A`、`T01-B`、`T01-C`、`T02`、`T03` |
| `session_id` | 真实独立会话标识，所有运行之间不得重复 |
| `fresh_session` | 必须为 JSON `true` |
| `agent_version`、`game_version` | 实际版本字符串；未跑游戏仍记录计划目标版本，状态保持 `not_run` |
| `started_at` | 运行开始时间字符串，建议 ISO 8601 含时区 |
| `vehicle`、`theme` | 具体载具与主题标识 |
| `scope` | 实际验证的适用标签数组 |
| `context_sources` | 执行会话接收的额外证据 ID；不能包含留出样本、之前成品的运行记录或事后评语 |
| `execution_evidence` | 至少一个 `run_record` 证据 |
| `inputs` | 下述冻结输入对象 |
| `production_inputs` | 本运行真正接收的其他生产证据 ID |
| `input_digest` | 冻结输入的规范 JSON 摘要 |
| `skill` | `{version, files}`，实际加载的完整 Skill 文件清单 |
| `skill_digest` | 实际加载 Skill 的文件清单摘要 |
| `attempt_count` | 与全部尝试数组长度相同的整数 |
| `attempts` | 全部尝试，按 1、2、3… 连续编号；不得挑选成功项后重新编号 |

`inputs` 含四个版本化文件引用：`brief`、`profile`、`tools`、`rubric`；`files` 为其他输入文件引用数组；`randomness` 为 `{policy, seed}`。`policy` 可以为 `fixed`（必须有种子）、`unspecified` 或 `unsupported`（后两者的 `seed` 必须为 `null`）。可添加其他可控参数，它们也参与输入摘要。

`run_record` JSON 回执必须逐项匹配对应运行的 `run_id`、`session_id`、`fresh_session`、`input_digest`、`skill_digest`、`attempt_count`、`context_sources`、`agent_version`、`started_at`、`scope`、`vehicle`、`theme`，并包含 `recorded_attempts: [1, 2, ...]` 与非空 `observations`。匹配包含 JSON 类型，`true` 不能替代整数 `1`。仅输出文件哈希不能证明独立执行。

### 尝试与三类结果

每个尝试包含 `attempt`、`outputs`、`human_interventions`、`outcomes`。

- `outputs`：本次实际产物文件引用数组。失败尝试可以为空；任何通过项都要求存在产物。
- `human_interventions`：完整人工操作数组；没有则为 `[]`。每项为 `{description, evidence:[ID]}`，证据不得为空，不能引用留出资料作为生产修订输入。
- `outcomes`：必须分别含 `technical`、`visual`、`game`，每项为 `{status, evidence:[ID]}`。
- `status` 只能为 `pass`、`fail`、`not_run`。后者证据为空；通过和失败都要引用对应类别的实际结果回执。

每个结果回执是 JSON：

| 字段 | 约束 |
| --- | --- |
| `run_id`、`attempt` | 指向实际运行及尝试 |
| `check` | 对应 `technical` / `visual` / `game` |
| `status` | 对应 `pass` / `fail` |
| `skill_digest`、`input_digest` | 对应本运行 |
| `output_digest` | 本尝试 `outputs` 的文件清单摘要 |
| `observations` | 真实观察、失败位置、判断理由与限制 |
| `supporting_evidence` | 补充证据 ID 数组，可为空；游戏通过时例外 |
| `game_version` | 游戏通过时必填，并与运行版本相同 |

游戏通过必须有至少一项 `game_capture`。该证据必须是 PNG、JPEG 或 WebP 图片字节；其证据对象还须包含匹配的 `run_id`、`attempt`、`game_version`、`output_digest`。这些字段关联截图与产物版本；工具只检查关系与图片文件头，无法判定截图确实出自游戏，也无法判断接缝是否正确。该判断必须由有权限的评审者完成。

输出保留每个运行的首次与最终尝试是否全部通过；保留失败和人工修订不会被“最终通过”抹去。

## 对照关系

- T01-A/B/C 必须保持同一 `input_digest`、`skill_digest`、`agent_version`、`vehicle`、`theme`，会话各自独立。可以记录确定性工具产生的相同结果；相同结果本身不证明独立性。
- T00 与 T01 保持 `brief`、`profile`、`tools`、`rubric` 的文件哈希与版本、随机性策略和 agent 版本一致。Skill 摘要及文件内容集合必须不同；仅改名不算移除风格模块。
- T02 相对 T01 必须更换载具；T03 保留载具并改变 brief 的实际字节。两者都保持工具、量表的字节与版本及 agent 版本。
- 声明的输入中不能夹带评测产物、游戏截图或结果/评语回执；按文件哈希识别改名复制。该规则同时检查 `context_sources`、`production_inputs` 和 `inputs` 文件引用。额外上下文也进入 `input_digest`，因此不同上下文不能冒充同输入的 T01 重复。
- T00 的失败可作为诚实的基线结果；所有比较项都实际检查后才算完成，不能把 `not_run` 当成失败。
- 旧候选运行可以保留，但会被标为 `stale_run`；它们不能为当前候选提供规则晋升或发布资格。不同候选的整套实验宜分别冻结清单，避免跨轮次重复组混用。
- `publication.required_test_cases` 明确本轮范围，通常填写六项。范围变更必须由真实决策决定；所有已记录的当前候选失败或未完检查都会阻止就绪，不能靠缩小必测列表隐藏。工具无法从一个清单恢复被删除的历史；历史文件应保持不可变并由项目登记保留。

## 发布就绪

同时满足以下条件才得到 `ready_for_publication: true`：

1. 结构、路径、文件字节与所有证据关系无错误。
2. 有规则，所有规则已按各自声明范围验证，且评审均为 `accepted`。
3. `required_test_cases` 均有适用运行；候选测试的每个记录运行最终三类检查均通过；T00 三类检查均已执行。
4. 没有旧候选等未解决就绪缺口。
5. 存在明确、逐文件限定范围的发布授权回执。

`publication.authorization` 为 `publication_authorization` 证据 ID；尚未授权时必须为 `null`。回执包含：

| 字段 | 约束 |
| --- | --- |
| `action` | `"publish"` |
| `authorized` | JSON `true` |
| `authorized_by`、`authorized_at`、`provenance` | 实际授权人、时间与可核对授权来源 |
| `candidate_digest` | 当前候选摘要 |
| `rules_digest` | 当前全部规则定义的摘要；由 `rules_digest(rules, evidence_by_id)` 计算 |
| `files` | 与当前候选完整匹配的 `{path, sha256}` 数组 |

这个工具没有发布命令。JSON 中写一个人名不会使授权变成真实：它只能检查记录一致性，不能认证用户身份、证明会话隔离、判断审美或发现隐瞒的输入。发布执行者仍需核对原始用户授权与真实作品评审。

## 摘要算法

使用模块中的 `files_digest`、`input_digest`、`rule_digest`、`rules_digest` 函数，避免不同调用者自行设计摘要算法。

`canonical_digest` 对 JSON 采用 UTF-8、`ensure_ascii=False`、键排序、分隔符 `(",", ":")` 后计算 SHA-256。

`files_digest(files)` 仅取各项 `{path, sha256}`，按 `path` 排序后计算规范 JSON 摘要。版本名是元数据，真正身份以文件字节为准。

`input_digest(inputs, production_evidence, context_evidence)` 对下面对象计算摘要：`inputs` 全量对象，按 `id` 排序的实际生产证据 `{id, sha256}` 数组，以及按 `id` 排序的额外上下文证据 `{id, sha256}` 数组。第三个参数省略时为空数组。必须先验证各文件引用，不能将任意 64 位字符串当成已冻结输入。

`rule_digest` 取 `id`、`scope`、`claim`、`required_checks`、`validation` 和实际证据的 `id/sha256/role/kind`；不纳入 `review`，避免回执自引用。`rules_digest` 对按规则 ID 排序的 `{id, digest}` 数组计算摘要。规则或其支持证据改变后，需要重新审查相应声明和授权范围。

## 测试边界

`test_workflow_check.py` 所有运行、评审、授权、图片均为标注清楚的临时合成夹具，离开测试即删除。它证明校验器可以拒绝路径越界、哈希缺失/篡改、错误状态提升、泄漏、会话重复、证据串用、缺游戏验收和越权文件范围；**这些单元测试不证明任何真实 Skill 已通过行为、视觉、游戏内或用户验收**。
