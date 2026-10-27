# Changelog

所有重要变更记录在此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

## [1.0.0] - 2026-10-27

首个可发布版本：LuckyCAT（HPM5E31）EtherCAT 主站 + CiA402 CSV 控制。

### Added

- EtherCAT 主站工程（CherryECAT + FreeRTOS + HPM SDK 1.13.0），输出
  `LuckyCAT_EtherCAT_Master.elf/.bin`；
- ENET0 + MII + JL1111（ECAT OUT，PHY 地址 2）移植层；
- CiA402 CSV 状态机、目标速度斜坡、位置反馈；
- PDO 偏移自动解析，支持内置从站表与 fallback 映射（`0x1602/0x1A02`）；
- DC、CoE 能力自适应（从站不支持时自动跳过）；
- SSD1306 OLED 状态界面（软件 I2C，PD6/PD7）；
- shell 命令 `motor start|stop|speed|status|reset|cycle|selftest`；
- 按键 K1/K2 控制；
- 链路断开/恢复的自动处理，不再崩溃；
- PC 端虚拟 EtherCAT CiA402 从站（`tools/ecat_slave_sim.py` + `wpc.py`）；
- 离线单元测试（SII/ESC/CiA402，16 项）；
- 跨平台构建、烧录、串口、OpenOCD 脚本；
- 完整文档：快速开始、硬件、架构、构建、测试、排障、来源说明。

### Fixed

- **ENET 发送完全不通**：板级 `board_init_pmp()` 为空，`.noncacheable` 段仍走
  D-Cache，DMA 读到旧描述符。实现 PMP/PMA 配置后发送恢复，`tx stalled = 0`；
- **链路断开时死机**（`mcause=5`，FreeRTOS 链表损坏）：同上，缓存一致性修复后消失；
- **TX 描述符 OWN 位不被硬件清零**：改用发送完成中断 + 软件回收环形队列；
- **共享局域网下误解析 ARP/DHCP**：RX 只接收 EtherType `0x88A4`；
- **无 mailbox 从站触发 CoE 断言**：仅在从站声明 CoE 且 mailbox 已配置时发 SDO；
- **不支持 DC 的从站触发断言**：按 `base_dc_supported` 决定 `dc_assign_activate`；
- **`motor status` 的 WKC 恒为 0**：PDO 回调改读 `pdo_datagram.working_counter`；
- **OLED I2C 无 ACK**：ACK 阶段把 SDA 切为输入，并放慢软件 I2C；
- 虚拟从站 SII 布局（`uint16_t *` 偏移、分类目录位置、SM 数量、EEPROM 返回长度）。

### Changed

- 默认 PDO 周期由 1 ms 改为 **4 ms**，兼容 PC 虚拟从站的回包抖动；
  接真实伺服可用 `motor cycle 1000` 改回；
- 工程采用独立仓库结构，保留 hpm_apps 风格的构建层级；
- 工具脚本去除硬编码路径、串口号与本机信息，改用环境变量/参数。

### Removed

- 板载 SSC CiA402 从站自测代码（EEPROM 仿真未跑通，仅单板自测使用）；
- 厂商 `board/.../doc/` 第三方文档；
- 调试用 PHY 扫描、MII 时钟探针、MAC 回环、寄存器打印等临时代码。

### License

- 项目新增代码采用 **Apache-2.0**；第三方文件保留原许可证
  （CherryECAT Apache-2.0，HPM SDK / 板级文件 BSD-3-Clause），详见 `THIRD_PARTY_NOTICES.md`。

### Known issues

- 板载 ESC 从站的 EEPROM 仿真未跑通（不影响接真实伺服）；
- 虚拟从站非硬实时，不能用于验证 1 ms 周期抖动或 DC 精度；
- 仅支持单网口，不支持冗余。
