# Skill与素材包独立分发

`wt-style-charcoal-industrial`是Skill，包含规则、工具和文字模板；`wt-charcoal-industrial-assets`是独立素材包，包含18项可用图形/材质、目录和必要AZUR范本图。二者各自有版本、文件清单和ZIP，也可以放进同一压缩包。合包内仍是两个并列目录，不把素材复制到Skill里面。

## 定位与使用

并排解压后，Skill自动读取旁边的素材目录。自定义位置用环境变量`WT_CHARCOAL_ASSETS`指定，或对定位/验证命令使用`--assets`。显式路径或显式版本不正确时直接报错，不偷偷选其他目录。

```text
python -B scripts/asset_pack.py locate
python -B scripts/asset_pack.py verify --assets "独立素材包目录"
python -B scripts/verify_release.py --assets "独立素材包目录"
```

定位命令返回实际`catalog.json`绝对路径。原有compose计划继续用`catalog`及`catalog_sha256`锁定这个外部目录，也可使用`asset-pack:catalog.json`；每项素材的文件路径相对素材目录。选材检查仍核对SHA256、用途、车型/设备语义、细线和字高，不因拆包放宽。

Skill单独安装后可阅读规则、设计构图、处理用户提供的素材、生成参数材质；取用现成素材及进行AZUR图像对照时需要独立素材包。包缺失时说明缺少哪项输入，不假装已读到，也不把旧安装目录里的同名图片当本版素材。无需把素材包放入skills目录，只要显式路径可访问即可。

## 素材适配

合适的素材直接拿，不强制重新生图；车型不同由AI按真实部位自主调整字、布局、数量、比例、颜色和材质。改制文件保存在本车工程，不覆盖母版素材包。使用包内原版就记录原素材身份，改制后记录本车新文件和母版来源。

三套防滑素材保留完整PNG及原生分辨率，C/coverage/normal-rgb/packed-n均可直接使用；N.A为数据通道，不是透明度。历史研究裁片、未核实AI元素、旧案例图库和失败构建留在研发区，不属于这两个发布包。
