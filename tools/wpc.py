#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0

"""wpc.py - minimal ctypes binding for wpcap/Npcap (Windows raw Ethernet I/O).

Only the few calls needed by the virtual EtherCAT slave are wrapped:

    list_devices()            -> [(name, description), ...]
    pick_device(keyword)      -> (name, description)
    PcapDev(name).recv/send

Npcap (https://npcap.com) must be installed. Administrator rights are not
required for send/receive on a normal NIC.
"""

import ctypes
import os

NPCAP_DIR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "Npcap")
if os.path.isdir(NPCAP_DIR):
    os.environ["PATH"] = NPCAP_DIR + ";" + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(NPCAP_DIR)
    except Exception:
        pass


class _timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class PcapPkthdr(ctypes.Structure):
    _fields_ = [("ts", _timeval), ("caplen", ctypes.c_uint), ("len", ctypes.c_uint)]


class PcapIf(ctypes.Structure):
    pass


PcapIf._fields_ = [
    ("next", ctypes.POINTER(PcapIf)),
    ("name", ctypes.c_char_p),
    ("description", ctypes.c_char_p),
    ("addresses", ctypes.c_void_p),
    ("flags", ctypes.c_uint),
]


def _load():
    try:
        lib = ctypes.CDLL("wpcap.dll")
    except OSError:
        raise OSError("wpcap.dll not found, install Npcap first (https://npcap.com)")

    lib.pcap_findalldevs.argtypes = [ctypes.POINTER(ctypes.POINTER(PcapIf)), ctypes.c_char_p]
    lib.pcap_findalldevs.restype = ctypes.c_int
    lib.pcap_freealldevs.argtypes = [ctypes.POINTER(PcapIf)]
    lib.pcap_open_live.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_char_p]
    lib.pcap_open_live.restype = ctypes.c_void_p
    lib.pcap_next_ex.argtypes = [ctypes.c_void_p,
                                 ctypes.POINTER(ctypes.POINTER(PcapPkthdr)),
                                 ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
    lib.pcap_next_ex.restype = ctypes.c_int
    lib.pcap_sendpacket.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
    lib.pcap_sendpacket.restype = ctypes.c_int
    lib.pcap_close.argtypes = [ctypes.c_void_p]
    return lib


_wpcap = None


def wpcap():
    global _wpcap
    if _wpcap is None:
        _wpcap = _load()
    return _wpcap


def list_devices():
    """Return [(name, description), ...] for all pcap devices."""
    lib = wpcap()
    alldevs = ctypes.POINTER(PcapIf)()
    errbuf = ctypes.create_string_buffer(256)
    if lib.pcap_findalldevs(ctypes.byref(alldevs), errbuf) != 0:
        raise OSError(errbuf.value.decode(errors="replace"))
    out = []
    p = alldevs
    while p:
        node = p.contents
        out.append((node.name.decode(errors="replace"),
                    (node.description or b"").decode(errors="replace")))
        p = node.next
    lib.pcap_freealldevs(alldevs)
    return out


def find_device(keyword):
    """Find the first device whose description or name contains keyword."""
    for name, desc in list_devices():
        if keyword.lower() in (desc + " " + name).lower():
            return name, desc
    return None, None


def pick_device(keyword=None):
    """Pick a physical NIC.

    If keyword is given it is matched against the description. Otherwise the
    best candidate is chosen: virtual adapters (Hyper-V, VMware, VirtualBox,
    VPN, loopback, WAN miniport...) are skipped and common wired Ethernet
    controllers are preferred.
    """
    devices = list_devices()
    if keyword:
        name, desc = find_device(keyword)
        if name is None:
            raise OSError("no pcap device matches %r, use --list to see the names" % keyword)
        return name, desc

    skip = ("loopback", "wan miniport", "npcap loopback", "bluetooth",
            "hyper-v", "vmware", "virtualbox", "vbox", "virtual ethernet",
            "tap-", "tun", "vpn", "docker", "wsl", "npcap")
    prefer = ("realtek", "intel", "gigabit", "i225", "i226", "ethernet",
              "killer", "broadcom", "marvell", "usb")

    best = None
    best_score = -999
    for name, desc in devices:
        low = (desc + " " + name).lower()
        if not desc or any(s in low for s in skip):
            continue
        score = 0
        for p in prefer:
            if p in low:
                score += 1
        if "wireless" in low or "wi-fi" in low or "wlan" in low:
            score -= 1
        if score > best_score:
            best, best_score = (name, desc), score

    if best:
        return best
    if devices:
        return devices[0]
    raise OSError("no pcap device found")


class PcapDev:
    def __init__(self, name, promisc=True, timeout_ms=1, snaplen=2048):
        lib = wpcap()
        self.lib = lib
        errbuf = ctypes.create_string_buffer(256)
        self.handle = lib.pcap_open_live(name.encode(), snaplen, 1 if promisc else 0,
                                         timeout_ms, errbuf)
        if not self.handle:
            raise OSError(errbuf.value.decode(errors="replace"))
        self._hdr = ctypes.POINTER(PcapPkthdr)()
        self._data = ctypes.POINTER(ctypes.c_ubyte)()
        self.tx_count = 0
        self.rx_count = 0
        self.tx_err = 0

    def recv(self):
        """Return the next frame as bytes, or None on timeout."""
        # pcap_next_ex: 1 = packet, 0 = timeout, -1 = error, -2 = EOF
        if self.lib.pcap_next_ex(self.handle, ctypes.byref(self._hdr),
                                 ctypes.byref(self._data)) != 1:
            return None
        self.rx_count += 1
        return ctypes.string_at(self._data, self._hdr.contents.caplen)

    def send(self, data):
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        if self.lib.pcap_sendpacket(self.handle, buf, len(data)) == 0:
            self.tx_count += 1
            return True
        self.tx_err += 1
        return False

    def close(self):
        if self.handle:
            self.lib.pcap_close(self.handle)
            self.handle = None


if __name__ == "__main__":
    for n, d in list_devices():
        print("%-64s %s" % (n, d))
