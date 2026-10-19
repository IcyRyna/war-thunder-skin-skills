# 修订 15：把 F-2A 方法第一次用到新机型（J-10C）时学到的东西写进 Skill

发布为通用 Skill 3.12、风格 Skill 1.12。

起因：用户要用 rev 14 的新 Skill 从头做 Akamywek 风格莱万汀 J-10C v4（只做基本布局，不放立绘，不参考 v1–v3），并要求记录过程，把经验总结进 Skill，整理成方便复刻的工作流。v4 的完整工作流记录在 `assignments/j10c-laevatain-akamywek-20261018/verification/v4/workflow.md`，复核结论在 `evidence/rev15-j10c/review.json`。

基线：`baseline/`（通用 3.11、风格 1.11 发布源和发布包，`manifest.json` 是逐文件哈希）。候选：`candidate/`。发布：`publish_revision15.py` → `publication/`。

## 缺陷修复（每条都有测试）

1. **别的颜色贴图混进来。** `replica_check.py`：新增 `colour_maps`、`skin_texture`，只取涂装那一张颜色贴图的材质；场景里有几张颜色贴图时，`used`、`plan`、`check`、`assemble` 都必须用 `--texture` 指名，否则拒绝。`check` 的同相机渲染也只替换这一张贴图。（J-10C 喷口 `j_10c_nozzle` 用 `j_10c_n_rgb.png`。）
2. **UV 铺满整张图的辅助件。** `vector_paint.py`：新增 `helper_triangles()`，在每张颜色贴图内部按纹素密度（超过面积加权中位数 8 倍）找出辅助件（J-10C `tail` 里一个 10 cm 方块）。`sampling_triangles`（已用纹素、接缝外扩）和 `select_charts`（图表分配）都排除它们。不排除时有两个后果：
   - 已用纹素变成 100%，接缝外扩失效；
   - 每个图表的种子都落在它上面，第一个图表认领它，它又以最高优先级把整张图按那个图表重画一遍，别的图表全被冲掉（J-10C 试画 a1：图层 02、04 的着色纹素是 0）。
3. **frame 图表的误报。** `vector_paint.py` 对有 `frame` 的图表不再按世界轴报“foreshortened over 2x”（展开机身误报 36%），收据里标 `frame: true`。

## 新功能

4. **`airframe_setup.py`**（从任务工具 `tools/v4/atlas_map.py`、`landmarks.py`、`frames.py`、`clean_base.py`、`area_shares.py` 通用化）：
   - `map`：岛地图、每纹素机体坐标（`coords.npz`）、站位线 / 中线 / 顶侧底分界叠图。
   - `frames`：每块 **UV 连通岛**一条米制 frame（和 vector_paint 的 island 规则一致）。先用平面三角形拟合，再迭代剔除离群三角形，分别报拟合部分和整岛的残差。J-10C 上自动得到和“按节点指定”一样好的结果（主翼上表面 2.7 / 9.6 / 13 px），并列出了任务设计漏画的内段升降副翼岛。
   - `clean`：按岛判断蒙皮和机械件，输出干净底色和保护遮罩，并报告原厂贴图的亮度、饱和度分布，供定阈值。
   - `shares`：渲染图的深底 / 签名色 / 淡染 / 白面积比和七视图拼图。
5. **`replica_check.py plan`**：马赛克可以直接写 `{"cell_px", "angle_deg", "origin_px", "inset", "levels"}`；`--provenance` 写明来源（原创设计不再固定标成“测量重建”）。

## 文档

6. 新参考 `references/new-airframe.md`《新机型上手》：从模型到第一版基本布局的可复刻清单，数字全部来自 J-10C。
7. `SKILL.md`：任务路由和参考列表加入新机型上手；工具表加入 `airframe_setup.py`，更新 `replica_check.py`。
8. `linework-and-color.md`：每层 `painted_texels` 为 0 的含义；图表按 UV 连通岛分；`surface_map` 对 frame 图表只信接缝项。
9. `uv-native-replica.md`：辅助件对图表分配的影响，指向新机型上手。
10. 风格 Skill：
    - `SKILL.md` 制作顺序加第 0 步（新机型准备）和面积比测量；
    - `motifs.md` 加“角度族内排嵌套尖片”；
    - `base-layout.md` 加“J-10C 实测”一节（部位做法、面积、五条经验）；
    - `scripts/`、`references/core/` 由 `standalone_style.py --write` 重新生成。

## 已知局限（如实记录，未修）

- `surface_map.py` 还不认识 frame 图表：遮挡和陡峭按图表世界轴判断，展开机身侧面的字和细线会被误报“被盖住”。文档已写明只信接缝项。
- J-10C v4 还没有用户评价，也没有进游戏测试。这里写进 Skill 的只是“规则在新机型上落地的记录”。
