# 贴图、Alpha 与材料

| 语义 | 含义 | 过滤与 mip |
|---|---|---|
| `fixed_rgb` | 固定替换颜色；全零 A 下 RGB 仍有效 | RGB 按已声明色域过滤，A 独立，不能预乘导致 RGB 消失 |
| `opacity` | 真透明／裁切覆盖，包括透明贴花层与部分网格 | 线性光预乘覆盖过滤后恢复 straight RGBA |
| `packed_data` | packed N 等材料数据；A 可能存法线分量 | 四通道线性独立，不按透明或普通 RGB 法线处理 |
| `scalar_data` | AO 等数值 | linear，不做颜色 gamma |

manifest 每项显式给 `file`、`role`、`alpha_semantics`、`color_space`。颜色只取 fixed_rgb／opacity，N 为 packed_data，AO 为 scalar_data；数据纹理必须 linear。preview material 也须声明绑定，不给全车静默套一组 Alpha 策略。

`_n` 文件名不证明各分量的含义。核对实际 shader、解码资源与当前预览实现，保留已验证值；颜色跨旋转岛迁移成功不证明切线法线方向正确。N／AO 与颜色分开处理，不能把原作者材料等同本车原厂材料。

EMBT 储物网格 `embt_alpha` 的颜色 Alpha 真正控制裁切；固定装甲颜色图可以全零 A，packed N 的 A 又有数据意义。对网格改 RGB 时先保留轮廓，再核对最终颜色与阴影。混合图集逐项确认，不将车体材质参数批量施加到炮塔／炮管／网格。

无做旧应同时去掉 C 中的掉漆残影和材料中的磨损影响；结构焊缝、AO、橡胶与网格身份独立保留。微颗粒是另一个开关，没有用户要求与实际观察就不开。禁止靠统一噪点或全图压平 N 伪装成干净漆面。

最终 DDS 检查头、格式、资源数、BLK 引用、尺寸和完整 mip 到 1×1；读回顶层与关键 mip。RGBA8 精确基线与 BC3 有损候选分别记录。小字、细线、透明边界在目标距离实际采样检查；邻岛扩色不得污染别的有效岛。新车输出仍需模型与游戏验证。
