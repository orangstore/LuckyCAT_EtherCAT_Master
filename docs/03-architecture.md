# 软件架构

## 1. 分层结构

```
┌──────────────────────────────────────────────────────────┐
│ 应用层  apps/LuckyCAT_EtherCAT_Master/software               │
│   main.c       启动、shell、OLED 初始化                   │
│   ecat_app.c   CiA402 状态机、PDO 回调、按键、OLED UI     │
├──────────────────────────────────────────────────────────┤
│ 协议栈  middleware/cherryecat                            │
│   ec_master.c  扫描/配置/周期收发/DC                      │
│   ec_slave.c   SII 解析、SM/FMMU 配置                     │
│   ec_coe.c     SDO（可选，从站支持 mailbox 时）           │
│   port/netdev_hpmicro.c   ENET 移植层                     │
├──────────────────────────────────────────────────────────┤
│ 板级    boards/hpm5e31_LuckyCAT                          │
│   board.c     时钟、PMP、ENET/ESC 时钟、复位              │
│   pinmux.c    ENET0 MII / OLED / UART / 按键引脚          │
├──────────────────────────────────────────────────────────┤
│ HPM SDK 1.13.0                                           │
│   驱动、FreeRTOS、JL1111、cherrysh、构建系统              │
└──────────────────────────────────────────────────────────┘
```

## 2. 启动流程

```
main()
 ├─ board_init()                 时钟树、PMP、引脚
 ├─ board_init_gpio_pins()
 ├─ xTaskCreate(task_start)
 └─ vTaskStartScheduler()

task_start()
 ├─ UART0 + shell 初始化
 ├─ OLED 初始化（软件 I2C）
 ├─ ec_master_cmd_init()         注册 ethercat 命令
 ├─ ec_master_init(0)            ENET0 + PHY + 扫描线程（失败则每 2 s 重试）
 ├─ ecat_app_start()             创建应用任务
 └─ vTaskDelete(NULL)
```

`ec_master_init()` 内部会创建 CherryECAT 的扫描线程；扫描完成后由应用任务接管
配置与周期运行。

## 3. 任务与中断

| 上下文 | 优先级 | 职责 |
| --- | --- | --- |
| `task_start` | `configMAX_PRIORITIES - 2` | 初始化，完成后退出 |
| CherryECAT 扫描线程 | 由 `ec_config.h` 配置 | 总线扫描、SII、状态机 |
| 周期线程（master 内部） | 高 | 1 个 PDO 数据报 + 周期调度 |
| `ecat_task` | 4 | 自动启动、按键、OLED（50/200 ms 分频） |
| ENET0 IRQ | 由 `board_enable_enet_irq` 配置 | 收包、发送完成计数 |
| GPTMR IRQ | 10 | CherryECAT 高精度定时器 |
| UART0 IRQ | 1 | shell 输入 |

## 4. 数据通路

### 4.1 发送

```
ec_master_period_process()
  └─ ec_netdev_get_txbuf()         取一个空闲描述符
  └─ 填充 EtherCAT 数据报
  └─ ec_netdev_low_level_output()
        ├─ enet_prepare_tx_desc()
        ├─ fence
        └─ DMA_TX_POLL_DEMAND = 1
```

HPM5E31 的 ENET DMA 在发送完成后**不会清零 `TDES0.OWN`**，所以移植层用发送完成中断
（TI）维护一个软件尾指针：

```
TI 中断 → g_ec_netdev_tx_done++
下一次取缓冲 → ec_netdev_tx_recycle()
              while (recycled != done) { 清 OWN; 尾指针前移; }
```

若描述符环满，`ec_netdev_low_level_get_txbuf()` 返回 `NULL`，主站本轮跳过发送而不是断言。

### 4.2 接收

```
ENET0 IRQ（RI）
  └─ ec_netdev_low_level_input()
        ├─ 检查 EtherType == 0x88A4，否则直接释放（过滤 ARP/DHCP）
        └─ ec_netdev_receive() → 协议栈匹配数据报
```

### 4.3 PDO 与应用

```
周期线程收到 LRW 应答
  ├─ 更新 master->actual_working_counter
  └─ ec_pdo_callback(slave, output, input)
        ├─ cia402_step(statusword, run)   → 控制字
        ├─ 速度斜坡（APP_VEL_RAMP_STEP）
        ├─ 写 output: 0x6040 / 0x60FF
        └─ 读 input : 0x6041 / 0x6064
```

> `ec_pdo_callback` 在 `master->actual_working_counter` 赋值**之前**被调用，
> 因此回调里读的是 `master->pdo_datagram.working_counter`。

## 5. CiA402 状态机

`cia402_step()` 只做控制字译码，状态迁移由从站状态字驱动：

| 状态字状态 | 控制字输出 |
| --- | --- |
| Not ready to switch on | `0x0000` |
| Switch on disabled | `0x0006`（Shutdown） |
| Ready to switch on | `0x0007`（Switch on） |
| Switched on | `run ? 0x000F : 0x0007` |
| Operation enabled | `run ? 0x000F : 0x0006` |
| Quick stop active | `0x0002`（Disable voltage） |
| Fault | 交替 `0x0080` / `0x0000`，直到故障清除 |
| Fault reaction active | `0x0000` |

`run` 由 K1 或 `motor start/stop` 控制。目标速度带斜坡，每个周期增减
`APP_VEL_RAMP_STEP`（默认 5），避免阶跃冲击。

## 6. PDO 映射

1. 先按 `SII.vendor_id / product_code / revision` 查 CherryECAT 内置的
   `ec_slave_table.c`，命中则用表里的 SM/PDO 定义；
2. 未命中时回退到标准 CiA402 CSV 布局：

| 方向 | PDO | 内容 |
| --- | --- | --- |
| 输出 | `0x1602` | `0x6040:00` (16 bit) + `0x60FF:00` (32 bit) + 16 bit pad = 8 B |
| 输入 | `0x1A02` | `0x6041:00` (16 bit) + `0x6064:00` (32 bit) + 16 bit pad = 8 B |

3. `layout_from_syncs()` 按条目位宽累加，得到每个对象的字节偏移，
   因此从站 PDO 顺序变化时不需要改代码。

## 7. 链路与异常处理

- 链路断开：CherryECAT 停止主站、清理从站；应用层检测到 `link` 下降后不再发命令，
  并把 `auto_start_done` 复位；
- 链路恢复：应用层重新触发扫描，扫描完成后自动配置并启动；
- PHY 初始化失败：`ec_master_init()` 返回失败，`main` 每 2 s 重试并在 OLED 提示；
- 发送环满：跳过本轮，计数 `g_ec_netdev_tx_stall`，不阻塞中断。

## 8. 关键板级修复：`board_init_pmp()`

厂商板级文件里 `board_init_pmp()` 是空函数。HPM5E31 的 ENET 描述符和收发缓冲区放在
`.noncacheable` 段（`0x01230000` 起），如果没有把它配置为 non-cacheable：

- CPU 写 `TDES0.OWN=1` 只落在 D-Cache，DMA 读到的仍是 `OWN=0` → 帧永远发不出去；
- DMA 回写的完成状态被 Cache 中的旧值覆盖 → 描述符永远不回收；
- 用调试器写 `DMA_TX_POLL_DEMAND` 能发（调试访问绕过缓存），CPU 写同样的寄存器无效。

修复方式与官方 EVK 一致：默认允许全部地址访问，并为 `.noncacheable` 段配置
`MEM_TYPE_MEM_NON_CACHE_BUF` 的 PMA 属性。

```c
/* boards/hpm5e31_LuckyCAT/board.c */
void board_init_pmp(void)
{
    /* allow all access by default */
    ...
    /* .noncacheable section: non-cacheable, bufferable */
    pmp_config.entry[0].pma_cfg = PMA_CFG(...);
}
```

修复后实测 `tx stalled = 0`，`queued / done / recycled` 同步增长。

## 9. 源文件索引

| 文件 | 说明 |
| --- | --- |
| `src/main.c` | 启动、shell、OLED 初始化 |
| `src/ecat_app.c` | CiA402、PDO 布局解析、按键、OLED UI、`motor` 命令 |
| `OLED/oled.c` | SSD1306 软件 I2C 驱动（含 ACK 检测） |
| `port/netdev_hpmicro.c` | ENET MII 移植层、TX 回收、RX 过滤、定时器 |
| `boards/.../board.c` | 时钟、PMP、ENET/ESC 时钟、PHY 复位 |
| `boards/.../pinmux.c` | 引脚复用（ENET0 与 ESC port1 二选一） |
