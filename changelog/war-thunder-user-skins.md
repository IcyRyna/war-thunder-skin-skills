# war-thunder-user-skins 更新记录

通用制作流程：素材、原 UV、材质、工具、打包和验收；不带特定画风。

“研究修订”是工作区 `research/tasks/skill-aesthetics-20261017/revision-N`，同一修订号的两个 Skill 是一起发布的。

| 版本 | 日期 | 研究修订 | 改了什么 | 下载 |
| --- | --- | --- | --- | --- |
| 3.11 | 2026-10-19 15:14 | rev 14 | 原 UV 逐组复刻：新增 replica_measure.py（描直边轮廓、按元素测渐变、马赛克拟合含边缘证据与固定格距、放大读格、游戏图标配准、整区自动测量并跳过原厂部件）和 replica_check.py（实际使用纹素、计划编辑含镜像轴与按测量拉直、计划转设计、一组一验、整机组装）；vector_paint 马赛克加 mirror；uv-native-replica.md 写入完整流程清单和 F-2A 整机复刻经验；新增 resource-markings.md | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.11) |
| 3.10 | 2026-10-18 23:07 | rev 12 | 原尺寸检查与面板线闸门：新增 detail_sheet.py（8192 颜色图按 1:1 和参考同米制比例并排，出 Composa 调用清单）；panel_lines.py 加质量闸门、描线不合格拒绝画，面板线默认不画；立绘改为干净抠图；design_lint 允许垂尾描边序列 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.10) |
| 3.9 | 2026-10-18 18:27 | rev 11 | 面板发丝线与接缝：新增 panel_lines.py（照原厂贴图描面板分块线和铆钉排，画成干净的发丝线）；surface_map.py 标出凸起背鳍条之类的接缝；白色规则允许成组的渐尖尖片 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.9) |
| 3.8 | 2026-10-18 15:59 | rev 10 | 漆面与白线：整机一层亮漆 coat_material.py、thin-white-line 检查、颜色图 8192、修正交叉的嵌套 V 示例 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.8) |
| 3.7 | 2026-10-18 03:57 | rev 9 | 审计跟进（Sonnet 5.5）：缓存目录改中性名、缺字体报错、WT_SKIN_FONT | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.7) |
| 3.6 | 2026-10-18 03:41 | rev 8 | 两个 Skill 各自独立成包，互不引用 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.6) |
| 3.5 | 2026-10-18 03:29 | rev 7 | 审美纠偏：字体、配色、布局偏向表；新增 design_lint.py | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.5) |
| 3.4 | 2026-10-18 03:06 | rev 5 | 风格 Skill 审计修正；surface_map.py 识别遮挡 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.4) |
| 3.3 | 2026-10-18 02:28 | rev 4 | J-16 陈千语 v5–v9 经验：共用 UV 图表顺序、朝上阈值、平整区落笔；新增 surface_map.py | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.3) |
| 3.2 | 2026-10-18 01:47 | rev 3 | 文件不乱放：Numba 缓存进系统临时目录、脚本加 -B | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.2) |
| 3.1 | 2026-10-17 22:24 | rev 2 | 用户反馈：垂尾外侧放立绘、立绘素材不重复 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.1) |
| 3.0 | 2026-10-17 20:59 | rev 1 | 审美与线条体系重写：审美基线、vector_paint 矢量直绘、对照板；分出 Akamywek 风格 Skill | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v3.0) |
| 2.12 | 2026-10-17 20:06 |  | 经验回写与冗余清理（2.x 最后一版） | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.11 | 2026-10-17 02:55 |  | 结构化补全：加入自绘示意图（34 个文件） | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.10 | 2026-10-17 00:40 |  | 表面研究补充 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.9 | 2026-10-16 23:54 |  | 五套复刻：发布核验 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.8 | 2026-10-16 23:39 |  | 五套复刻：发布修正 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.7 | 2026-10-16 23:30 |  | Akamywek 五套复刻练习：经验发布 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.6 | 2026-10-16 20:34 |  | Akamywek 展开贴图对照研究结论 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.5 | 2026-10-16 20:13 |  | Akamywek 线条规则与实际设计差距的修正 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.4 | 2026-10-16 20:02 |  | J-16 清晰度审计补丁 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.3 | 2026-10-16 06:23 |  | Akamywek 线条迁移研究：定稿 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.2 | 2026-10-16 05:00 |  | Akamywek 线条迁移研究：规则草案 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.1 | 2026-10-16 03:41 |  | 线条与质感实物复核的修正版 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 2.0 | 2026-10-16 02:51 |  | 工作流补强、J-10C 线条与材质失配审计：加入公共脚本（31 个文件） | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v2.x) |
| 1.15 | 2026-10-15 00:30 |  | Rossi 清理后的规则回写（1.x 最后一版） | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.14 | 2026-10-14 18:15 |  | 垂尾外侧立绘与素材多样性 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.13 | 2026-10-14 17:32 |  | 人物裁切优先级 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.12 | 2026-10-14 16:01 |  | 垂尾与整机上下文对照 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.11 | 2026-10-14 14:24 |  | 垂尾承载面细化 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.10 | 2026-10-14 10:48 |  | 尾面布局 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.9 | 2026-10-14 10:37 |  | 尺度可读性：线宽、字高与观看距离 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.8 | 2026-10-14 08:47 |  | 材质可读性：R/B 通道与受光对照 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.7 | 2026-10-14 08:27 |  | 对比度复查 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.6 | 2026-10-14 07:57 |  | 垂尾立绘裁切 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.5 | 2026-10-14 07:33 |  | 机腹布局规则 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.4 | 2026-10-14 06:49 |  | 整机视觉节奏：主路径、安静区与密度 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.3 | 2026-10-14 06:25 |  | 各表面布局细化：承载面、构图与验收 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.2 | 2026-10-14 05:54 |  | 按现有工具能力调整流程（能力适配） | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.1 | 2026-10-14 04:08 |  | 接入图像模型辅助编辑（image 2.5）的输入、保护域与检查 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |
| 1.0 | 2026-10-14 03:41 |  | 最早留存的快照：单一 Skill，只有 SKILL.md 和参考文档 | [Release](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/war-thunder-user-skins/v1.x) |

1.x 的包都是“某次修改之前”的快照，这里把每份快照算作上一次修改的结果，简介取自上一次修改任务的名称，属于推断。
