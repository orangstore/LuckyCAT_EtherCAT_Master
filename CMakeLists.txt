# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0
#
# Minimal HPM application root for LuckyCAT_EtherCAT_Master.
# It mirrors the layout of the HPMicro hpm_apps repository, but only keeps the
# components and middleware required by this project.

add_subdirectory(components)
add_subdirectory(middleware)

message(STATUS "SDK_VERSION_STRING: ${SDK_VERSION_STRING}")
message(STATUS "APP_VERSION_STRING: ${APP_VERSION_STRING}")
if(APP_VERSION_STRING AND NOT (SDK_VERSION_STRING STREQUAL APP_VERSION_STRING))
    message(FATAL_ERROR "SDK version mismatch, this project requires HPM SDK ${APP_VERSION_STRING}")
endif()
