# 硬件说明

## 1. 板卡概览

| 项目 | 参数 |
| --- | --- |
| 开发板 | LuckyCAT |
| SoC | HPM5E31xPBx（RISC-V，内置 2 端口 EtherCAT ESC） |
| Flash | 1 MB QSPI NOR（`0x80000000`） |
| 主站网口 | 丝印 **ECAT OUT**（ESC port1 的 PHY） |
| 从站网口 | 丝印 **ECAT IN**（ESC port0 的 PHY） |
| 调试器 | 板载 CMSIS-DAP |

## 2. ENET0（MII）引脚

主站使用 `HPM_ENET0`，固定 **MII** 模式，PHY 为 JL1111（U4）。

### 2.1 发送方向（MCU → PHY）

| MCU 引脚 | 复用功能 | 说明 |
| --- | --- | --- |
| PF02 | `ETH0_TXCK` | 25 MHz 发送时钟（PHY 提供） |
| PF03 | `ETH0_TXD_0` | 发送数据 bit0 |
| PF04 | `ETH0_TXD_1` | 发送数据 bit1 |
| PF05 | `ETH0_TXD_2` | 发送数据 bit2 |
| PF06 | `ETH0_TXD_3` | 发送数据 bit3 |
| PF07 | `ETH0_TXEN` | 发送使能 |

### 2.2 接收方向（PHY → MCU）

| MCU 引脚 | 复用功能 | 说明 |
| --- | --- | --- |
| PF13 | `ETH0_RXCK` | 25 MHz 接收时钟 |
| PF08 | `ETH0_RXDV` | 接收数据有效 |
| PF09 | `ETH0_RXD_0` | 接收数据 bit0 |
| PF10 | `ETH0_RXD_1` | 接收数据 bit1 |
| PF11 | `ETH0_RXD_2` | 接收数据 bit2 |
| PF12 | `ETH0_RXD_3` | 接收数据 bit3 |
| PF14 | `ETH0_RXER` | 接收错误 |

### 2.3 管理与时钟

| MCU 引脚 | 复用功能 | 说明 |
| --- | --- | --- |
| PA30 | `ETH0_MDIO` | PHY 管理数据（两颗 PHY 共用） |
| PA31 | `ETH0_MDC` | PHY 管理时钟 |
| PB26 | `GPIO_B_26` | 两颗 PHY 共用的复位（低有效） |
| PA09 | `ESC0_REFCK` | 25 MHz 参考时钟，送给 P1 的 PHY |

> 板上两颗 JL1111 都**没有独立晶振**，XI 的 25 MHz 来自 ESC 的 `ESC0_REFCK` 输出。
> 因此主站初始化时必须同时打开 ESC 的 PHY 时钟输出（`board_init_enet_mii_clock()`）。

## 3. 引脚复用关系

ENET0 的 MII 引脚与片上 ESC 的 **port1** 是同一组 PAD：

| PAD | ALT 11（ESC 从站） | ALT 18（ENET 主站） |
| --- | --- | --- |
| PF02 | `ESC0_P1_TXCK` | `ETH0_TXCK` |
| PF03~PF06 | `ESC0_P1_TXD_0..3` | `ETH0_TXD_0..3` |
| PF07 | `ESC0_P1_TXEN` | `ETH0_TXEN` |
| PF08 | `ESC0_P1_RXDV` | `ETH0_RXDV` |
| PF09~PF12 | `ESC0_P1_RXD_0..3` | `ETH0_RXD_0..3` |
| PF13 | `ESC0_P1_RXCK` | `ETH0_RXCK` |
| PF14 | `ESC0_P1_RXER` | `ETH0_RXER` |

结论：

- **主站模式**：PF 组配置为 `ETH0_*`，`ECAT OUT` 作为普通网口使用；
- **从站模式**：PF 组配置为 `ESC0_P1_*`，`ECAT OUT` 归 ESC 使用。

同一时刻只能二选一。板级 `pinmux.c` 中的 `init_esc_pins()` 已屏蔽 port1 的引脚配置，
把 PF 组留给 ENET0。

其他共享资源：

- **MDIO/MDC（PA30/PA31）**：两颗 PHY 共用一条管理总线；
- **PHY 复位（PB26）**：两颗 PHY 共用一个复位信号，复位 P1 会同时复位 P0；
- **参考时钟（PA09）**：由 ESC 输出，主站与从站都需要它。

## 4. PHY 地址

| 网口 | PHY | 默认 MDIO 地址 | 用途 |
| --- | --- | --- | --- |
| ECAT IN（P0） | JL1111 U3 | 1 | 从站 port0（主站模式下仅用于诊断） |
| ECAT OUT（P1） | JL1111 U4 | 2 | **主站数据口** |

`middleware/cherryecat/port/netdev_hpmicro.c` 中：

```c
#define ENET_MII_PHY_ADDR       2   /* ECAT OUT */
#define ENET_MII_PEER_PHY_ADDR  1   /* ECAT IN  */
```

## 5. 人机接口

| 外设 | 引脚 | 说明 |
| --- | --- | --- |
| OLED SCL | PD7 | 软件 I2C |
| OLED SDA | PD6 | 软件 I2C（ACK 时切输入） |
| 按键 K1 | PA2 | 低有效，启停 |
| 按键 K2 | PA3 | 低有效，速度循环 |
| LED | PA22 | 低电平点亮，OP 时常亮 |
| 串口 TX | PA00 | UART0 TXD，115200 8N1 |
| 串口 RX | PA01 | UART0 RXD |

## 6. 接线建议

### 6.1 接真实伺服

```
LuckyCAT ECAT OUT  ──网线──  伺服驱动器 ECAT IN
```

主站只使用 ECAT OUT；ECAT IN 不用。

### 6.2 接 PC 虚拟从站

```
LuckyCAT ECAT OUT  ──网线──  交换机/路由器  ──网线──  PC 网口
```

EtherCAT 帧是以太网广播（EtherType `0x88A4`），普通交换机会透明转发。
PC 侧需要安装 [Npcap](https://npcap.com)（WinPcap 兼容模式即可）。

也可以直连 PC 网口，效果相同。

## 7. 电源与复位

- 板子通过 USB 供电与调试（CMSIS-DAP）；
- 复位后固件会自动重新初始化 ENET/PHY，OLED 显示 `Initializing..`；
- 若 PHY 初始化失败，固件会每 2 s 重试，并在 OLED 显示 `ECAT INIT FAILED / RETRY...`。
