# 工具索引与默认值隔离

安装包中的 `scripts/` 由仓库共用飞机工具源按原字节组装，包括回归测试；身份记录在包根的 `tool-provenance.json`。调用必须以本包文件为准，不从原安装 Skill 隐式导入。外部 runtime、字体、原图、解码器和游戏均不随包分发。

Python 最低要求来自原工具为 3.10+。基础扫描与 Composa 客户端使用标准库；大部分图像工具需要 Pillow、NumPy；几何光栅需要 Numba；部分分区与分析需要 SciPy；参考测量另需 OpenCV；下载需要 requests。先检查已安装环境，缺失时明确依赖，不声称已运行；每次验证的具体 runtime、依赖版本和结果记录在执行任务中。

## 通用工程入口

| 工具 | 功能与边界 |
|---|---|
| `inspect_skins.py scan/preview` | BLK、头部、哈希与可选解码；无游戏资源数据库 |
| `compare_skin.py` | 基线与输出的通道、覆盖区统计；UV mask 必须真实匹配 |
| `build_skin.py` | 精确资源替换、保护通道、TGA/BLK/ZIP 与事务收据 |
| `dds_variant.py` | 已验证 TGA 包的独立 DDS/mip 变体，依赖固定 texconv |
| `artifact_io.py` | 内部事务 I/O 模块，无 CLI；由同目录脚本导入 |
| `surface_preview.py prepare/render/bake` | 原 UV 静态几何、配对 guides 与投射；prepare 需外部解码器 |
| `scene_preview.py prepare/render` | 多材质静态场景；材质解释与透明代理有限制 |
| `airframe_setup.py map/frames` | 按现有飞机场景列岛、坐标与局部拟合框架 |
| `uv_frame.py` | 以明确基准拟合 UV 局部坐标，检查误差 |
| `vector_paint.py` | 几何上求值、独立层与 SVG；设计内容由任务提供 |
| `surface_map.py` | 表面、遮挡、共享与接缝诊断；frame 图表需另外看模型 |
| `detail_sheet.py` | 实际输出 1:1 与明确密度的参考并排；历史机型密度示例不继承 |
| `composa_mcp.py` | 实时 schema、顺序调用与恢复证据；不自动开权限 |
| `fetch_asset.py` | 下载已选公开图片并保存来源；不替用户选素材或判断许可 |
| `atlas_palette.py` | 指定区域色族统计；需说明测量分母 |
| `style_board.py` | 同尺寸视觉并排，不进行自动审美认可 |
| `replica_measure.py` | 参考轮廓、色彩、图案与图标配准测量；不把推测当作者原流程 |
| `replica_check.py` | 实际使用纹素、分组／整机比较、计划到设计转换 |

## 仅按明确意图启用

| 工具／模式 | 必须由任务／风格提供的条件 |
|---|---|
| `design_lint.py` | 是既有特定审美启发式，检查字体、配色、线型、人物等。**不是通用生产硬闸门**；只有规则逐条适用时才采纳，不能因纯黑白、多色、粗线等直接判通用失败 |
| `airframe_setup.py clean` | 原图阈值分类与 `--coat`；默认 `#333334` 不代表通用底色，自动分类要实际检查 |
| `airframe_setup.py shares` | 固定 dark/signature/tint/white 色族定义，仅适合相符的风格实验；不能为任意风格评分 |
| `coat_material.py` | 明确的整片重涂目标、通道证据、平法线值和结构保留量；不能裸用默认参数 |
| `structure_layer.py` | 结构提取的目标与通道；默认颜色、opacity、channels 均须核对 |
| `panel_lines.py trace/apply` | 任务明确需要重建面板线；不规定所有风格有／无面板线 |
| `arrangement.py` | 任务明确采用构造线切格／序列图形；图形 grammar 是能力，不是默认构图 |
| `art_cutout.py` | 输入确为可按纯背景色分离的素材，阈值与保留细节已核对；检查图的深色底不是设计推荐 |
| `finish_preview.py` | profile 符合选定近似模型，只用于限定条件下比较 |

源码与 `--help` 仍包含历史名称、配色示例和审美文案，因为本次保留字节用于回归。那些内容不覆盖本包入口、当前任务、风格规范和 profile；后续删除或参数化需以独立代码变更和回归完成。

## 验证

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m unittest discover -s "$SkillRoot/scripts" -p "test_*.py" -v
```

Numba 缓存由现有脚本默认放系统 TEMP，也可显式设置 `NUMBA_CACHE_DIR` 到会话临时目录。不要在包内产生 `__pycache__` 或其他缓存。回归通过只证明已覆盖的工程行为，无法替代真实模型、游戏与用户风格审查。
