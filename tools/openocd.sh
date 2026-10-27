#!/usr/bin/env bash
# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0
# Start an OpenOCD debug server for the LuckyCAT board (CMSIS-DAP probe).
#
# The server stays in the foreground; keep this terminal open and use
# tools/flash.py from another one.
#
# Environment: HPM_SDK_BASE (required), BOARD (default hpm5e31_LuckyCAT),
#              OPENOCD (optional, path to the openocd executable)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOARD="${BOARD:-hpm5e31_LuckyCAT}"
: "${HPM_SDK_BASE:?set HPM_SDK_BASE to the hpm_sdk directory}"

SDK_ENV_ROOT="$(cd "$HPM_SDK_BASE/.." && pwd)"
OPENOCD_BIN="${OPENOCD:-$SDK_ENV_ROOT/tools/openocd/openocd.exe}"
if [ ! -x "$OPENOCD_BIN" ]; then
    OPENOCD_BIN="$(command -v openocd || true)"
fi
if [ -z "$OPENOCD_BIN" ]; then
    echo "ERROR: openocd not found, set OPENOCD=/path/to/openocd" >&2
    exit 1
fi

exec "$OPENOCD_BIN" \
    -s "$HPM_SDK_BASE/boards/openocd" \
    -f probes/cmsis_dap.cfg \
    -f soc/hpm5e00.cfg \
    -f "$ROOT/boards/$BOARD/$BOARD.cfg" \
    -c "adapter speed 1000"
