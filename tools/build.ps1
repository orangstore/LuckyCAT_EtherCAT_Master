# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0
# Build LuckyCAT_EtherCAT_Master on Windows (PowerShell).
#
# Required environment variables:
#   HPM_SDK_BASE              path to hpm_sdk (1.13.0)
#   GNURISCV_TOOLCHAIN_PATH   path to the RISC-V GCC toolchain
#
# Usage:
#   .\tools\build.ps1
#   .\tools\build.ps1 -Clean
#   .\tools\build.ps1 -Jobs 4
param(
    [switch]$Clean,
    [int]$Jobs = 8,
    [string]$Board = "hpm5e31_LuckyCAT"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$AppDir = Join-Path $Root "apps\LuckyCAT_EtherCAT_Master\software"
$BuildDir = if ($env:BUILD_DIR) { $env:BUILD_DIR } else { Join-Path $AppDir "build" }

if (-not $env:HPM_SDK_BASE -or -not (Test-Path (Join-Path $env:HPM_SDK_BASE "cmake"))) {
    Write-Error "HPM_SDK_BASE is not set or does not point to an HPM SDK (1.13.0)."
}
if (-not $env:GNURISCV_TOOLCHAIN_PATH -or -not (Test-Path (Join-Path $env:GNURISCV_TOOLCHAIN_PATH "bin"))) {
    Write-Error "GNURISCV_TOOLCHAIN_PATH is not set or does not contain bin\."
}

$SdkEnvRoot = Split-Path -Parent $env:HPM_SDK_BASE
foreach ($d in @("tools\python3", "tools\cmake\bin", "tools\ninja")) {
    $p = Join-Path $SdkEnvRoot $d
    if (Test-Path $p) { $env:PATH = "$p;$env:PATH" }
}
$env:PATH = (Join-Path $env:GNURISCV_TOOLCHAIN_PATH "bin") + ";" + $env:PATH

foreach ($tool in @("cmake", "ninja", "riscv32-unknown-elf-gcc")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "$tool not found in PATH"
    }
}

if ($Clean -and (Test-Path $BuildDir)) {
    Remove-Item -Recurse -Force $BuildDir
}

if (-not (Test-Path (Join-Path $BuildDir "CMakeCache.txt"))) {
    cmake -S $AppDir -B $BuildDir -GNinja `
        -DBOARD=$Board `
        -DBOARD_SEARCH_PATH="$Root/boards" `
        -DHPM_BUILD_TYPE=flash_xip `
        -DCMAKE_BUILD_TYPE=debug
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

cmake --build $BuildDir -j $Jobs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "BUILD OK"
Write-Host "  elf: $BuildDir\output\LuckyCAT_EtherCAT_Master.elf"
Write-Host "  bin: $BuildDir\output\LuckyCAT_EtherCAT_Master.bin"
