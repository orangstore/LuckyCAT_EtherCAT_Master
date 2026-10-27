# 测试

## 运行

```bash
python tests/run_tests.py
```

或：

```bash
python -m unittest discover -s tests -v
```

不需要开发板、不需要 Npcap。

## 覆盖范围

`test_esc_model.py` 直接调用 `tools/ecat_slave_sim.py` 中的模型，验证：

- SII 头部在 CherryECAT 实际读取位置（VID/PID/revision/mailbox_protocols）；
- 分类目录在字节 0x80、SM 分类含 4 个 SM（索引 2/3 为 PDO）；
- 配置区校验和；
- BRD/APWR/FPRD/LRW 数据报、WKC 计数、逻辑寻址；
- AL 状态机迁移与非法请求过滤；
- EEPROM 读取的长度与内容；
- CiA402 使能序列、状态字位、速度斜坡、快停。

## 不在本目录的测试

- PHY 回环：板端 `motor selftest`；
- 主从联调：`tools/ecat_slave_sim.py` + 板子，步骤见 `docs/05-test-guide.md`。

## 新增测试

在 `tests/` 下新建 `test_*.py`，使用标准 `unittest`；需要访问工具模块时：

```python
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
```
