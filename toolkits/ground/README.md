# 地面工具 0.1.0

十个生产脚本在 `scripts/` 单一维护，按 `catalog.json` 装入独立 Skill。脚本身份及完整依赖见 [toolkit-lock](../../src/styles/ground/wt-style-endfield/toolkit-lock.json)。

```bash
python -m pip install -r toolkits/ground/requirements.txt
python -B -m unittest discover -s toolkits/ground/tests -v
```

真实预览另需 ModernGL 5.12.0 和 OpenGL 3.3；真实 DDS 转换测试需把 `WT_TEXCONV` 指向锁定 SHA-256 的 May 2026 texconv。缺少这些外部能力的测试明确跳过，不能写成通过。Composa 客户端仅用标准库，连接后读取实时 MCP schema。

默认自由构图、可选预设；包不包含整车自动生成器或旧跨车型重投影入口。
