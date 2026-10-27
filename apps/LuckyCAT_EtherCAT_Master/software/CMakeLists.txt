# Copyright (c) 2025 HPMicro
# SPDX-License-Identifier: BSD-3-Clause

cmake_minimum_required(VERSION 3.13)

# Must match the HPM SDK release in use
set(APP_VERSION_STRING "\"1.13.0\"")

set(HPM_SDK_LD_NO_NANO_SPECS 1)

set(CONFIG_FREERTOS 1)
set(CONFIG_CHERRYSH 1)
set(CONFIG_CHERRYSH_INTERFACE "uart")

# ENET0 in MII mode, JL1111 PHY on the "ECAT OUT" port
set(CONFIG_ENET_PHY 1)
set(APP_USE_ENET_PORT_COUNT 1)
set(APP_USE_ENET_ITF_MII 1)

set(CONFIG_A_CHERRYECAT 1)
set(CONFIG_CHERRYECAT 1)
set(CONFIG_CHERRYECAT_OSAL "freertos")

# Firmware output name: <APP_NAME>.elf/.bin
set(APP_NAME LuckyCAT_EtherCAT_Master)

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})

project(LuckyCAT_EtherCAT_Master)

sdk_compile_definitions(-D__freertos_irq_stack_top=_stack)
sdk_compile_definitions(-DCONFIG_FREERTOS=1)
sdk_compile_definitions(-DUSE_NONVECTOR_MODE=1)
sdk_compile_definitions(-DDISABLE_IRQ_PREEMPTIVE=1)

sdk_compile_options("-O2")

sdk_inc(inc)
sdk_app_inc(OLED)
sdk_app_src(src/main.c)
sdk_app_src(src/ecat_app.c)
sdk_app_src(OLED/oled.c)

# Board support, CherryECAT middleware and the PHY component are added from the
# repository root, the same way the HPMicro hpm_apps examples do it.
add_subdirectory(../../.. hpm_apps/build_tmp)
generate_ide_projects()
