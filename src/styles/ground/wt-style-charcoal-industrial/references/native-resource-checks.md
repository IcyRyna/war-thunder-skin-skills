# 原生资源与导出门槛
游戏资源文件名、DynModel 资源名和单位配置名不保证相同。A6HEL 本轮分别为 germ_leopard_2a6_hel.grp、leopard_2a6_hel、il_leopard_2a6_hel。只用原生资源；旧涂装不是缺失输入的替代。

Gaijin DDSx Header 字段顺序是 w,h，且存在矩形贴图、mip 次序标志与基础包依赖。`ddsx_top.decode_top` 接收明确已解压 payload 和原32字节头，支持本轮实测 BC 纹理矩形尺寸；拒绝未满足的 paired-base、体积/数组或长度不符。以独立解码器检查尺寸与块方向。来源：https://raw.githubusercontent.com/GaijinEntertainment/DagorEngine/main/prog/engine/sharedInclude/3d/ddsxTex.h 。提取器必须辨别 `$hq` 资源，不能因为名称匹配先拿低分辨率条目。

全 UV 中性底漆包括小金属件、岛边/留边与背面。透明装饰 Alpha、固定 C 覆盖 Alpha、N 数据 Alpha 分别处理。固定漆面仅允许已验证 shader；N 的修改按任务声明：同材质仅调粗糙度时可以只改R；覆盖为新漆面则应复核B金属度与G/A强度，使用显式paint mask并记录改变的通道。保护区保持原字节。AO顶层默认不改。无损 BGRA8 导出按声明语义重新生成 mip；不能声称新的 mip 链与原 DDS 全文件相同。

本试点 C 为 nativeRGB 的2倍采样尺寸，保留目标原生机械结构；上采样不恢复缺失细节。BLK 所有颜色 replace 块转换为固定 set_tex/camo_skin_tex；每级读回，最终 DDS 再绑定离线模型。
