# 颜色覆盖、贴花透明与打包材质分开

## 已验证的颜色故障

AZUR早期颜色在离线图和游戏中不一致，呈现基础迷彩的橄榄色。固定颜色沿用了不适当的资源绑定/覆盖语义。修复同时明确 `set_tex`、`param:t="camo_skin_tex"` 和已确认不透明C的Alpha255；该修复未改RGB各级mip、N或AO，随后灰黑色恢复得到确认。证据支持这套联合契约，不把两处同时修复的观察伪称为各自独立的效果试验。

这类故障不能用“再把RGB调黑”代替诊断，也不能直接归因于导入别车N图。先核对真实shader、from/to资源、当前加载包、Alpha角色、mip与游戏刷新。

## 三类 Alpha

| 数据 | 含义与动作 |
| --- | --- |
| 独立贴花PNG | 实际覆盖；使用预乘滤波处理边缘，格缝与孔洞透明 |
| 已确认不透明的固定漆面C | 最终涂层完整覆盖；核实shader后Alpha255，配套set_tex/camo_skin_tex并逐mip读回 |
| 打包N的A | 可能是切线法线分量等数值数据；依据该车契约保留，不能刷白或做背景移除 |

alpha-test网布、格栅、镜片等不适用全不透明覆盖。共用同一颜色资源的任一材质是alpha-test时，先拆分证据与策略，不用不透明补丁强行覆盖。

## 可执行工具

```text
python -B scripts/fixed_color.py prepare --input composite.png --output NEW_PAINT.png --materials materials.json --resource actual_body_c
python -B scripts/fixed_color.py bind --input source.blk --output NEW.blk --materials materials.json --contract fixed-contract.json
python -B scripts/fixed_color.py export --input NEW_PAINT.png --output NEW_PAINT.dds --semantics fixed_rgb --space srgb
python -B scripts/fixed_color.py check --skin FINAL_SKIN --blk FINAL_SKIN/vehicle.blk --materials materials.json --contract fixed-contract.json
```

契约的bindings逐项声明resource、file、role。已核实不透明固定C才加coverage:opaque_fixed；N/AO声明其真实角色，不加这个coverage。资源名称从目标材质槽取得，不从AZUR示例复制。模板BLK的每份纹理都须出现在契约；N/AO保持原映射。

prepare只改变颜色A，不改RGB；export写完整BGRA8 mip并独立读回。check识别该BGRA8基线以及工程工具输出的DX10格式；其他DDS编码先用已验证导出路径，不静默重解释。真实目标材质尚未验证时先保留其数据语义，不凭数值猜Alpha含义。

N/AO来自目标车。改哑光等参数必须声明实际通道、遮罩与基线，逐像素证明其他通道及保护区未变。Dagor打包N不等同普通RGB法线；离线Blender材质只是近似。
