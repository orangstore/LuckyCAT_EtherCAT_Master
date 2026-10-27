# 代码来源与改动说明

本工程不是从零编写，而是在 HPMicro 官方 SDK、官方应用仓库以及 LuckyCAT 板级示例的基础上
整理、修改、补充而来。本文件说明每个目录的来源、许可证与具体改动，便于后续维护和上游同步。

---

## 1. 来源总览

| 本仓库路径 | 上游来源 | 许可证 | 关系 |
| --- | --- | --- | --- |
| `boards/hpm5e31_LuckyCAT/` | `LuckyCAT_SoftWare-main/board/hpm5e31_LuckyCAT` | BSD-3-Clause（文件头） | 复制 + 修改 |
| `apps/LuckyCAT_EtherCAT_Master/software/inc/*.h` | `hpm_apps-1.11.1/apps/ethercat_master/software/inc` | BSD-3-Clause | 原样使用 |
| `apps/LuckyCAT_EtherCAT_Master/software/CMakeLists.txt` | `hpm_apps-1.11.1/apps/ethercat_master/software/CMakeLists.txt` | BSD-3-Clause | 修改 |
| `apps/LuckyCAT_EtherCAT_Master/software/src/main.c` | 上游 `ethercat_master` 启动流程 | BSD-3-Clause | 改写 |
| `apps/LuckyCAT_EtherCAT_Master/software/src/ecat_app.c` | 本项目新增 | **Apache-2.0** | 新增 |
| `apps/LuckyCAT_EtherCAT_Master/software/OLED/` | 厂商 `demo/3_oled_sw_i2c/OLED` | 厂商示例（无显式文件头） | 修改 |
| `middleware/cherryecat/`（除 port） | `hpm_apps-1.11.1/middleware/cherryecat` | Apache-2.0 | 原样使用（删除无用目录） |
| `middleware/cherryecat/port/netdev_hpmicro.c` | 同上 | Apache-2.0 | 大幅修改 |
| `components/enet_phy/` | `hpm_apps-1.11.1/components/enet_phy` | BSD-3-Clause | 原样使用 |
| 构建系统 / 驱动 / FreeRTOS / JL1111 / cherrysh | `hpm_sdk 1.13.0` | BSD-3-Clause | 外部依赖，不随仓库分发 |
| 根 `CMakeLists.txt`、`components/`、`middleware/` 的 CMake | 本项目新增 | **Apache-2.0** | 新增 |
| `tools/`、`tests/`、`docs/` | 本项目新增 | **Apache-2.0** | 新增 |

### 许可证总览

- 根目录 `LICENSE` 为 **Apache License 2.0**，覆盖本项目新编写的代码与文档；
- 表中标注 BSD-3-Clause 或“厂商示例”的文件保留原许可证/原状态，不因本项目而改变；
- CherryECAT 本身即为 Apache-2.0，与本项目一致；
- BSD-3-Clause 与 Apache-2.0 兼容，但再分发时仍需保留原版权与许可声明，
  详见根目录 `THIRD_PARTY_NOTICES.md`。

---

## 2. LuckyCAT_SoftWare-main 的用途与改动

厂商工程提供了板级硬件描述与示例，用于确认引脚、PHY、OLED、时钟等硬件信息。

### 2.1 `board.c`

| 改动 | 说明 |
| --- | --- |
| **实现 `board_init_pmp()`** | 原文件为空函数。新增默认全地址访问 + `.noncacheable` 段的 non-cacheable PMA 配置，这是 ENET DMA 正常工作的前提 |
| **新增 `board_init_enet_mii_clock()`** | 打开 ENET/ESC 时钟与 ESC PHY 时钟输出，并把 ENET0 的 MII 发送时钟源设为 TXC |
| 保留 | 时钟树、电源、UART、USB、ADC 等厂商初始化 |

### 2.2 `board.h`

| 改动 | 说明 |
| --- | --- |
| `BOARD_ECAT_SUPPORT_PORT1` 由 `1` 改为 `0` | ENET0 主站占用 port1 的引脚，从站只保留 port0 |
| 新增 `board_init_enet_mii_clock()` 声明 | 配合 board.c |

### 2.3 `pinmux.c`

| 改动 | 说明 |
| --- | --- |
| `init_esc_pins()` 中 PA30/PA31 改为 `ETH0_MDIO/ETH0_MDC` | 主站需要管理两颗 PHY |
| PB26 不再由 ESC 配置为 GPIO 复位 | 复位由 ENET 侧 `board_reset_enet_phy()` 负责 |
| PB28（NMII_LINK1）改为下拉 | 单板回环时让 ESC 认为 port1 无链路 |
| ESC port1（PF02~PF14）配置用 `#if 0` 屏蔽 | 与 ENET0 MII 复用，主站模式下不能配对 |

### 2.4 其他

- `hpm5e31_LuckyCAT.cfg`、`hpm5e31_LuckyCAT.yaml`、`README_*.rst`：原样保留；
- `doc/`（厂商原理图/图片，约 1.4 MB）：**未纳入**发布仓库，避免分发第三方文档；
- OLED 驱动 `demo/3_oled_sw_i2c/OLED`：复制后修改（见第 3 节）。

### 2.5 参考但未直接使用的部分

- `demo/5_lwip/lwip_iperf`：用于对照 ENET/JL1111 的 MII 初始化流程、
  验证发送计数与描述符行为；相关结论见 `docs/06-troubleshooting.md`；
- `demo/4_ethercat_io/ecat_io`：用于验证板上 ESC 从站与外设，未纳入本发布版。

---

## 3. 应用层改动

| 文件 | 来源 | 改动 |
| --- | --- | --- |
| `src/main.c` | 参考 `ethercat_master` 的启动流程 | 重写：OLED/shell 初始化、主站初始化重试、移除板载从站入口 |
| `src/ecat_app.c` | 新增 | CiA402 状态机、PDO 偏移解析、速度斜坡、按键、OLED UI、`motor` 命令 |
| `OLED/oled.c/h` | `LuckyCAT_SoftWare-main/demo/3_oled_sw_i2c/OLED` | 增加 I2C ACK 统计、显存清空接口；放慢软件 I2C；移除未使用的自检函数 |
| `inc/ec_config.h` 等 | `hpm_apps-1.11.1/apps/ethercat_master` | 原样使用 |
| `CMakeLists.txt` | 同上 | 改工程名/输出名；移除 SSC 从站与 EEPROM 仿真；固定 MII |

主要逻辑改动说明：

1. **PDO 布局自动解析**：不再固定偏移，按 SII/内置表里的条目位宽累加；
2. **DC 能力自适应**：`base_dc_supported` 为假时 `dc_assign_activate = 0`；
3. **CoE 能力自适应**：无 mailbox 的从站跳过 `0x6060` 写入；
4. **WKC 读取时机**：回调内读 `pdo_datagram.working_counter`；
5. **链路恢复**：链路重新建立后自动重新扫描并启动。

---

## 4. CherryECAT 中间件改动

上游：`hpm_apps-1.11.1/middleware/cherryecat`（Apache-2.0，v2.0.1）。

保留：`include/`、`src/`、`osal/`、`CMakeLists.txt`、`LICENSE`、`README*`、`VERSION`。

删除：`scripts/`（代码生成脚本）、`SConscript`、`.readthedocs.yaml`（与本工程无关）。

### 4.1 `port/netdev_hpmicro.c`

这是改动最大的文件，从“通用 HPM ENET 移植”改为“LuckyCAT 专用 MII 移植”：

| 改动 | 原因 |
| --- | --- |
| 固定 MII，移除 RMII/RGMII 分支 | 本板只使用 ENET0 + MII |
| PHY 地址固定为 2 | ECAT OUT 的 JL1111 硬件 strap |
| JL1111 显式切换 MII 模式 | 芯片缺省为 RMII |
| 发送描述符软件回收 | HPM5E31 DMA 不清 `TDES0.OWN` |
| 发送完成中断（TIE/IOC） | 为回收提供完成计数 |
| RX 增加 EtherType `0x88A4` 过滤 | 共享局域网时过滤 ARP/DHCP |
| 缓冲区/描述符放入 `.noncacheable` | 配合 `board_init_pmp()` |
| 发送环满返回 `NULL` 而非断言 | 避免一帧拥塞导致系统停机 |
| 链路建立时补一次 `POLL_DEMAND` | 链路晚于帧排队时重启发送 |
| 删除 PHY 扫描、时钟探针等调试代码 | 发布版整洁 |

### 4.2 协议栈内部

为配合应用层能力判断，仅做了很小的改动：

- `ec_slave.c` 的 SII 读取与解析保持上游逻辑；
- `ec_sii.c` 保持上游逻辑（调试打印已移除）；
- 扫描/状态机/DC 均由应用层通过配置结构控制，未改协议栈核心。

---

## 5. 工具与测试（新增）

| 文件 | 说明 |
| --- | --- |
| `tools/build.sh` / `build.ps1` | 跨平台构建，使用环境变量而非硬编码路径 |
| `tools/openocd.sh` / `.ps1` | 启动 CMSIS-DAP 调试服务 |
| `tools/flash.py` | 通过 OpenOCD telnet 烧录+校验+复位 |
| `tools/serial_monitor.py` | 串口监视、发送命令、通过 OpenOCD 复位 |
| `tools/wpc.py` | Npcap/wpcap 的 ctypes 封装 |
| `tools/ecat_slave_sim.py` | PC 端虚拟 EtherCAT CiA402 从站 |
| `tests/test_esc_model.py` | ESC/SII/CiA402 离线单元测试 |
| `tests/run_tests.py` | 测试入口 |

`ecat_slave_sim.py` 中的 SII 布局、SM 数量、EEPROM 长度等细节，是根据 CherryECAT
的实际解析行为反推并验证的，说明见 `docs/06-troubleshooting.md` 第 8 节。

---

## 6. 未纳入发布版的内容

| 内容 | 原因 |
| --- | --- |
| 板载 SSC CiA402 从站（`software/slave/`、`slave_app.c`） | EEPROM 仿真未跑通，仅用于单板自测；接真实伺服用不到 |
| 厂商 `board/.../doc/` | 第三方文档，避免再分发 |
| 调试日志、截图、临时脚本 | 与功能无关 |
| 本机路径、串口号、网卡/MAC 等 | 隐私与可移植性 |

---

## 7. 上游同步建议

1. **CherryECAT**：上游更新时，优先合并 `src/`、`include/`、`osal/`，
   再重新套用 `port/netdev_hpmicro.c` 的本项目修改（改动点见 4.1）；
2. **HPM SDK**：升级 SDK 时注意 `board_init_pmp` 的 PMA API、JL1111 驱动签名、
   `ENET_MAC_SIZE` 宏、`enet_prepare_tx_desc` 行为；
3. **板级文件**：若厂商更新 `board.c/pinmux.c`，需要重新确认
   PMP、MII 时钟、ESC port1 引脚屏蔽这三处改动。
