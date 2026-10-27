# 快速开始

目标：从零把工程编译、烧录、跑起来，并用 PC 虚拟从站验证完整链路。

## 0. 准备

| 项目 | 要求 |
| --- | --- |
| HPM SDK | 1.13.0（`sdk_env` 中的 `hpm_sdk`） |
| 工具链 | `rv32imac_zicsr_zifencei_multilib_b_ext` |
| 开发板 | LuckyCAT（HPM5E31），板载 CMSIS-DAP |
| 网线 | ECAT OUT → 交换机/路由器 → PC（虚拟从站） |
| PC 软件 | Python 3.8+、Npcap（虚拟从站） |

环境变量（二选一，按自己 SDK 的实际位置修改）：

```bash
# Git Bash / Linux
export HPM_SDK_BASE=/path/to/sdk_env/hpm_sdk
export GNURISCV_TOOLCHAIN_PATH=/path/to/sdk_env/toolchains/rv32imac_zicsr_zifencei_multilib_b_ext-<host>
```

```powershell
# Windows PowerShell
$env:HPM_SDK_BASE = "D:\path\to\sdk_env\hpm_sdk"
$env:GNURISCV_TOOLCHAIN_PATH = "D:\path\to\sdk_env\toolchains\rv32imac_zicsr_zifencei_multilib_b_ext-win"
```

## 1. 构建

```bash
./tools/build.sh
```

或：

```powershell
.\tools\build.ps1
```

成功时输出：

```
BUILD OK
  elf: .../build/output/LuckyCAT_EtherCAT_Master.elf
  bin: .../build/output/LuckyCAT_EtherCAT_Master.bin
```

首次构建会生成 `build/output/` 下的 `.elf/.bin/.map/.asm`。

## 2. 启动调试服务并烧录

终端 1：

```bash
./tools/openocd.sh
```

终端 2：

```bash
python tools/flash.py
```

期望：

```
** Programming Started **
** Programming Finished **
** Verified OK **
** Resetting Target **
FLASH OK: .../LuckyCAT_EtherCAT_Master.elf
```

## 3. 看启动日志

```bash
python tools/serial_monitor.py --port COM5 --reset --seconds 8
```

（`--port` 可省略，脚本会自动选择 USB 串口；`--list` 查看全部串口。）

正常输出：

```
OLED: I2C OK (ack errors 0)
==============================================
 LuckyCAT_EtherCAT_Master v1.0.0
 HPM5E31 + CherryECAT, CiA402 CSV motor control
==============================================
Initializing EtherCAT master (ENET0 / MII / JL1111)...
ENET: PHY P0 BMSR = 0x...., P1 BMSR = 0x786D
ENET: link up (BMSR = 0x786D)
EtherCAT master initialized, scanning bus...
```

OLED 显示：

```
LuckyCAT EtherCAT
LNK:UP  SCANNING..
CW:0000 SW:0000
TGT:      0
POS:      0
VEL:      0/s
WKC:0/0   TXE:0
TX OK, NO SLAVE
```

没有从站时这是正常状态。

## 4. 启动 PC 虚拟从站

先把网线接好：`LuckyCAT ECAT OUT` → 交换机/路由器 → PC 网口。

```bash
pip install -r tools/requirements.txt      # 只有串口工具需要 pyserial
python tools/ecat_slave_sim.py --list      # 确认能看到 PC 网卡
python tools/ecat_slave_sim.py
```

脚本启动后：

```
== 虚拟 EtherCAT 从站 ==
网卡: Intel(R) Ethernet Connection ...
MAC : xx:xx:xx:xx:xx:xx
SII : VID=0x00000F1C, SM0=0x1100 SM1=0x1180, PDO 8+8 B
等待主站扫描...
发现主站 MAC: xx:xx:xx:xx:xx:xx
```

板子侧复位（或等待自动重扫）：

```bash
python tools/serial_monitor.py --port COM5 --reset --seconds 3
```

然后：

```
motor status
```

期望：

```
master  : started, slaves 1, link up
scan    : done 1, phase 2, wkc_exp 3
sii     : VID 0x00000F1C PID 0x0000CA40 rev 0x00010000, sm 4, mbx 0x0000
slave0  : state OP, AL 0x0000
cia402  : cw 0x0007, sw 0x0223, run 0
pdo     : cycles ..., wkc 3/3, size 16 (o8 i8) lwkc 3 sync 2
phy     : P0 BMSR 0x.... (link 1), P1 BMSR 0x786D (link 1)
tx      : queued ..., done ..., recycled ..., stalled 0
motion  : target 0, ramped 0, actual 0, pos ...
```

## 5. 使能与调速

```bash
motor start          # 请求使能，控制字 0x06 -> 0x07 -> 0x0F
motor status         # 期望 sw 0x0627，run 1
motor speed 1000     # 目标速度 1000
motor status         # pos 持续增加
motor stop           # 撤销使能，sw 回到 0x0223
```

按键同样可用：K1 启停，K2 循环 0/30/60/120/240。

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| `ECAT INIT FAILED / RETRY...` | 检查 ECAT OUT 是否插好、PHY 是否供电；看串口 BMSR 是否 link |
| `TX OK, NO SLAVE` | 从站没接或虚拟从站没起来 |
| `motor status` 中 `slaves 0` | 检查网线/交换机；确认虚拟从站绑定到正确网卡 |
| `wkc 0/3` | 周期太快，`motor cycle 4000` 后重启主站 |
| 烧录失败 | 先确认 OpenOCD 已启动、调试器未被占用 |

更多见 [06-troubleshooting.md](06-troubleshooting.md)。
