# OpenAI 图像工具的可选适配

只在当前环境有 OpenAI 图像工具，或用户指定使用其模型时读取本参考。它是 [图像辅助编辑](image-assisted-editing.md) 的供应商分支，不是素材获取或整机制作的前置依赖。其他模型按各自接口执行；没有图像模型时使用用户给图、自主检索和分层编辑路线。

## GPT Image 2.5

指定 GPT Image 2.5 时，精细原立绘编辑优先请求 `gpt-image-2.5-sunburst`。`gpt-image-2.5-flare` 可用于有明确速度要求的候选比较，使用同一组输入和检查标准后决定是否适合。用户指定完整模型名时按其要求执行。此偏好只作用于该模型系列，不能覆盖用户对其他供应商或本地模型的选择。

按当前官方模型页和图像编辑接口核对模型名、参数与可用权限。原立绘编辑使用 `/v1/images/edits` 并传入真实输入图片。透明输出使用 PNG 或 WebP。不要因为其他模型有同名参数，就给 2.5 添加未经确认的 `input_fidelity`。

图像编辑接口支持遮罩时先核对格式、尺寸与 alpha 语义；其透明遮罩区域表示可编辑区域。仍需观察输出，需逐像素保留的部位从原图合成。

## 有内置图像工具时

先检查实际工具 schema。一般图像编辑优先使用该环境可用的内置图像工具。若工具提供 `referenced_image_paths`，有本地路径的输入先查看，再按此参数传入；只有缺少本地路径的对话图片才按工具规则使用最近图片参数，不能同时使用两种机制。其他 schema 按其实际输入方式处理。

精确版本要求必须落实到有模型选择能力的工具、API 或配套 CLI。工具没有 `model` 参数时，在提示词中写模型名不能完成切换，也不能宣称已调用 2.5。此时记录版本未确认；需要精确 2.5 的任务使用已经核实的模型选择路线，不静默换成其他版本。

## 有配套 CLI 时

只有运行环境实际提供 imagegen CLI 时才使用。先查看 `--help` 和参数验证逻辑，不复制或修改系统 CLI。明确传入 `--model gpt-image-2.5-sunburst`；旧版助手脚本可能只接受 `auto`、`1024x1024`、`1536x1024`、`1024x1536` 和 `low/medium/high/auto`，按当前脚本支持的值调用。API 新增的尺寸或质量值不能直接当作本地助手脚本已经支持。先做 `--dry-run` 核对请求，再按已授权的编辑任务实际执行。

下面是 Codex 的 Windows 环境已经具备配套 CLI，且工程中已准备好原图与指令文件时的调用示例；其他 Agent 不要求这些路径存在：

```powershell
$codexSkillRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$imagegenCli = Join-Path $codexSkillRoot 'skills/.system/imagegen/scripts/image_gen.py'
python "$imagegenCli" edit --image 'assets/character-original.png' --prompt-file 'edits/character-recolor.txt' --model gpt-image-2.5-sunburst --size 1024x1536 --quality high --background transparent --output-format png --out 'assets/character-recolor-v1.png' --no-augment --dry-run
```

实际编辑使用同一组已核对参数去掉 `--dry-run`，并使用该环境已经配置的凭据。请求预检查只证明本地构造了指定模型的请求；API 返回成功、输出图片存在并完成观察之后，才能报告实际编辑已执行。提示词、模型请求名和检查结果留在制作工程，凭据不进入工程或分发包。

## 官方接口参考

模型选择与提示方法见 [OpenAI 图像提示指南](https://developers.openai.com/api/docs/guides/image-prompting)，模型能力见 [GPT Image 2.5 Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)，编辑参数见 [图像编辑接口](https://developers.openai.com/api/reference/resources/images/methods/edit)。执行时核对当前文档与实际工具参数。
