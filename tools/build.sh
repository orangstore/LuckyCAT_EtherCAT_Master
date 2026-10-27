#!/usr/bin/env bash
# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0
# Build LuckyCAT_EtherCAT_Master (Git Bash / Linux / macOS).
#
# Required environment:
#   HPM_SDK_BASE              path to hpm_sdk (1.13.0)
#   GNURISCV_TOOLCHAIN_PATH   path to the RISC-V GCC toolchain
#
# Optional:
#   BUILD_DIR                 build directory (default: <app>/build)
#   BOARD                     board name (default: hpm5e31_LuckyCAT)
#
# Usage:
#   ./tools/build.sh              build
#   ./tools/build.sh clean        remove the build directory and rebuild
#   ./tools/build.sh -j 4         limit parallelism
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/apps/LuckyCAT_EtherCAT_Master/software"
BOARD="${BOARD:-hpm5e31_LuckyCAT}"
BUILD_DIR="${BUILD_DIR:-$APP_DIR/build}"
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
CLEAN=0

while [ $# -gt 0 ]; do
    case "$1" in
        clean|--clean) CLEAN=1; shift ;;
        -j) JOBS="$2"; shift 2 ;;
        -j*) JOBS="${1#-j}"; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown option: $1"; exit 1 ;;
    esac
done

if [ -z "${HPM_SDK_BASE:-}" ] || [ ! -d "${HPM_SDK_BASE:-}/cmake" ]; then
    echo "ERROR: HPM_SDK_BASE is not set or does not point to an HPM SDK (1.13.0)." >&2
    echo "       export HPM_SDK_BASE=/path/to/sdk_env/hpm_sdk" >&2
    exit 1
fi
if [ -z "${GNURISCV_TOOLCHAIN_PATH:-}" ] || [ ! -d "${GNURISCV_TOOLCHAIN_PATH:-}/bin" ]; then
    echo "ERROR: GNURISCV_TOOLCHAIN_PATH is not set or does not contain bin/." >&2
    exit 1
fi

# Prefer the cmake/ninja/python bundled with the SDK environment, then fall back
# to whatever is already in PATH.
SDK_ENV_ROOT="$(cd "$HPM_SDK_BASE/.." && pwd)"
for d in "$SDK_ENV_ROOT/tools/python3" "$SDK_ENV_ROOT/tools/cmake/bin" "$SDK_ENV_ROOT/tools/ninja"; do
    [ -d "$d" ] && PATH="$d:$PATH"
done
# Git Bash needs a POSIX path for the toolchain directory
TC_BIN="$GNURISCV_TOOLCHAIN_PATH/bin"
if command -v cygpath >/dev/null 2>&1; then
    TC_BIN="$(cygpath -u "$TC_BIN")"
fi
PATH="$TC_BIN:$PATH"
export PATH

command -v cmake >/dev/null || { echo "ERROR: cmake not found" >&2; exit 1; }
command -v ninja >/dev/null || { echo "ERROR: ninja not found" >&2; exit 1; }
if ! command -v riscv32-unknown-elf-gcc >/dev/null 2>&1 && [ ! -x "$TC_BIN/riscv32-unknown-elf-gcc.exe" ]; then
    echo "ERROR: RISC-V GCC not found in $TC_BIN" >&2
    exit 1
fi

if [ "$CLEAN" = "1" ]; then
    rm -rf "$BUILD_DIR"
fi

if [ ! -f "$BUILD_DIR/CMakeCache.txt" ]; then
    cmake -S "$APP_DIR" -B "$BUILD_DIR" -GNinja \
        -DBOARD="$BOARD" \
        -DBOARD_SEARCH_PATH="$ROOT/boards" \
        -DHPM_BUILD_TYPE=flash_xip \
        -DCMAKE_BUILD_TYPE=debug
fi

cmake --build "$BUILD_DIR" -j "$JOBS"

echo
echo "BUILD OK"
echo "  elf: $BUILD_DIR/output/LuckyCAT_EtherCAT_Master.elf"
echo "  bin: $BUILD_DIR/output/LuckyCAT_EtherCAT_Master.bin"
