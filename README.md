# LuckyCAT_EtherCAT_Master

**注意**：该项目全由大肥鱼（DeepSeek-V4.1-Flash）编写、调试和验证，切勿将项目用于生产环境。

面向 **LuckyCAT（HPM5E31）** 开发板的 EtherCAT 主站参考工程：CherryECAT 协议栈 +
CiA402 周期同步速度（CSV）控制 + SSD1306 OLED 状态显示 + shell 调试命令行。

工程基于 HPMicro **HPM SDK 1.13.0**，可直接用 `cmake + ninja + RISC-V GCC` 构建，并附带
一套 **PC 端虚拟 EtherCAT 从站**，没有伺服驱动器也能把“扫描 → PREOP → SAFEOP → OP →
CiA402 使能 → 速度给定 → 位置反馈”整条链路跑通并验证。

> English summary: an EtherCAT master reference for the HPM5E31 based LuckyCAT board
> (CherryECAT + CiA402 CSV + OLED + shell). Includes a Python virtual CiA402 slave so the
> complete master/slave chain can be validated on a desk without a real drive.

---

## 1. 功能特性

| 功能 | 说明 | 状态 |
| --- | --- | --- |
| EtherCAT 主站 | CherryECAT，ENET0 + MII + JL1111，1 个网口 | ✅ |
| 总线扫描 | 自动分配站地址、读取 SII、配置 SM/FMMU、PREOP/SAFEOP/OP | ✅ |
| CiA402 CSV | 控制字/状态字状态机、目标速度斜坡、位置反馈 | ✅ |
| PDO 映射 | 自动解析从站 PDO 偏移，缺省回退到 `0x6040/0x60FF` + `0x6041/0x6064` | ✅ |
| DC 分布式时钟 | 从站支持时启用，不支持时自动跳过 | ✅ |
| OLED 状态 | 128×64 SSD1306，软件 I2C（PD6/PD7） | ✅ |
| Shell 命令 | `ethercat`（CherryECAT 内置）、`motor`（本项目） | ✅ |
| 按键控制 | K1 启停、K2 循环切换目标速度 | ✅ |
| 故障恢复 | 链路断开不崩溃，链路恢复后自动重新扫描/启动 | ✅ |
| PC 虚拟从站 | Python + Npcap，模拟 ESC/CiA402，含离线单元测试 | ✅ |

## 2. 硬件与接线

- **MCU**：HPM5E31xPBx（RISC-V，1 MB QSPI NOR）
- **主站网口**：板上丝印 **ECAT OUT**（P1），PHY 为 JL1111（MDIO 地址 2）
- **从站网口**：板上丝印 **ECAT IN**（P0），PHY 为 JL1111（MDIO 地址 1）
- **串口**：UART0，PA00/PA01，115200 8N1
- **OLED**：SSD1306 128×64，软件 I2C，SCL=PD7，SDA=PD6
- **按键**：K1=PA2，K2=PA3（低有效）
- **LED**：PA22（低电平点亮）

> ⚠️ ENET0 的 MII 引脚（PF02~PF14）与片上 ESC 的 port1 **完全复用**，因此主站只能使用
> **ECAT OUT** 口；同一时刻 ENET0 与 ESC port1 不能同时工作。详见
> [docs/02-hardware.md](docs/02-hardware.md)。

## 3. 目录结构

```
LuckyCAT_EtherCAT_Master/
├── apps/LuckyCAT_EtherCAT_Master/software/   应用层（main / ecat_app / OLED）
├── boards/hpm5e31_LuckyCAT/              板级支持（时钟、引脚、PMP、ENET）
├── middleware/cherryecat/                CherryECAT 协议栈 + HPMicro 移植层
├── components/enet_phy/                  PHY 公共头文件（沿用 hpm_apps）
├── tools/                                构建、烧录、串口、虚拟从站脚本
├── tests/                                离线单元测试
├── docs/                                 设计/硬件/构建/测试/排障/来源说明
└── CMakeLists.txt                        最小 hpm_apps 风格工程根
```

## 4. 快速开始

### 4.1 环境

| 依赖 | 版本/说明 |
| --- | --- |
| HPM SDK | **1.13.0**（`sdk_env` 目录中的 `hpm_sdk`） |
| 工具链 | `rv32imac_zicsr_zifencei_multilib_b_ext` GCC |
| 构建 | CMake ≥ 3.13、Ninja |
| 调试 | OpenOCD（SDK 自带即可）、CMSIS-DAP 调试器 |
| 测试脚本 | Python 3.8+，虚拟从站需要 Npcap |

```bash
export HPM_SDK_BASE=/path/to/sdk_env/hpm_sdk
export GNURISCV_TOOLCHAIN_PATH=/path/to/sdk_env/toolchains/rv32imac_zicsr_zifencei_multilib_b_ext-<host>
```

Windows PowerShell：

```powershell
$env:HPM_SDK_BASE = "D:\path\to\sdk_env\hpm_sdk"
$env:GNURISCV_TOOLCHAIN_PATH = "D:\path\to\sdk_env\toolchains\rv32imac_zicsr_zifencei_multilib_b_ext-win"
```

### 4.2 构建

```bash
./tools/build.sh            # Git Bash / Linux
./tools/build.sh clean      # 干净重建
```

```powershell
.\tools\build.ps1
.\tools\build.ps1 -Clean
```

产物：

```
apps/LuckyCAT_EtherCAT_Master/software/build/output/LuckyCAT_EtherCAT_Master.elf
apps/LuckyCAT_EtherCAT_Master/software/build/output/LuckyCAT_EtherCAT_Master.bin
```

### 4.3 烧录与串口

```bash
./tools/openocd.sh                  # 终端 1：常驻调试服务（127.0.0.1:4444）
python tools/flash.py               # 终端 2：烧录 + 校验 + 复位运行
python tools/serial_monitor.py --port COM5 --reset --seconds 8
```

没有指定 `--port` 时会自动选择第一个 USB 串口；`--list` 可列出全部串口。

### 4.4 运行

上电后串口输出：

```
==============================================
 LuckyCAT_EtherCAT_Master v1.0.0
 HPM5E31 + CherryECAT, CiA402 CSV motor control
==============================================
Initializing EtherCAT master (ENET0 / MII / JL1111)...
EtherCAT master initialized, scanning bus...
```

OLED 同步显示链路、从站状态、控制字/状态字、目标速度、实际位置、WKC 与发送状态。

## 5. 使用说明

### 5.1 Shell 命令

| 命令 | 说明 |
| --- | --- |
| `motor start` | 请求 CiA402 使能（等价 K1） |
| `motor stop` | 撤销使能 |
| `motor speed <n>` | 设置目标速度（斜坡限幅，±2000） |
| `motor status` | 打印主站/从站/PDO/CiA402/PHY/发送统计 |
| `motor reset` | 停止并清零目标速度 |
| `motor cycle [us]` | 查看或设置 PDO 周期（需在启动前设置） |
| `motor selftest` | PHY 内部回环自检（验证 MII 引脚通路） |
| `ethercat` | CherryECAT 内置命令（扫描、SDO、PDO 等） |

### 5.2 按键

- **K1**：切换运行/停止（`motor start` / `motor stop`）
- **K2**：目标速度循环 0 → 30 → 60 → 120 → 240 → 0

### 5.3 周期时间

默认 **4000 µs**，是为了兼容 PC 端 Python 虚拟从站的 1~2 ms 回包抖动。
接真实伺服时建议改为 1000 µs：

```bash
motor cycle 1000     # 启动前设置
```

或修改 `apps/LuckyCAT_EtherCAT_Master/software/src/ecat_app.c` 中的 `APP_CYCLE_TIME_US`。

## 6. 验证

完整测试方法见 [docs/05-test-guide.md](docs/05-test-guide.md)，分三层：

1. **离线单元测试**（无需硬件）：
   ```bash
   python tests/run_tests.py
   ```
2. **PHY 回环自检**（只需板子）：`motor selftest`，期望 `PASS`。
3. **主从联调**（板子 + PC）：
   ```bash
   python tools/ecat_slave_sim.py --list
   python tools/ecat_slave_sim.py
   ```
   板子 `ECAT OUT` 接交换机/路由器，PC 同网段。期望板子输出：

   ```
   master  : started, slaves 1, link up
   slave0  : state OP, AL 0x0000
   cia402  : cw 0x000F, sw 0x0627, run 1
   pdo     : cycles ..., wkc 3/3, size 16 (o8 i8)
   tx      : queued ..., done ..., recycled ..., stalled 0
   ```

本项目实测记录（PC 虚拟从站）：

| 项目 | 结果 |
| --- | --- |
| 链路 | 100 Mbps 全双工 |
| 扫描 | 1 个从站，站地址 1001 |
| 状态 | INIT → PREOP → SAFEOP → OP |
| PDO | 16 字节（8 出 / 8 入），WKC 3/3 |
| CiA402 | `cw=0x000F`，`sw=0x0627`（Operation enabled + target reached） |
| 运动 | `motor speed 1000` 后位置持续递增 |

## 7. 关键实现说明

1. **`board_init_pmp()` 不能是空函数**：必须把 `.noncacheable` 段配置为 non-cacheable，
   否则 ENET 的 DMA 描述符与 CPU 看到的内容不一致，表现为“帧发不出去 / 描述符 OWN 不清零”。
   这是本工程从“完全不能发”到“正常通信”的根因。
2. **HPM5E31 的 TX 描述符 OWN 位不会由硬件清零**：移植层用发送完成中断（TI）回收描述符，
   软件维护环形队列尾指针。
3. **ENET RX 只接收 0x88A4**：接在共享局域网时避免把 ARP/DHCP 当 EtherCAT 解析。
4. **SII 布局差异**：CherryECAT 的 `sii_image` 是 `uint16_t *` 但按字节偏移读头，
   写虚拟从站时 `mailbox_protocols` 要放在字节 0x38、分类目录在字节 0x80。
5. **PDO 回调中的 WKC**：回调发生在 `master->actual_working_counter` 赋值之前，
   应直接读 `pdo_datagram.working_counter`。

细节与更多踩坑见 [docs/03-architecture.md](docs/03-architecture.md) 和
[docs/06-troubleshooting.md](docs/06-troubleshooting.md)。

## 8. 代码来源与改动

本工程是在以下项目基础上整理、修改而来，来源与改动清单见
[docs/07-provenance.md](docs/07-provenance.md)：

| 来源 | 用途 |
| --- | --- |
| `LuckyCAT_SoftWare-main`（LuckyCAT 厂商示例） | 板级文件（`board.c/h`、`pinmux`、OpenOCD cfg、yaml）、OLED 驱动、ENET/PHY 硬件信息 |
| `hpm_apps-1.11.1`（HPMicro 应用仓库） | 应用骨架、CherryECAT 中间件、`components/enet_phy` |
| `hpm_sdk 1.13.0`（HPMicro SDK） | 构建系统、驱动、FreeRTOS、JL1111 驱动、cherrysh |

相对上游的主要改动：

- 板级：实现 `board_init_pmp()`、新增 `board_init_enet_mii_clock()`、屏蔽 ESC port1 引脚占用；
- 移植层：ENET 固定 MII、JL1111 切 MII、发送描述符软件回收、RX EtherType 过滤；
- 应用层：CiA402 CSV 状态机、PDO 偏移解析、DC/CoE 能力自适应、OLED UI、shell 命令；
- 工具：虚拟从站、离线测试、跨平台构建/烧录/串口脚本。

板载 ESC（SSC CiA402 从站）自测代码**未纳入本发布版**：其 EEPROM 仿真未跑通，且仅在
单板自测时有用，相关结论记录在 [docs/06-troubleshooting.md](docs/06-troubleshooting.md)。

## 9. 已知限制

- 仅支持 1 个主站网口（ENET0/MII），不支持冗余；
- 默认 PDO 映射按 CiA402 CSV 的常见布局回退，若从站 PDO 不同需确认 `ec_slave_table.c`；
- 虚拟从站不是硬实时，不能用于验证 1 ms 周期抖动或 DC 同步精度；
- 板载从站自测未完成（EEPROM 仿真），接真实伺服用不到。

## 10. 许可证

本项目新增代码采用 **Apache License 2.0**，详见 [LICENSE](LICENSE)。

仓库中包含的第三方文件保留其原许可证，主要是：

- CherryECAT：Apache-2.0；
- HPM SDK / hpm_apps 示例骨架、LuckyCAT 板级文件、`components/enet_phy`：BSD-3-Clause；
- 厂商 OLED 示例驱动：随板级示例提供。

逐文件说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与
[docs/07-provenance.md](docs/07-provenance.md)。

## 11. 发布包

发布压缩包 `LuckyCAT_EtherCAT_Master_v1.0.0.zip` 包含：

```
LuckyCAT_EtherCAT_Master/
├── ...                    源码（与 git tag v1.0.0 一致）
└── firmware/
    ├── LuckyCAT_EtherCAT_Master.elf
    ├── LuckyCAT_EtherCAT_Master.bin
    └── SHA256SUMS.txt
```

预编译固件对应 tag `v1.0.0`，烧录方式：

```bash
python tools/flash.py --elf firmware/LuckyCAT_EtherCAT_Master.elf
```

## 12. 变更记录

见 [CHANGELOG.md](CHANGELOG.md)。
