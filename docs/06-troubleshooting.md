# 故障排查

本文件记录本项目在移植和调试过程中实际遇到并解决的问题，按现象组织。
寄存器地址基于 HPM5E31：ENET0 基址 `0xF1400000`，ESC 基址 `0xF1700000`。

---

## 1. 主站发不出帧，`tx stalled` 持续增长

### 现象

```
[E/ec_master] ec_netdev_send() failed (...)
motor status:
  tx      : queued 0, done 0, recycled 0, stalled 1200
OLED: NO TX (ENET DMA)
```

寄存器：

- `DMA_STATUS (0xF1401014)` 出现 TU（发送下溢）与 RU；
- `DMA_CURR_HOST_TX_DESC (0xF1401048)` 停在环首；
- `TXFRAMECOUNT_GB (0xF1400124)` 不增长；
- 发送描述符 `TDES0.OWN` 始终为 1；
- 用调试器写 `DMA_TX_POLL_DEMAND (0xF1401004)` 能一次性把积压帧发完，CPU 写同样寄存器无效。

### 根因

板级 `board_init_pmp()` 是**空函数**。ENET 描述符与收发缓冲区位于 `.noncacheable`
段，但没有被配置成 non-cacheable，于是：

- CPU 写 `OWN=1` 只落在 D-Cache，DMA 从物理内存读到 `OWN=0` → 不发送；
- DMA 回写的完成状态被 Cache 里的旧值覆盖 → 描述符永不回收；
- 调试器访问绕过缓存，所以“调试器能发、CPU 不能发”。

### 处理

`boards/hpm5e31_LuckyCAT/board.c` 中实现 `board_init_pmp()`，为 `.noncacheable`
段配置 `MEM_TYPE_MEM_NON_CACHE_BUF` 的 PMA 属性（与官方 EVK 一致）。

验证：

```
tx      : queued 80, done 80, recycled 79, stalled 0
```

### 备注

- 与 SDK 版本无关：1.11.0 与 1.13.0 表现一致；
- 与 MII/RMII、PBL、描述符长度、内存屏障均无关，这些方向都试过，现象不变。

---

## 2. 链路断开时死机（`mcause=5`）

### 现象

拔网线或 PHY 进入回环时：

```
[I/ec_master] Detect link down on ec-netdev0(main)
Exception occur!
mcause: 0x5  mepc: ...xTaskRemoveFromEventList
Current Thread Name: ec_scan
```

### 根因

与第 1 条同源：DMA 覆写了仍在 Cache 中的 FreeRTOS 链表/事件结构，导致内核链表损坏。
不是链路处理逻辑本身的问题。

### 处理

修复 `board_init_pmp()` 后不再复现。回归测试：拔插网线、重启虚拟从站、PHY 回环，
均无异常，shell 始终可用。

---

## 3. PHY 无 link / ENET 初始化失败

### 现象

```
ENET: PHY P0 BMSR = 0x...., P1 BMSR = 0x7849
ENET: no link, initialize MAC in PHY loopback mode
Enet initialization fails
```

### 检查顺序

1. **网线是否插在 ECAT OUT**（P1，PHY 地址 2）；ECAT IN 不是主站口；
2. **PHY 参考时钟**：板上 PHY 没有晶振，25 MHz 来自 `ESC0_REFCK`（PA09），
   必须调用 `board_init_enet_mii_clock()` 打开 ESC PHY 时钟输出；
3. **PHY 模式**：JL1111 缺省是 RMII，需要 `jl1111_basic_mode_init()` 且
   `media_interface = enet_inf_mii`；
4. **复位**：两颗 PHY 共用 PB26，复位后要等自协商完成（代码最多等 8 s）；
5. **MDIO**：PA30/PA31 是否被 ESC 占用（`init_esc_pins()` 不应再配置这两脚）。

### 说明

JL1111 只有在 link 建立后才输出 MII RX clock，因此链路未建立时 ENET 无法初始化。
代码的做法是：先临时打开 PHY 内部回环取得 RX clock 完成 MAC 初始化，再恢复自协商。
这在“先上电、后插网线”的场景下是必要的。

---

## 4. 串口刷 `Corrupted frame received`

### 现象

板子接在共享局域网时，主站不断打印：

```
[E/ec_netdev] Corrupted frame received
```

### 根因

ENET 收到了 ARP/DHCP/IP 广播，协议栈把它们当作 EtherCAT 帧解析。

### 处理

`port/netdev_hpmicro.c` 的接收路径只把 EtherType `0x88A4` 的帧交给协议栈，
其余帧直接释放描述符。

---

## 5. 启动时断言：slave does not support DC

### 现象

```
ASSERT: ... dc ...
```

### 根因

`ec_slave_cfg.dc_assign_activate` 固定为 `0x300`，但从站（例如 PC 模拟器）
不支持 DC。

### 处理

```c
s_slave_cfg[i].dc_assign_activate = master->slaves[i].base_dc_supported ? 0x300 : 0;
master->dc_sync_with_dc_ref_enable = (master->dc_ref_clock != NULL);
```

接真实伺服时若支持 DC，会自动启用。

---

## 6. 启动时断言：`ec_coe_download` / rx mailbox 为 0

### 现象

从站没有 mailbox（`mailbox_protocols = 0`），主站仍尝试写 `0x6060`，触发断言。

### 处理

只有同时满足以下条件才发 SDO：

```c
bool coe_ready = ((slave->sii.mailbox_protocols & EC_MBXPROT_COE) != 0) &&
                 (slave->configured_rx_mailbox_size > 0);
```

否则打印 `no CoE mailbox, skip 0x6060 (assuming CSV)`。

---

## 7. `motor status` 里 `wkc` 永远是 0

### 现象

PDO 实际在交换（从站侧能看到数据），但应用层显示 `wkc 0/3`。

### 根因

`ec_pdo_callback()` 在 `master->actual_working_counter` 赋值**之前**被调用。

### 处理

回调里直接读数据报自己的计数：

```c
app->wkc_actual = slave->master->pdo_datagram.working_counter;
```

---

## 8. 虚拟从站相关

### 8.1 主站读到全 0xFF 的 SII

CherryECAT 的 `sii_image` 声明为 `uint16_t *`，但读头部时用的是**字节偏移**，
所以实际地址是标准位置的两倍。写虚拟从站时：

| 字段 | 标准位置 | CherryECAT 实际读取 |
| --- | --- | --- |
| vendor id | 0x08 | 0x10 |
| product code | 0x0A | 0x14 |
| revision | 0x0C | 0x18 |
| mailbox_protocols | 0x1C | **0x38** |
| 分类目录 | 0x40 | **0x80**（字地址 0x40） |

`mailbox_protocols` 非 0 会让主站以为支持 CoE，把 `pdo_sm_count` 算成
`sm_count - 2`，PDO 永远配不起来。

### 8.2 SII 扫描成功但 PDO 起不来

应用层的 `sync.index` 是 **2/3**，所以从站必须报 **至少 4 个 SM**：

- SM0/SM1：长度 0（预留给 mailbox）；
- SM2：输出，物理地址 `0x1100`，长度 8；
- SM3：输入，物理地址 `0x1180`，长度 8。

### 8.3 EEPROM 读取导致帧变长

虚拟从站返回的数据必须**正好等于**数据报声明的长度：

```
0x502 状态(2) + 0x504 地址(4) + 0x508 数据(N-6)
```

多返回字节会把整帧撑长，主站按“帧损坏”丢弃。

### 8.4 主站收不到应答 / `wkc` 掉

- 确认虚拟从站绑定的是连接板子的那块网卡（`--iface`）；
- 必须过滤“源 MAC 等于本机 MAC”的帧，否则 Npcap 会抓到本机发出的帧并回环；
- 1 ms 周期对 Python 太快，用 `motor cycle 4000`。

---

## 9. 烧录失败

| 现象 | 处理 |
| --- | --- |
| `Cannot connect to OpenOCD` | 先运行 `tools/openocd.sh` / `openocd.ps1` |
| `flash write_image` 超时/校验失败 | 降低 `adapter speed`（`--speed 1000`），确认调试器未被其他程序占用 |
| `Error: init mode failed` | 板子未上电、CMSIS-DAP 未识别、或复位引脚被占用 |
| 烧录后无输出 | 确认烧的是 `LuckyCAT_EtherCAT_Master.elf`，且串口 115200 8N1 |

---

## 10. OLED 无显示

- 软件 I2C：SCL=PD7，SDA=PD6；
- ACK 读取时 SDA 必须切为输入（`gpio_set_pin_input`），否则永远读到高电平；
- 启动日志会打印 `OLED: I2C OK (ack errors 0)` 或 `I2C ERROR`；
- `IIC_delay()` 已按 480 MHz 主频放慢到约 1 µs，过快会导致 ACK 失败。

---

## 11. 板载 ESC 从站自测（未纳入发布版）

开发过程中曾把 SSC CiA402 从站集成到同一固件，用于单板回环自测。结论：

- 从站能被主站扫到（`1 slaves responding ... INIT`），但完整扫描卡在 SII 读取
  （`Bus scanning failed at step 11`）；
- 根因是 ESC 的 EEPROM 仿真命令应答延迟超过主站 200 ms 超时；
  `EEPROM_CommandHandler()` 本身有效（能把 `0x8130` 清成 `0x0030`），
  但在任务/中断上下文都不稳定；
- 另外发现 EEPROM 仿真区全 `0xFFFF` 时校验和恰好通过，导致固件从不写入 SII 镜像
  （已修，但整体仍未跑通）。

该功能只影响“无真实从站时的单板自测”，接伺服用不到，因此发布版移除了
`software/slave/` 与 `slave_app.c`。推荐用 PC 虚拟从站替代（L2 测试）。
