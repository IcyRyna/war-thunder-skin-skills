# 载具适配资料合同

机器可检查结构见 [vehicle-profile.schema.json](vehicle-profile.schema.json)，自带 [合成实例](../examples/synthetic/profile.json)。schema 使用 JSON Schema Draft 2020-12；profile 文件不是脚本的命令输入，执行者需按其参数生成真实 CLI 参数和设计稿。

profile 与风格分开版本。风格规则引用稳定语义名，例如 `primary_side`；profile 再提供实际 `resource_id`、遮罩、图表与变换。允许不同机型使用完全不同的 UV；不能把某机型的像素坐标写成风格不变量。

## 必需内容

- `identity`：vehicle ID、variant、类别、平台和模板标识。合成示例必须标 `synthetic_example`，不能冒充真实载具。
- `adapter`：工具包标识、版本／快照哈希、实际能力、支持范围与证据。`external_required` 表示适配未齐；不能推进几何或游戏能力。地面实例不得声明使用内置飞机适配器。
- `files`：profile 所在目录为路径基准；每个文件具有唯一 ID、相对路径和实际 SHA-256。profile 的任务级副本可按当前任务重新登记，不能保留失效路径。
- `textures`：精确 BLK resource ID、文件 ID、尺寸、角色、RGBA 通道和证据。未知通道允许记录，但只可 `preserve`，不能修改。
- `regions`：语义名称、纹理资源、遮罩文件、坐标基准／单位、参考方向与变换；同时说明允许操作与共享／镜像关联。
- `topology`：共享、镜像、接缝、拉伸和禁止覆盖关系；空列表必须结合验证状态解释，不能把没测的关系当不存在。
- `export`：BLK、格式、尺寸／编码、alpha、mip 与资源引用要求，附依据。
- `validation`：检查状态、证据文件、未解决项。`passed` 必须附证据；`not_applicable` 必须写理由。

`files` 中 ID 唯一、引用存在、哈希与尺寸相符、路径留在规定根内、region 所引资源存在，这些跨字段／文件系统约束需要额外检查，JSON Schema 本身不全覆盖。必须在实际构建前检查；只通过 schema 不能写“profile 已验证”。

## 区域与材质证据

mask 约定写成明确文字与数值意义，例如“0 不选、255 选、过渡值作覆盖率”。同时记录原点、UV 的 V 方向、单位、矩阵排列和变换方向。共享纹素必须说明哪些语义区域会同时改变；镜像字样先用定位测试验证。`affine_uv` 不能当作自动修正曲面拉伸的能力。

每通道的 `interpretation_state` 与 `operation` 单独记录。未知时 `semantic: unknown`、`operation: preserve`；已确认的映射要有证据 ID 和适用 shader／平台说明。真实游戏通道不能从合成示例推导。

## 版本和重验触发

模板／模型／shader／解码器变化，重新核验关联部分；保留旧 profile 与旧证据。修订只影响明确载具／改型和经过测试的范围。新载具的工程适配先独立通过，再评判风格迁移，避免把错误通道或坐标误判为风格失效。
