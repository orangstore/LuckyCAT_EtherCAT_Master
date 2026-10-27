#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0

"""flash.py - program LuckyCAT_EtherCAT_Master through a running OpenOCD server.

The OpenOCD telnet server (default 127.0.0.1:4444) must already be running,
see tools/openocd.sh / tools/openocd.ps1.

Examples:
    python tools/flash.py
    python tools/flash.py --elf build/output/LuckyCAT_EtherCAT_Master.elf
    python tools/flash.py --speed 2000 --no-reset
"""

import argparse
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ELF = os.path.join(ROOT, "apps", "LuckyCAT_EtherCAT_Master", "software",
                           "build", "output", "LuckyCAT_EtherCAT_Master.elf")


def read_until(sock, marker=b"> ", timeout=30.0):
    sock.settimeout(0.5)
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
            if marker in buf:
                return buf.decode(errors="replace")
        except socket.timeout:
            continue
    return buf.decode(errors="replace")


def cmd(sock, text, timeout=30.0):
    sock.sendall(text.encode() + b"\r\n")
    return read_until(sock, timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=DEFAULT_ELF, help="firmware ELF to program")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4444)
    ap.add_argument("--speed", type=int, default=1000, help="JTAG/SWD clock in kHz")
    ap.add_argument("--no-reset", action="store_true", help="do not reset/run after flashing")
    args = ap.parse_args()

    # OpenOCD's Tcl parser eats backslashes, always send a forward slash path
    elf = args.elf.replace("\\", "/")

    if not os.path.exists(elf):
        print("ELF not found:", elf)
        print("Build it first with tools/build.sh or tools/build.ps1")
        return 1

    try:
        sock = socket.create_connection((args.host, args.port), 5)
    except OSError as exc:
        print("Cannot connect to OpenOCD at %s:%u (%s)" % (args.host, args.port, exc))
        print("Start it first, e.g. tools/openocd.sh  or  tools/openocd.ps1")
        return 1

    read_until(sock)
    cmd(sock, "adapter speed %u" % args.speed)
    cmd(sock, "reset halt", timeout=10)
    time.sleep(0.3)

    out = cmd(sock, "flash write_image erase %s" % elf, timeout=180)
    if "wrote" not in out:
        print(out.replace("\r", "").strip())
        print("FLASH FAILED")
        return 2

    out = cmd(sock, "verify_image %s" % elf, timeout=180)
    if "verified" not in out:
        print(out.replace("\r", "").strip())
        print("VERIFY FAILED")
        return 3

    for line in out.replace("\r", "").splitlines():
        if "verified" in line:
            print(line.strip())

    if not args.no_reset:
        cmd(sock, "reset run", timeout=10)

    sock.close()
    print("FLASH OK:", elf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
