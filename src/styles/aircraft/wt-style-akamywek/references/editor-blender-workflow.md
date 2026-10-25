# 分层编辑器看UV，Blender看真实表面

需要查看UV、编辑分层或核对立绘在模型上的位置时读取本页。工具能力必须从实际连接和输出确认。Composa是独立分层编辑器，不是Adobe Photoshop；CMPS也不能称作PSD。

## 工具职责与入口

| 工作 | 入口 | 实际要取得的结果 |
|---|---|---|
| 原生UV线框与材质域 | `uv_review_assets.py` | 同尺寸颜色PNG、透明线框、选定域遮罩、输入哈希与非零面数 |
| 原生Photoshop | `photoshop_uv_review.py` | 先只读探测；可连接时生成分层PSD、带UV预览、隐藏UV后的颜色PNG和收据 |
| Composa | `composa_mcp.py`实时schema | 分层CMPS、实际编辑器导出、操作和文档生命周期收据 |
| Blender | `blender_uv_review.py`在Blender中执行 | 带原UV和颜色图的真实模型、UV编辑区、`.blend`、按需一张局部检查图与UV回读误差 |

原生PS适配器在本次审计只通过静态检查和不可用探测，没有获得原生PS实测通过。Composa和Blender的实际验证另有记录。其他机器重新发现运行环境，不能继承本机“可连接”的状态。

## 从真实UV生成编辑器检查资料

先从profile取得正确几何、颜色资源、尺寸、材质名和待查节点。不能把不同材质的0–1坐标混为共享纹素。

```powershell
python -X utf8 -B "$SkillRoot/scripts/uv_review_assets.py" --geometry $Geometry --base $OriginalColour --material $ColourMaterial --node $ReviewNode --out $NewReviewInputs
```

`--material`必须明确，可重复；`--node`可重复或省略以查看该材质全部节点。颜色图由原件无损解码，不覆盖DDS；原Alpha保留。线框以原UV坐标绘制为透明PNG，名称为`UV_GUIDE_HIDE_FOR_EXPORT.png`。查看时与颜色图同尺寸、同原点叠放。此图是0–1 tile的检查视图，报告中的越界UV未被clamp或重排，需在Blender中检查，不能把画布裁掉的区域当作不存在。

## 在Adobe Photoshop中查看

```powershell
python -X utf8 -B "$SkillRoot/scripts/photoshop_uv_review.py" --probe --out $NewPhotoshopProbe
python -X utf8 -B "$SkillRoot/scripts/photoshop_uv_review.py" --base "$NewReviewInputs/base-colour.png" --wire "$NewReviewInputs/UV_GUIDE_HIDE_FOR_EXPORT.png" --out $NewPhotoshopReview
```

默认仅连接已运行的原生Photoshop；本轮确实需要启动已安装PS时可明确用`--launch`。`--probe`不启动应用。缺PS或COM不可连接时输出`unavailable`，不能用Composa结果冒充原生PS成功。

适配器新建自己的文档，将颜色图和UV线框置于独立层；导出检查图，隐藏线框导出颜色，再保存PSD。它保存原有文档身份，成功后只关闭自己创建的文档；失败尝试保存自有恢复PSD并保留文档。调用状态不明时不自动重试。隐藏UV后的RGBA往返不一致会报告失败，不能把偏色结果用于游戏导出。

本工具处理颜色PNG和检查线框；packed材质、法线和数据Alpha仍按profile独立保存，不能经过生成式重绘或随意RGB变换。

## 在Composa中查看与编辑

1. 用`composa_mcp.py --out 新目录`读取当前schema；已有AI控制授权时直接连接。用`document_state`／`list_documents`记录原有文档、实际返回的`document`编号及稳定ID；不假定编号从0开始。跨批次先核对编号与身份仍对应，关闭时用稳定ID／修订。
2. 使用`open_document`打开本批颜色PNG或自己的CMPS。按实时schema，用`place_image`导入已经映射到原生UV的独立图层和线框。全画布图层应保持原尺寸；当前schema的`fit:false, scale:1`及画布中心坐标可用于同尺寸叠放，不能误把整张UV缩到视口大小。
3. 用`describe_document`确认实际图层名称／ID；检查器层与人物、装饰、线条、文字分开。查看像素局部和必要的整体预览。`transform_layer`的画布像素位置与顺时针角度不能直接照搬米制chart坐标或Blender角度。
4. 导出颜色前隐藏线框、定位号和检查遮罩；或先导出无检查层的颜色，再叠放UV检查。保存`.cmps`保留层，`export_image`的扁平PNG不替代源工程。核对导出尺寸、颜色、Alpha和参考图层的预期合成。
5. 默认客户端只收尾本批新建／打开的文档；自有未保存修改先保存检查点。原有文档保持。使用`--keep-open`跨批次时，最后按实际文档ID／修订保存关闭自己文档，不按标签序号关闭，也不强杀编辑器。

PS或Composa只能从线框看出2D岛形；身体是否跨到另一面、鸭翼是否遮脸等问题还要回真实模型核对。

本轮Composa的CMPS复制重开后，UV检查图像素一致；与Python确定性合成相比，编辑区RGB最大差2/255，Alpha和未改区完全一致。此结果不构成通用容差，也不能称为跨软件逐字节相同。具体任务仍记录实际合成差异；精确数据通道保持原件，最终游戏构建使用明确绑定的当前颜色基线，不混用不同合成版本。

## 在Blender中查看真实UV与人物位置

使用本任务可用的Blender CLI，明确路径；不要覆盖用户已打开的场景或改用户偏好。本次实测为4.5.15 LTS，其他版本以实际运行结果为准。

```powershell
& $VerifiedBlender --background --factory-startup --python-exit-code 1 --python "$SkillRoot/scripts/blender_uv_review.py" -- --geometry $Geometry --texture $CurrentColour --material $ColourMaterial --up-axis $ProfileUp --forward-axis $ProfileForward --out $NewBlenderReview --render --view top --pixels 1200
```

`$ProfileUp`、`$ProfileForward`来自已确认profile，例如本次F16A是`y`和`x`，不能由机型名猜测。材质／节点筛选与当前颜色图对应。脚本保留源XYZ和逐面UV，不unwrap、不repack、不焊接，不修改原NPZ；创建NativeUV、颜色材质、UV编辑区并打包颜色图，保存独立`.blend`。Blender网格使用float32，收据记录实际UV回读误差与输入未改动。

在UV编辑区定位脸、手、帽沿、字标和线条尖端，对照3D中的真实部件、上下表面、缝和方向；需要时增加当前问题的一个斜视局部。不要把整张atlas的相邻关系当成身体接续。曲面、共享UV与多面投射不能用伪造的单一2D仿射矩阵证明安全。

命令必须有成功收据、非零面数、实际`.blend`及请求的图像；只看到进程退出0不算成功。`--python-exit-code 1`让脚本异常返回失败。此工具是离线颜色布局检查，未实现游戏shader、动画或全部材质；不自动生成七视图。活动面只能使用有来源的姿态；手工刚性扰动要明确标为探索，不能声称恢复了游戏行程。
