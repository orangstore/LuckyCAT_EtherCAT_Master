# Third-party notices

本仓库采用 **混合许可证**：项目新增代码为 Apache-2.0，随仓库分发的第三方文件保留其原有
许可证。使用与再分发时请同时遵守对应条款。

## 0. 本项目（LuckyCAT_EtherCAT_Master）

- 许可证：**Apache License 2.0**（见根目录 `LICENSE`）
- 覆盖范围：本项目新编写的文件，包括
  - `apps/LuckyCAT_EtherCAT_Master/software/src/ecat_app.c`
  - 根目录及各层新增的 `CMakeLists.txt`
  - `tools/`、`tests/`、`docs/`、`README.md`、`CHANGELOG.md`
- 版权：`Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors`

## 1. CherryECAT（随仓库分发）

- 路径：`middleware/cherryecat/`
- 上游：<https://github.com/cherry-embedded/CherryECAT>
- 版本：2.0.1（见 `middleware/cherryecat/VERSION`）
- 许可证：**Apache License 2.0**（见 `middleware/cherryecat/LICENSE`）
- 说明：保留上游 `LICENSE`、`README`、`VERSION` 与源码结构；删除了与本工程无关的
  `scripts/`、`SConscript`、`.readthedocs.yaml`。`port/netdev_hpmicro.c` 由本项目修改，
  修改部分仍受 Apache-2.0 约束。

## 2. HPMicro SDK（外部依赖，未随仓库分发）

- 名称：HPM SDK 1.13.0
- 上游：<https://github.com/hpmicro/hpm_sdk>
- 许可证：**BSD-3-Clause**
- 使用方式：通过 `HPM_SDK_BASE` 引用，仓库中不包含 SDK 源码。
- 涉及组件：驱动、FreeRTOS、JL1111 PHY 驱动、cherrysh、构建系统。

## 3. HPMicro hpm_apps（部分文件随仓库分发）

- 上游：HPMicro `hpm_apps` 应用仓库（本工程基于 1.11.1 版本整理）
- 许可证：**BSD-3-Clause**（文件头保留）
- 路径：
  - `apps/LuckyCAT_EtherCAT_Master/software/inc/*.h`（`ec_config.h`、`csh_config.h`、
    `FreeRTOSConfig.h`、`shell.h`、`cia402_def.h`）；
  - `apps/LuckyCAT_EtherCAT_Master/software/CMakeLists.txt`（由上游模板修改）；
  - `apps/LuckyCAT_EtherCAT_Master/software/src/main.c`（由上游 `ethercat_master` 示例改写）；
  - `components/enet_phy/`。

## 4. LuckyCAT 板级支持（随仓库分发）

- 来源：LuckyCAT 厂商示例工程 `LuckyCAT_SoftWare-main`
- 许可证：文件头标注 **BSD-3-Clause**
- 路径：`boards/hpm5e31_LuckyCAT/`
- 改动：`board.c` / `board.h` / `pinmux.c` 有修改，详见 `docs/07-provenance.md`。
- 未分发：厂商 `doc/` 目录中的原理图与图片。

## 5. OLED 驱动（随仓库分发）

- 路径：`apps/LuckyCAT_EtherCAT_Master/software/OLED/`
- 来源：LuckyCAT 厂商示例 `demo/3_oled_sw_i2c/OLED`
- 说明：原文件未包含许可证头，作为板级示例随本工程一起使用；本项目在其基础上增加了
  I2C ACK 统计、显存清空接口并放慢了软件 I2C。如用于商业再分发，请与板卡厂商确认授权。

## 6. EtherCAT 从站协议栈（未包含）

开发过程中曾使用 EtherCAT Technology Group 的 SSC（Slave Stack Code）做单板自测，
该代码**未纳入本仓库**。SSC 的复制与分发受 EtherCAT Technology Group 的许可约束，
如需使用请自行从 ETG 获取授权。

## 7. Npcap（外部依赖，未随仓库分发）

- 用途：`tools/wpc.py` / `tools/ecat_slave_sim.py` 通过 Npcap 收发原始以太网帧。
- 上游：<https://npcap.com>
- 许可证：Npcap 自有许可证（免费版对再分发有限制）。
- 说明：仓库不包含 Npcap 的任何二进制文件，使用者需自行安装。

## 8. Python 依赖

- `pyserial`（BSD-3-Clause）：仅 `tools/serial_monitor.py` 使用，未随仓库分发。

## 9. 商标

EtherCAT® 是 Beckhoff Automation GmbH 的注册商标，并授权给 EtherCAT Technology Group。
本工程仅用于技术验证，不包含任何 EtherCAT 商标授权。
