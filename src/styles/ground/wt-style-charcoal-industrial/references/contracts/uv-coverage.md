# 完整原生 UV 覆盖验收

从全部材质槽列出资源C/N/AO、shader、UV占用与共享关系。不从材质名字、节点名字或统一高度阈值推断“机枪/装饰/镜组全部不涂”。例如镜组金属壳体须重涂，镜片保护；履带与轮胎保护不等于裙板支架保护。

每张C图提供同尺寸二值遮罩：occupied（实际UV占用）、paint（决定重涂的表面）、protected（保留的表面）。前两类职责与protected不重叠，且paint|protected必须覆盖occupied。protect区域逐项说明材料/功能及模型证据；不能把没处理的区域塞进保护区。共享UV上存在冲突先解决策略，不能只让遮罩覆盖数字达标。

按整个paint遮罩建立本车中性炭黑基底，再叠加灰块和子版。所有原色检查都在最终C图上执行：全UV缩略图、岛边与小件放大、模型前后/下部/顶部、镜壳与武器外罩。需要padding时使用目标岛与安全距离，避免串色。

运行 uv_coverage.py --occupied occupied.png --paint paint.png --protected protected.png --before original.png --after final.png --out NEW_REPORT。
输出unclassified.png、overlap.png、unchanged-paint.png、报告。未分类/职责重叠/保护区RGBA被改视为技术失败。paint内与原图相同的像素只提示复核：原本已经中性或遮罩边界都可能合法，不自动删细线或强行改像素。报告不能替代保护理由、实际涂层覆盖和模型回查。

普通UserSkins路线在原生UV上重涂，不改UV；若用户已授权原生模型UV接入，按native-model-deployment.md另行验证与成套回退。两条路线均不复制源车整张C/N/AO。固定漆面C的覆盖Alpha与装饰透明Alpha分别处理。最终DDS每级mip检查；渲染必须重新绑定最终DDS。

注意：occupied内职责审计与UV外padding分开。before/after需使用相同通道语义；对已确认opaque_fixed资源，先在独立基线统一覆盖Alpha再比较保护区。alpha-test保护区仍使用原始RGBA，不可用该步骤改写其透明度。

## 共享UV必须来自几何检查

分别光栅化目标三角面和其他三角面的UV覆盖，交集为shared。仅检查修改区外像素不变，仍不能证明其他部件没被牵连；共享像素在同一张图中。默认保护交集，或在有明确成对承载面授权时另建允许策略并同时验收。运行检查器时提供 --shared shared.png；未提供时sharing_checked=false，不能宣称完成共享检查。空交集也需要实际几何证据。
