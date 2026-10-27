#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0

"""serial_monitor.py - console helper for LuckyCAT_EtherCAT_Master.

Reads the board UART (115200 8N1 by default), optionally resets the target
through OpenOCD and/or sends shell commands.

Examples:
    python tools/serial_monitor.py --list
    python tools/serial_monitor.py --port COM5 --seconds 10
    python tools/serial_monitor.py --port COM5 --reset --seconds 8
    python tools/serial_monitor.py --port COM5 --send "motor status" --seconds 3

Requires pyserial:  pip install -r tools/requirements.txt
"""

import argparse
import socket
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is required: pip install -r tools/requirements.txt")
    sys.exit(1)


def openocd_cmd(command, host="127.0.0.1", port=4444):
    try:
        with socket.create_connection((host, port), 3) as sock:
            time.sleep(0.2)
            sock.recv(4096)
            sock.sendall(command.encode() + b"\r\n")
            time.sleep(0.3)
            try:
                sock.recv(4096)
            except socket.timeout:
                pass
        return True
    except OSError as exc:
        print("OpenOCD not reachable (%s), skip '%s'" % (exc, command))
        return False


def pick_port():
    ports = list(list_ports.comports())
    if not ports:
        return None
    preferred = ("usb-serial", "ch340", "cp210", "ft232", "cdc", "acm")
    for p in ports:
        text = (p.description or "").lower()
        if any(k in text for k in preferred):
            return p.device
    return ports[0].device


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--send", action="append", default=[], help="shell command to send (repeatable)")
    ap.add_argument("--send-delay", type=float, default=0.5)
    ap.add_argument("--reset", action="store_true", help="reset the target through OpenOCD first")
    ap.add_argument("--openocd-host", default="127.0.0.1")
    ap.add_argument("--openocd-port", type=int, default=4444)
    ap.add_argument("--log", help="also append the output to this file")
    ap.add_argument("--list", action="store_true", help="list serial ports")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print("%-12s %s  [%s]" % (p.device, p.description, p.hwid))
        return 0

    port = args.port or pick_port()
    if not port:
        print("No serial port found, use --list to inspect the available ports.")
        return 1

    try:
        ser = serial.Serial(port, args.baud, timeout=0.2)
    except Exception as exc:
        print("Cannot open %s: %s" % (port, exc))
        return 1

    log = open(args.log, "a", encoding="utf-8") if args.log else None
    print("== %s @ %u 8N1, %.1fs ==" % (port, args.baud, args.seconds))

    if args.reset:
        openocd_cmd("reset halt", args.openocd_host, args.openocd_port)
        time.sleep(0.2)
        openocd_cmd("resume", args.openocd_host, args.openocd_port)

    for cmd in args.send:
        time.sleep(args.send_delay)
        ser.write((cmd + "\r\n").encode())
        ser.flush()

    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            line = ser.readline()
            if not line:
                continue
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            print(text)
            if log:
                log.write(text + "\n")
                log.flush()
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        if log:
            log.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
