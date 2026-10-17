# 二次元喷气机的分层编辑

使用当前可操作且满足分层、图文与导出需求的编辑器。功能与参数以实时 schema 为准，不把界面能力当已有 MCP API。Composa 可用 scripts/composa_mcp.py，其他编辑器走其真实接口。

按职责保留色场、人物、文字、图形、结构和材质遮罩。原图备用层独立，文字保持文字层；复杂图形保留 SVG 源，栅格导入范围如实说明。素材适配见 [素材与布局](assets-and-layout.md)，生成素材验收见 [图像辅助编辑](image-assisted-editing.md)。

当前 Composa 的 transform_layer x/y 为左上角，place_image x/y 为中心；明确文档与图层定位。保存 CMPS，导出图片由文件工具衔接 TGA／DDS。任意 alpha、分组、mask 或布尔操作只有接口支持才用。

正交覆盖图导出保持配对参考画布、位置和方向，隐藏底图与诊断层；直接 UV 图保持原比例。导入后检查实际图形、alpha与关键位置，clip／mask 可能被转换器忽略。复合字形检查填充规则：分离闭合笔画采用 evenodd 时，交叠处可能被挖空，需看实际栅格连接再修轮廓或填充。

修订诊断优先从当前工程替换对应贡献再导出；透明新层不会擦掉旧对象。最后按 [工程重开](packaging-and-validation.md#工程可继续编辑) 检查真实可逆编辑、撤销及导出一致性。

## MCP 客户端

--exe、COMPOSA_EXE 或 PATH／常见 Windows 目录定位可执行文件。工具列表为空时查应用初始化和 AI Control；按会话已有授权打开应用，客户端不代启该开关。

```powershell
python scripts/composa_mcp.py --out output/editor-tools
python scripts/composa_mcp.py --calls calls.json --out output/editor-session
```

calls 是 name/arguments JSON 数组。客户端预检工具名与必需字段、顺序执行并在首错停止，服务器负责完整 schema 校验。每轮使用全新空 --out，--timeout 为每请求1–60秒；--launch 使用应用自身启动选项，普通发现不修改 AI Control 或助手配置。

session.json 的 completed 仅说明该批调用完成。发送前写 attempts，原响应先落 responses，再解析图片和兼容结果。图片／磁盘处理失败不证明编辑未执行，先保留结构证据并查询文档。

响应图片目前只物化静态、非隔行8-bit灰度／RGB PNG，可带alpha；索引色、16-bit、动画等明确拒绝，原响应保留。该限制不改变服务器自身导出能力。

超时或缺完整响应标 unknown_applied；禁止自动重放整批。在新只读会话核对文档、图层、内容及保存状态，与最后已确认步骤对照，再补缺步或仅重导出。服务错误同样检查部分应用，旧失败证据保持。
