# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0
# Start an OpenOCD debug server for the LuckyCAT board (CMSIS-DAP probe).
#
# Keep this window open; use tools\flash.py or tools\serial_monitor.py from
# another PowerShell window.
#
# Environment: HPM_SDK_BASE (required), OPENOCD (optional full path)
param(
    [string]$Board = "hpm5e31_LuckyCAT",
    [int]$Speed = 1000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not $env:HPM_SDK_BASE) { Write-Error "HPM_SDK_BASE is not set." }
$SdkEnvRoot = Split-Path -Parent $env:HPM_SDK_BASE

$OpenOcd = if ($env:OPENOCD) { $env:OPENOCD } else { Join-Path $SdkEnvRoot "tools\openocd\openocd.exe" }
if (-not (Test-Path $OpenOcd)) {
    $cmd = Get-Command openocd -ErrorAction SilentlyContinue
    if (-not $cmd) { Write-Error "openocd not found, set OPENOCD to its full path." }
    $OpenOcd = $cmd.Source
}

& $OpenOcd `
    -s (Join-Path $env:HPM_SDK_BASE "boards\openocd") `
    -f probes/cmsis_dap.cfg `
    -f soc/hpm5e00.cfg `
    -f (Join-Path $Root "boards\$Board\$Board.cfg") `
    -c "adapter speed $Speed"
