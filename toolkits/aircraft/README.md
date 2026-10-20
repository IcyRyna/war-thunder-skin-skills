# 飞机工程工具

`scripts/` 是飞机工程脚本和回归测试的唯一维护来源。原通用飞机流程与 Akamywek 独立包中的 48 个脚本逐文件相同；仓库仅保留这一份，组装各独立安装包时再放入包内 `scripts/`。

这里保留原有行为与历史默认值。通用构建入口通过任务设计和 vehicle profile 限定工具的使用，不能把历史审美参数当成所有风格的规则。地面载具仍使用自己的工具，不从本目录推断兼容性。

从仓库根运行回归：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m unittest discover -s toolkits/aircraft/scripts -p "test_*.py" -v
```

运行需要 Python 3.10+，以及对应测试使用的 Pillow、NumPy、Numba、SciPy、OpenCV 和 requests。外部解码器、编辑器、游戏和 DDS 编码工具不随源码分发。测试结果属于具体运行记录，不代表真实载具、视觉或游戏验收通过。
