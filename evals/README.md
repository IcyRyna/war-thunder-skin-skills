# 研究与评测检查

`checks/workflow_check.py` 校验研究清单中的文件身份、输入隔离、实验对应关系和评价记录。完整字段与状态语义见 [CONTRACT.md](CONTRACT.md)。

从仓库根运行标准库测试：

```powershell
python -B -m unittest discover -s evals/tests -p "test_*.py" -v
```

测试只创建并清理合成临时夹具。结构有效、工具回归、视觉评价、游戏验证和用户审查是不同结论；测试通过不证明任何真实作品或 Skill 已通过其余检查。
