# 载具适配契约

`schema/vehicle-profile.schema.json` 定义设计语义到实际贴图资源、区域、坐标与材质通道的映射。profile 供执行者校验并翻译成工具参数；现有工程 CLI 不会自动读取或执行 profile。

`examples/synthetic/` 是人工构造的最小工程样本，没有真实载具映射或游戏通过声明。构建独立 `wt-skin-build` 包时，schema 进入 `references/vehicle-profile.schema.json`，样本进入 `examples/synthetic/`；样本 README 中的命令从生成的包根运行。

真实载具 profile 应与原始模板、证据和适用范围一起维护。不要把某个机型或坦克的坐标直接当成另一个载具的通用参数。
