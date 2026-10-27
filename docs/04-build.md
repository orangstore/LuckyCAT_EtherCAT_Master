# 构建说明

## 1. 依赖

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| HPM SDK | **1.13.0** | `APP_VERSION_STRING` 会校验，版本不一致会直接报错 |
| RISC-V GCC | `rv32imac_zicsr_zifencei_multilib_b_ext` | SDK 自带 |
| CMake | ≥ 3.13 | SDK 自带 |
| Ninja | 任意 | SDK 自带 |
| Python | 3.8+ | SDK 构建脚本需要 `yaml`（SDK 自带 python 已安装） |

SDK 目录结构假定为：

```
sdk_env/
├── hpm_sdk/
├── toolchains/rv32imac_zicsr_zifencei_multilib_b_ext-<host>/
└── tools/{cmake,ninja,python3,openocd}/
```

`tools/build.sh` 会优先使用 `$HPM_SDK_BASE/../tools` 下的 cmake/ninja/python，
找不到时回退到 `PATH`。

## 2. 环境变量

```bash
export HPM_SDK_BASE=/path/to/sdk_env/hpm_sdk
export GNURISCV_TOOLCHAIN_PATH=/path/to/sdk_env/toolchains/rv32imac_zicsr_zifencei_multilib_b_ext-win
```

可选：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BOARD` | `hpm5e31_LuckyCAT` | 板级目录名 |
| `BUILD_DIR` | `apps/LuckyCAT_EtherCAT_Master/software/build` | 构建目录 |

## 3. 目录与构建层级

本仓库根目录刻意保持 **hpm_apps 风格**，让应用 CMakeLists 可以原样复用上游写法：

```
LuckyCAT_EtherCAT_Master/                  ← 相当于 hpm_apps 根
├── CMakeLists.txt                     ← add_subdirectory(components) / (middleware)
├── components/enet_phy/               ← PHY 公共头
├── middleware/cherryecat/             ← 协议栈
├── boards/hpm5e31_LuckyCAT/           ← 通过 BOARD_SEARCH_PATH 找到
└── apps/LuckyCAT_EtherCAT_Master/software ← 应用入口（CMake 顶层）
```

应用 CMakeLists 的关键点：

```cmake
set(APP_NAME LuckyCAT_EtherCAT_Master)     # 输出文件名
find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})
project(LuckyCAT_EtherCAT_Master)
add_subdirectory(../../.. hpm_apps/build_tmp)
generate_ide_projects()
```

`add_subdirectory(../../..)` 回到仓库根，从而加载 `components` 与 `middleware`。

## 4. 构建命令

### 4.1 脚本

```bash
./tools/build.sh                 # 增量构建
./tools/build.sh clean           # 删除 build 后重建
./tools/build.sh -j 4            # 限制并行
```

```powershell
.\tools\build.ps1
.\tools\build.ps1 -Clean
.\tools\build.ps1 -Jobs 4
```

### 4.2 手工 CMake

```bash
cd apps/LuckyCAT_EtherCAT_Master/software
cmake -S . -B build -GNinja \
    -DBOARD=hpm5e31_LuckyCAT \
    -DBOARD_SEARCH_PATH=$PWD/../../../boards \
    -DHPM_BUILD_TYPE=flash_xip \
    -DCMAKE_BUILD_TYPE=debug
cmake --build build -j 8
```

构建类型：

| `HPM_BUILD_TYPE` | 说明 |
| --- | --- |
| `flash_xip` | 代码在 Flash 原地执行（默认，推荐） |
| `flash_sdram_xip` | 需要外部 SDRAM，本板未使用 |
| `ram` | 调试用，掉电丢失 |

`CMAKE_BUILD_TYPE` 可选 `debug` / `release`；当前脚本使用 `debug`。

## 5. 产物

```
build/output/
├── LuckyCAT_EtherCAT_Master.elf      # 烧录/调试
├── LuckyCAT_EtherCAT_Master.bin      # 量产/离线烧录
├── LuckyCAT_EtherCAT_Master.map      # 符号与段布局
└── LuckyCAT_EtherCAT_Master.asm      # 反汇编
```

另外会生成 IAR / SEGGER 工程（供 IDE 使用）：

```
build/iar_embedded_workbench/LuckyCAT_EtherCAT_Master.ewp
build/segger_embedded_studio/LuckyCAT_EtherCAT_Master.emProject
```

## 6. 清理

```bash
rm -rf apps/LuckyCAT_EtherCAT_Master/software/build
```

或 `./tools/build.sh clean`。

## 7. 集成回 hpm_apps

如果要把本工程放回 `hpm_apps` 仓库：

1. 复制 `apps/LuckyCAT_EtherCAT_Master` 到 `hpm_apps/apps/`；
2. 复制 `boards/hpm5e31_LuckyCAT` 到 `hpm_apps/boards/`（若已存在则合并）；
3. 用 `hpm_apps` 的 `hpmapp.sh` 或同样的 CMake 命令构建，`BOARD_SEARCH_PATH` 指向
   `hpm_apps/boards`；
4. `middleware/cherryecat` 需要保留本仓库的 `port/netdev_hpmicro.c` 修改
   （TX 描述符回收、RX 过滤、MII 固定）。

## 8. 版本兼容性

- **HPM SDK 1.13.0**：本工程的目标版本，已验证；
- HPM SDK 1.11.0：协议栈与驱动可以编译，但 JL1111 API 与 `ENET_MAC` 宏不同，
  且 SDK 版本校验会拒绝（可改 `APP_VERSION_STRING` 后自行验证，不保证）；
- 其他版本未验证。

## 9. 常见构建问题

| 报错 | 原因/处理 |
| --- | --- |
| `GNURISCV_TOOLCHAIN_PATH is not set yet` | 未导出环境变量 |
| `SDK version mismatch` | SDK 不是 1.13.0，或 `APP_VERSION_STRING` 被改过 |
| `No module named yaml` | 用了系统 python 而不是 SDK 自带 python；把 SDK 的 `tools/python3` 放到 PATH 前面 |
| `ninja: command not found` | 同上，或用 `tools/build.sh`（会自动加 PATH） |
| `undefined reference to board_init_enet_mii_clock` | 板级目录不是本仓库的版本 |
