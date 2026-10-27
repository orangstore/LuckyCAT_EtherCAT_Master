# 测试方法

测试分四层，可单独执行，也可按顺序做完整验收。

| 层级 | 需要硬件 | 验证内容 | 预计耗时 |
| --- | --- | --- | --- |
| L0 构建 + 离线单元测试 | 无 | 代码可编译、SII/ESC/CiA402 模型正确 | 2 min |
| L1 PHY 回环自检 | 板子 | ENET0 MII 引脚、PHY、DMA 收发通路 | 1 min |
| L2 PC 虚拟从站联调 | 板子 + PC | 扫描、状态机、PDO、CiA402 全链路 | 10 min |
| L3 真实伺服 | 板子 + 伺服 | 真实驱动器的 CiA402、DC、周期性能 | 30 min |

---

## L0 构建与离线测试

```bash
./tools/build.sh
python tests/run_tests.py
```

期望：

```
Ran 16 tests in ...s
OK
```

覆盖内容：

- SII 头部在 CherryECAT 实际读取位置（VID/PID/revision/mailbox_protocols）；
- SII 分类目录位置、SM 数量与物理地址；
- 配置区校验和；
- BRD/APWR/FPRD/LRW 数据报与 WKC；
- AL 状态机 INIT→PREOP→SAFEPO→OP、非法请求忽略；
- EEPROM 读取长度与内容；
- CiA402 使能序列、状态字位、速度斜坡、快停。

产物检查：

```bash
ls -l apps/LuckyCAT_EtherCAT_Master/software/build/output/
# LuckyCAT_EtherCAT_Master.elf / .bin / .map / .asm
```

**通过标准**：构建无 error；单元测试全部 OK。

---

## L1 PHY 回环自检（单板）

目的：在没有任何从站的情况下验证 ENET0 的 MII 引脚、PHY 与 DMA 收发。

1. 板子正常上电（ECAT OUT 可插可不插网线）；
2. 串口执行：

```
motor selftest
```

3. 期望输出：

```
selftest: PHY loopback BMCR 0x3100 -> 0x7100, BMSR 0x786D
selftest: RX frames N -> N+1, DMA_STATUS 0x00660000 -> PASS
```

**判定**：

- `PASS`：MAC 发出的帧被 PHY 环回并被接收计数，MII 数据/时钟引脚正常；
- `NO FRAME`：检查 PF02~PF14 是否被 ESC port1 占用、PHY 是否 link、`board_init_pmp()` 是否生效；
- 该命令会短暂切换 PHY 回环，执行时链路会瞬断，属正常现象。

> 说明：该测试只验证 MAC↔PHY 通路，不验证网线对端。

---

## L2 PC 虚拟从站联调

### L2.1 准备

1. **接线**

   ```
   LuckyCAT ECAT OUT ──网线── 交换机/路由器 ──网线── PC 网口
   ```

   也可直连 PC。交换机对 EtherType `0x88A4` 透明转发，EtherCAT 帧是广播，
   PC 能收到；PC 回的单播帧按 MAC 表送回板子。

2. **安装 Npcap**（Windows）：<https://npcap.com>，安装时勾选 WinPcap 兼容模式。

3. **PC 网段**：无需 IP 配置（纯二层），但网卡必须处于“已连接”状态。

### L2.2 启动虚拟从站

```bash
python tools/ecat_slave_sim.py --list
python tools/ecat_slave_sim.py
```

参数：

| 参数 | 说明 |
| --- | --- |
| `--iface <关键字>` | 按描述选择网卡；缺省自动选第一块物理网卡 |
| `--verbose` | 逐条打印数据报 |
| `--quiet-pdo` | 不打印 PDO 变化 |

期望启动输出：

```
== 虚拟 EtherCAT 从站 ==
网卡: ...
MAC : ...
SII : VID=0x00000F1C, SM0=0x1100 SM1=0x1180, PDO 8+8 B
等待主站扫描...
```

### L2.3 复位板子并观察

```bash
python tools/serial_monitor.py --port COM5 --reset --seconds 10
```

虚拟从站侧应出现：

```
发现主站 MAC: ...
[ESC] station address = 1001
[ESC] AL -> PREOP
[ESC] AL -> SAFEOP
[ESC] AL -> OP
  CiA402: cw=0x0006 sw=0x0021 state=READY ...
```

板子侧 `motor status`：

```
master  : started, slaves 1, link up
scan    : done 1, phase 2, wkc_exp 3
sii     : VID 0x00000F1C PID 0x0000CA40 rev 0x00010000, sm 4, mbx 0x0000
slave0  : state OP, AL 0x0000
cia402  : cw 0x0007, sw 0x0223, run 0
pdo     : cycles N, wkc 3/3, size 16 (o8 i8) lwkc 3 sync 2
tx      : queued N, done N, recycled N-1, stalled 0
```

**通过标准**：

- `slaves 1`、`state OP`、`wkc 3/3`；
- `tx stalled = 0`，`queued` 与 `done` 持续增长；
- 虚拟从站无 `badlen` 增长。

### L2.4 CiA402 功能验证

```
motor start
motor status
```

期望：

```
cia402  : cw 0x000F, sw 0x0627, run 1
```

- `0x0627` = Operation enabled + remote + target reached；
- 虚拟从站侧状态变为 `OP_ENABLED`。

```
motor speed 1000
motor status
```

期望 `motion` 行：

```
motion  : target 1000, ramped 1000, actual ~1000, pos 持续增加
```

再执行：

```
motor speed 0        # 减速到 0，pos 停止
motor stop           # 撤销使能，sw 变回 0x0223
motor start          # 重新使能
```

**通过标准**：控制字随状态字正确迁移，速度斜坡无跳变，位置反馈单调变化，
`motor stop` 后 `sw` 回到 `0x0223`。

### L2.5 异常与恢复

1. **拔网线**：板子串口打印 `Detect link down`，不出现异常，OLED 显示 `LNK:DN`；
2. **重新插上**：主站自动重新扫描，`slaves 1`、`state OP` 恢复；
3. **关闭虚拟从站**：板子进入无线程可通信状态，但不死机，shell 仍可用；
4. **重新启动虚拟从站 + 板子复位**：恢复正常。

**通过标准**：任意顺序插拔/重启均不出现 `Exception occur!`，shell 始终可用。

### L2.6 周期调整

默认 4 ms。若想验证更小周期：

```
motor stop
motor cycle 2000
motor start
```

若 `wkc` 开始小于 3/3，说明 Python 回包来不及，改回 4000。

> 虚拟从站不是硬实时，最小可靠周期约 2~4 ms，取决于 PC 负载与网卡。

---

## L3 接真实伺服

1. 接线：`ECAT OUT` → 伺服 `ECAT IN`；伺服站地址由主站扫描自动分配；
2. 上电顺序：先伺服，后板子（或任意，主站会重扫）；
3. 周期改回 1 ms：

   ```
   motor cycle 1000
   ```

   然后复位板子（`motor cycle` 只在主站启动前生效）。

4. `motor status` 检查：

   - `sii` 行的 VID/PID 应为伺服厂商值；
   - 若伺服不在 `ec_slave_table.c` 中，会使用 fallback 映射并打印
     `(fallback mapping)`；
   - 若伺服支持 CoE，会打印 `operation mode set to CSV (9)`；
   - 若伺服支持 DC，`dc_assign_activate = 0x300`，否则自动关闭 DC。

5. 使能/调速同 L2.4。

**通过标准**：

- `state OP`、`wkc` 等于从站数（单轴为 3）；
- 使能后伺服无 fault，`sw` 的 bit2/bit3 正确；
- 速度给定后电机按预期转动，`pos` 反馈方向与速度一致；
- 1 ms 周期下 `cycles` 增长稳定，无 `tx stalled`。

### 若伺服 PDO 不是 0x1602/0x1A02

1. 在 `middleware/cherryecat/src/ec_slave_table.c` 增加该伺服的条目
   （VID/PID/REV + 操作模式 + SM/PDO 定义）；
2. 或修改 `ecat_app.c` 中的 `fb_out_entries` / `fb_in_entries` 与 `fb_syncs`，
   保持对象索引与位宽与实际一致；
3. 重新编译烧录。

---

## 实测记录（参考基线）

PC 虚拟从站、4 ms 周期、单从站：

| 项目 | 结果 |
| --- | --- |
| 链路 | 100 Mbps 全双工 |
| 从站数 | 1（站地址 1001） |
| 状态 | INIT → PREOP → SAFEOP → OP |
| PDO | 16 B（8 出 / 8 入），WKC 3/3 |
| CiA402 | `cw=0x000F`，`sw=0x0627` |
| 运动 | target 1000 → ramped 1000 → pos 持续递增 |
| 发送 | `stalled 0`，`queued/done/recycled` 同步增长 |
| 异常恢复 | 拔插网线、重启从站均不崩溃 |

---

## 测试脚本清单

| 脚本 | 用途 |
| --- | --- |
| `tests/run_tests.py` | 运行全部离线单元测试 |
| `tests/test_esc_model.py` | ESC/SII/CiA402 模型测试 |
| `tools/ecat_slave_sim.py` | PC 虚拟 EtherCAT 从站 |
| `tools/wpc.py` | Npcap 原始帧收发封装 |
| `tools/serial_monitor.py` | 串口监视/发送命令/复位 |
| `tools/flash.py` | 通过 OpenOCD 烧录 |
| `tools/openocd.sh` / `.ps1` | 启动调试服务 |
