# 给 AI 的本地预览入口

用户在制作前应明确告知助手：**可以使用此本地工作台预览模型与检查涂装**，并提供工具的完整解压路径与战雷安装目录。此文档描述工具接口；具体操作范围仍以用户当前请求为准。

先双击 `启动工作台.cmd` 或运行下列命令，首次自动下载固定依赖。命令均从工具解压目录执行，PowerShell 中路径带空格时保留引号：

```powershell
& .\runtime\python.exe -B -X utf8 .\launcher.py --check
& .\runtime\python.exe -B -X utf8 .\preview.py doctor
& .\runtime\python.exe -B -X utf8 .\launcher.py --game-dir 'D:/Games/War Thunder' --no-browser
```

启动器输出本机 URL，也将本次 URL / PID 写入工具目录的 `runtime/session.json`。用助手自己的浏览器工具打开这个 URL；服务仅监听 127.0.0.1。`--no-browser` 适合 AI 的后台进程，不弹浏览器或目录选择框；需要导入涂装时先用 `--game-dir` 指定真实安装位置。停止自身启动的服务可用 Ctrl+C。

需要直接初始化准确车型时，先从游戏模型索引确认内部 ID，再调用：

```powershell
& .\runtime\python.exe -B -X utf8 .\preview.py init --vehicle leclerc_azur --game-dir 'D:/Games/War Thunder' --out 'D:/WT-Work/leclerc-preview' --max-texture 1024
& .\runtime\python.exe -B -X utf8 .\launcher.py --scene 'D:/WT-Work/leclerc-preview' --game-dir 'D:/Games/War Thunder' --no-browser
```

`leclerc_azur` 是示例，必须换成目标车型真实 ID。`init` 从安装文件夹读取模型与纹理，无需启动游戏客户端。完整参数见 `preview.py --help`、`skin_import.py --help` 与 README。也可在网页导入用户的 ZIP / 已解压文件夹，按 BLK 与实际模型索引自动匹配车型。

检查至少覆盖整车斜前、两侧、顶部与后方，定位装饰与接缝；切换反射/凹凸，确认材质表现。模型显示清晰度与编辑画布独立设置，按机器性能选择 512–4K。使用真实模型与原生 UV，保留新增装饰和区域改色的独立图层，便于用户人工校准。已合并旧图不能据此声称恢复了原图层。

`project.py` 可将 AI 的图层计划打包成可编辑工程；使用前阅读 `project.py --help` 及 README 的图层契约。保存工程后再导出颜色贴图。当前工作台导出颜色 PNG / ZIP，不直接生成完整游戏 DDS/BLK，不改 N/AO；最终游戏生产仍按对应车型的已验证材质契约完成。
