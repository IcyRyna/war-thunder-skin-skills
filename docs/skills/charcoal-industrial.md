# 炭灰工业涂装 · 0.1.6

以勒克莱尔AZUR为第一构成范本，面向War Thunder地面载具：三档主灰、大几何与不同尺度蜂窝、车型身份、顶部完整警示、车尾暖色呼应，以及观瞄、机枪、炮管、橡胶和原皮小件的材质分工。

## 两个独立产物

| 下载 | 大小 | 内容 |
|---|---:|---|
| [Skill安装包](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-style-charcoal-industrial/v0.1.6/wt-style-charcoal-industrial-v0.1.6.skill.zip) | 391.45 KB | 规则、工具、模板；不包含生产图片 |
| [独立素材包](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-style-charcoal-industrial/v0.1.6/wt-charcoal-industrial-assets-v0.1.6.zip) | 72.38 MB | 18项可直接用/改制的素材、完整高清材质、必要AZUR范本图 |
| [一起压缩的合集](https://github.com/IcyRyna/war-thunder-skin-skills/releases/download/wt-style-charcoal-industrial/v0.1.6/wt-charcoal-industrial-bundle-v0.1.6.zip) | 72.77 MB | 两个并列目录，内容与单独下载一致 |

[发布说明与文件校验](https://github.com/IcyRyna/war-thunder-skin-skills/releases/tag/wt-style-charcoal-industrial/v0.1.6)。历史研究图库、原车裁片、未核实AI元素和过程记录不在这两个发布包里。此前“Skill里包含全部素材”的说明自0.1.6起不再适用。

## 安装与素材定位

将`wt-style-charcoal-industrial`放入技能目录，调用`$wt-style-charcoal-industrial`。素材包是独立目录`wt-charcoal-industrial-assets`；两者并排解压可自动识别，素材放在别处则用`WT_CHARCOAL_ASSETS`指定其目录。

```text
python -B scripts/verify_release.py
python -B scripts/asset_pack.py locate
python -B scripts/verify_release.py --assets "独立素材包目录"
```

Skill单独安装仍可读取规则、设计构图、处理自备素材并生成参数材质。取用现成图形或对照AZUR范本图时，连接独立素材包。缺包会明确报错，不能默默借用另一版本的图片。

运行环境为Python 3.12；依赖见Skill内`requirements.txt`，交互预览的额外依赖见`requirements-preview.txt`。实际涂装制作使用已连接的Composa/编辑器；Blender可用时实际核验模型与最终DDS。

## 素材如何使用

合适的图形可以直接拿。车型不同，由AI根据真实板形、原生UV、文字用途和整车构图调整布局、颜色、图案密度与材质；新子版放当前工程，保留原母版。无需每次重画或生图，也不能仅改目录标签就把不适用文字判成合格。

三套高清防滑保留完整的color、coverage、normal-rgb、packed-n及原生分辨率。PNG像素和数据通道未有损改写，N.A不作透明度处理。18项制作素材及三张核心范本图均保留本轮审定的原始媒体字节。

![AZUR构成范本](../../assets/charcoal-industrial/references/azur-current-v29/hero-front.png)

## 本版改进

- 13项部位明确主装饰、副装饰、真实材质和原皮细节的职责；完整板面不会因遮挡缩成角落。
- 固定真实源面和共享使用者；整面改局部、缩小目标面组、零像素比较或六方向全不可见不能作为完成证据。
- 视觉检查绑定实际渲染回执与输出图片；只刷新声明中的DDS哈希、沿用旧图会被拒绝。
- 真实编辑器保存/复制重开、DDS各级mip、原生模型与通道保护分别核验。
- Skill与素材的身份、版本、目录、哈希和安装路径分别验证；素材可以与Skill合包，但不会装进Skill目录。

## 验证范围

291项单元/集成回归通过；独立解压验证覆盖Skill单独使用、缺素材包、并排目录和任意素材路径。18项素材目录与三套四图防滑检查通过。A7HU既有副本完成13项部位局部审计，六份真实编辑器工程、13张DDS/149级mip及完整顶部、首下字标、支架、火控和原皮细节修复有实际记录。

这些结果不表示未见车型独立制作、旧工程完整schema3迁移或新游戏实装已经完成；具体作品美术认可仍由用户判断。A7HU作品不随本次Skill发布上传。

原作研究来源：[Fying_ / WT Live 1192186](https://live.warthunder.com/post/1192186/en/)。自行编写的代码与指令沿用仓库MIT许可；第三方参考与游戏资源保留各自范围，见[许可说明](../licensing.md)。
