# 完整范围与实际画面审计

数字检查回答“在声明的范围内是否符合条件”；它不能决定声明范围是否正确，也不能自动决定画面好看。制作前固定真实对象，制作后同时看完整对象、最终像素和实际模型。用户指出需要占满的板件，继续以整块原生板件为基准。

## 范围不能随失败结果收缩

每个 coverage 增加 `scope_contract: {file, sha256}`，指向制作前保存的独立 JSON：`model_sha256`、`native_resource`、`layer_role`、`mode`、`target_source_faces`、`reason`。source faces 使用原模型完整面号。vehicle_review 对比实际目标面组与该文件，目标少一面、换材质资源、把 full_surface 改成 partial 均拒绝。正常设计变更先说明真实物理原因并保留旧范围与新范围的差异，不能在覆盖失败后重写合同来消除错误。

单独运行 surface_coverage 仍只审计传入的范围；它的通过不能替代 vehicle_review 的完整范围检查。材质面组、首下、侧裙后段、折边、顶盖、火控窄框和小支架都适用此规则。没有纹样的完整机械件可以按真实材料保持素面，不能因为只画了它的上半截而把下半截改名为“安静区”。

原生 bindings 必须带 `source_inventory: {file, sha256}`，引用原导出器的 materials 清单（obj_name / shader / texture_slots），不得由本轮声明反向生成“来源”。核对模型实际使用的全部材料及 C/N/AO 槽。允许相同材料的完全相同重复导出，拒绝冲突定义。同一资源有多个 shader 时，用 `shader_by_user` 逐使用者记录；不能只保留第一个 shader。实际车辆常见同一玻璃资源被多种 shader 使用。

## 检查过不等于满意

视觉记录与 checked 方向记录必须给出：

- `verdict: satisfactory`、具体 `observation`；`needs_fix` 或未判定直接阻止通过。
- `images: [{file, sha256}]`，实际可解码的模型检查图或游戏截图。JSON、文字备注和文件存在不能替代图像。
- `artifact_binding`：当前 `model_sha256`、`texture_kind`（base_color 或 runtime_dds）和完整 `texture_sha256` 字典。底色用实际 base_c；最终检查用全部交付 DDS。产物变化后旧图作废，重新检查。
- 当前实际工具回执和渲染输入链仍按 production_tools 核验；写一个新哈希字段不等于重新渲染。人工读图结论和机器证据校验分别陈述，不能把 `satisfactory` 当用户美术认可。

视觉记录还必须携带`render_receipt: {file, sha256}`。回执绑定实际model_sha256、bound_runtime_dds（底色检查为bound_base_colors）、成功exit_code、执行script及run_log，并在renders里列出每张实际图片的file、sha256与texture_kind。选择的每张图都必须出现在回执中且种类一致。只改检查表里的artifact_binding、继续沿用旧图和旧渲染回执，会被拒绝；底色图不能拿来声称最终DDS检查。

checked 方向不允许空 coverage；六方向全部 not_visible 不能通过。没有被任何检查图覆盖的范围必须逐项记录真实遮挡/不可得限制及证据，不允许整体跳过后汇总成“全车通过”。保留材质检查如果没有任何运行像素可比较，只能报告 `no_runtime_override / unchanged=null`，不能把 0 次比较显示为“像素完全保持”。

## 无装饰底色必须来自正确图层状态

按真实图层职责保存可见状态。只隐藏蜂窝、身份/警示图组、数码副纹样和新增色标；保留首上大几何、板件灰区、材质色层、格栅素面和原生功能色。不要只留下名为 00-base 的一层。先导出无装饰检查，再恢复原状态，保存、复制重开，并比较最终导出像素；图层命名变化时重新核对实际名称/ID，不能只靠旧关键词猜测。
