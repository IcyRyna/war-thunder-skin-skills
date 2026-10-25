# J10C鸭翼局部构形实做

这是第三轮真实开发试作的设计JSON，长度单位为米；它只画上下鸭翼的红白复合形，不是一套完整涂装或通用模板。

输入几何为本机游戏`j_10c` LOD0，原始UV不变，材质`j_10c_aircraft_normal_detail_lo`，节点`elevator0`与`elevator1`。原始几何身份见[测量数据](../../references/whole-layout-measurements.json)，源角点和迁移过程见[构形记录](../../references/source-constructions/rafale-to-j10c.json)。几何与游戏资源不内置，需用自己的已核验profile提供。

构形保留三点红形、四点白形、独立终点和暗缝。外接框迁移失效；实体角点对应之后，本例再以目标角点三角形中心为基点整体收至0.95。这个值不能当成其他机型默认值。实际8K输出的左右、上下四面均做了边界采样和内部颜色抽查，并查看模型上下视图。未证明游戏动态状态或任意载具迁移。
