# 0.1.6 运行纹理与交付合同

本文件把“导出的图就是检查过的图，游戏包就是审过的运行文件”变成可重复检查。它不模拟游戏shader，也不自动判断艺术效果。

## 每个DDS一份声明

runtime_textures为列表，每项：

    {
      "id": "turret-n",
      "dds": {"file": "runtime/turret_n.dds", "sha256": "实际摘要"},
      "role": "normal",
      "alpha_semantics": "packed_data",
      "color_space": "linear",
      "state": "modified",
      "baseline": {"file": "inputs/turret_n.png", "sha256": "实际摘要"},
      "canonical": {"file": "export/turret_n.png", "sha256": "实际摘要"},
      "encoding": {"mode": "exact"}
    }

color使用fixed_rgb或opacity、sRGB；normal使用packed_data、linear；ao使用scalar_data、linear。实际DDS DXGI必须一致，N/AO不能带sRGB标记，N.A不作为透明度。其他shader语义不能伪装成该合同。

preserve指baseline到canonical全部像素一致；编码是否允许有损由encoding另行决定。某材质区域保留而同一纹理其他区修改时，在materials.preserve_samples中引用runtime_texture_id和保留mask。修改N但把材质改名preserve不能跳过。

## 有损编码单独验收

默认exact。需要有损候选时显式声明：

    {
      "mode": "bounded",
      "max_abs": [8, 4, 8, 4],
      "max_mean": [1, 1, 1, 1],
      "max_normal_angle_deg": 2,
      "evidence": {"file": "verification/encoding-choice.json", "sha256": "实际摘要"}
    }

这些数值只是字段示例，不能直接当某辆车的认可配方。脚本限制最大单通道误差≤32、平均≤8、法线方向≤5度；实际选择应更严格并有依据。逐mip任一级超限即失败，不按全车平均掩盖局部异常。R/B的制作配方波动与编码误差是两种不同概念。

每级报告尺寸、实际解码RGBA哈希、canonical语义mip哈希、RGBA最大/平均误差以及N法线最大角度。完整链必须到1×1；不能只看header的mip_count。数据mip按当前已核实战雷打包语义逐标量过滤，不套普通RGB法线算法。

编码误差通过不证明低级mip在真实模型的图岛/玻璃/窄边旁没有不良观感；滤波、压缩块和LOD仍按观察矩阵检查。

## 模型资源与BLK闭环

bindings资源清单示例：

    {
      "schema_version": 1,
      "unit_id": "实际目标",
      "model_sha256": "实际原生模型摘要",
      "resources": [{
        "resource": "实际原生资源名_n",
        "role": "normal",
        "alpha_semantics": "packed_data",
        "color_space": "linear",
        "shader": "实际材质shader",
        "users": ["实际部件/材质槽"]
      }]
    }

运行BLK严格解析replace_tex/set_tex与from/to，set_tex必须使用camo_skin_tex。每个实际DDS必须被映射；源资源不得冲突、缺少模型slot或把C/N角色互换。模型清单不是从新BLK反推出来的，需要从实际原生输入提取并冻结。

最终模型若本次明确获准改UV，应以实际交付模型作为目标身份并重新生成对应清单、覆盖与所有共享检查；本流程本身不授权改UV。

## ZIP身份

final_runtime_files每个成员都声明package_path，例如UserSkins/Vehicle/turret_n.dds。实际BLK同目录相对引用必须能指向相同成员。额外的模型依赖按原生交付结构列入名单。

delivery_validate执行：
1. 本车final完整检查；
2. ZIP严格<100,000,000字节、解压严格<200,000,000字节，成员路径和CRC合格；
3. ZIP文件名单与运行名单双向相等；
4. 每个实际成员流式SHA与受审源字节相等；
5. 因ZIP内BLK和DDS已逐字节一致，其绑定对应严格解析过的同一份模型slot与纹理声明。

报告单列budget_pass、runtime_identity_pass、dds_semantics_pass及统一technical_pass。只放一个很小的无关文件的ZIP可通过预算工具，但无法通过此交付验收。

## 当前边界

严格DDS解码支持本Skill导出器的DX10 RGBA8、BC3、BC7单张2D纹理；数组、cubemap、体积纹理、其他格式及legacy容器不猜测通过。实际游戏加载、选中目录、镜片shader、动态网布与附件状态属于对应游戏证据。rc3使用合成回归、三车真实输入及A7HU现有工程的离线回放，具体通过和未通过项目见validation.md；尚未独立制作未见车型。


运行清单默认只接收DDS和车辆BLK。实际配套原生模型.bin/.grp另以kind=native_model_dependency及dependency_evidence说明必需性；源码、工程、图片、日志和普通文本不能混入游戏包。


rc3新增native_resources与实际BLK映射集合一致性、合法OPAQUE颜色标记核验、BC7逐mip解码，以及Composa的显式局部舍入合同，详见[schema 3](schema-3-contract.md)。

## 2026-10-29工具调用审计补充

生产交付必须按[工具调用与回执契约](tool-execution-contract.md)提供production_tools schema 1。vehicle_review final仍是技术检查；delivery_validate额外核对真实编辑、保存、复制重开、导出、后处理关联和Blender执行/实际不可用证据。旧日志缺字段时据实转换或补做缺失步骤，不生成虚构成功记录。

预览默认单张iso；七张及以上需本次明确用户请求记录。渲染器source_face_ids用于追溯被略过退化面后的原始面身份，不能把导入器的数组下标当原生面号。Windows editor_batch固定UTF-8子进程日志，未知结果先读回执再决定，不自动重放编辑。
