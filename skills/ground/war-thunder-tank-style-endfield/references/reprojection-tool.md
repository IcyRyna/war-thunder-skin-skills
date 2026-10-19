# 逐纹素表面转移工具

`scripts/reproject_surface.py` 将已确认对应的三维表面颜色与材料转入目标原生 UV。它使用 OpenGL 4.3 和来源三角形 BVH，逐纹素求命中点与来源 UV，避免单纯逐顶点外推跨过来源 UV 接缝。

它不判断构图是否适合目标车，也不能把旧车机械底图自动分成纯设计图层。跨车系只迁移风格时，优先重新布局，不能用更大的搜索半径把无关表面强行套在一起。

## 运行

```text
python -B scripts/reproject_surface.py --config design/reprojection.json --part body
python -B scripts/check_uv_reprojection.py
```

需要 Pillow、NumPy、OpenCV、Numba、ModernGL 和 OpenGL 4.3。使用已有环境。检查器在系统临时目录建立小模型，验证平铺小件不能覆盖主面，同时核对零颜色 Alpha、目标法线与输入文件不变。

## 配置

所有输入和输出路径相对于配置文件。`parts` 的键由当前任务命名；模型文件夹含 `assembly.obj`、`materials.json`，可带已存在且有效的 `geometry.npz`。缺少有效缓存时在本次输出内生成缓存，保留输入模型。

以下展示字段结构，资源名和路径应取本次真实输入：

```json
{
  "parts": {
    "body": {
      "inputs": {
        "source_model": "../source/reference-model",
        "target_model": "../source/target-model",
        "source_c": "../reference/body.png",
        "source_n": "../reference/body_n.dds",
        "source_base_n": "../reference/native_body_n.dds",
        "target_c": "../source/native/body_c.dds",
        "target_n": "../source/native/body_n.dds",
        "coating_shader": "coating.glsl"
      },
      "source_resource": "reference_body_c",
      "target_resource": "target_body_c",
      "size": [8192, 8192],
      "role": 1,
      "radius": 0.10,
      "source_offset": [0, 0, 0],
      "output": "../workbase/v1/body",
      "minimum_uv_owner_density": 0,
      "coating_component_min_area": 0,
      "node_tags": {},
      "collapsed_uv_regions": []
    }
  }
}
```

资源选择读取 `materials.json` 的真实纹理槽，不依靠材质显示名的前缀。`source_offset` 是经确认的来源查询平移，不能替代姿态、尺度或部件身份核对。

`runtime.skill_scripts` 仅在任务使用外部工具位置时需要；独立安装的包默认从脚本自身目录导入 `tank_core.py`。

| 字段 | 含义与边界 |
|---|---|
| `radius` | 模型坐标单位中的最大搜索距离；先核实导出单位与实际对应关系 |
| `minimum_uv_owner_density` | 非零时过滤三维面积/UV面积过低的回绘面；默认不启用，不作为跨车型固定阈值 |
| `coating_component_min_area` | 非零时按连通组件三维面积标记可涂的大面；阈值由当前模型确定 |
| `node_tags` | 当前模型已核实的节点名到整数标签；供独立涂层规则选择部件 |
| `role` | 当前资源的整数类别，含义由本次涂层规则定义 |
| `collapsed_uv_regions` | 明确的三维范围、颜色与可选 R/B，用于零面积 UV 采样足迹 |

零面积 UV 区域形式：

```json
{
  "bounds": [[-1, 2, -1], [1, 3, 1]],
  "rgb": [42, 43, 43],
  "packed_rb": [117, 5]
}
```

这些数值只是结构示例。不给 `packed_rb` 时保留目标原生 R/B。采样足迹有固定像素扩展，需按本次纹素密度检查它是否触及邻岛。

## 独立涂层规则

`coating_shader` 是本次任务自己的 GLSL 规则。最小接口为：

```glsl
void applyCoating(vec3 p, vec3 N, vec4 stock, float paint,
                  bool matched, inout vec4 color,
                  inout vec4 pbr, inout bool recoated) {
    pbr.ga = texture(target_n, target_tc).ga;
}
```

这个接口示例保留转移颜色并恢复目标 G/A 结构法线。实际任务仍需写明所需色块、材质和部件约束。

规则可读取 `component_tag`、`can_paint`、`material_role`、`target_tc`，以及目标颜色/材质采样器。可选输入 `design_logo` 提供带透明度的标志图。需要明确解决重叠 UV 写入优先级时，可设置 `owner_depth_override` 为 0–1 的深度；数值越小越优先。先确认谁应拥有这些纹素，不能用优先级掩盖几何对应错误。

对清洁新漆，可保留 `texture(target_n, target_tc)` 的 G/A，并分别设置漆面 R/B。对原生金属或软质附件，保留相应目标材料。坐标掩码、节点标签和图形尺寸保存在任务规则中，不写死在工具或通用 Skill 里。

## 输出与验收

输出包括 `color.png`、`color-view.png`、`normal.png`、使用范围、匹配诊断和报告。`color.png` 保留零 Alpha 供固定 `replace_tex` 使用；`color-view.png` 用于编辑器查看。工具不改写来源图像、OBJ 或材质清单，输出目录必须是新版本。

报告的命中比例、过滤面数和零面积 UV 面数仅作诊断。仍需检查真实模型、字标、图形接缝和材料，再打包 DDS。此工具不替代最终游戏内确认。
