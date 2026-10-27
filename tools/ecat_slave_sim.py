#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0

"""
ecat_slave_sim.py - minimal EtherCAT CiA402 slave emulator running on a PC

Why: the LuckyCAT_EtherCAT_Master firmware needs a real slave to exercise bus
scan, PREOP/SAFEOP/OP and CiA402. This script implements a small ESC model
plus a CiA402 application on top of Npcap raw Ethernet frames, so the whole
chain can be validated without a servo drive.

Emulated slave:
  - 4 SyncManagers: SM0/SM1 unused (length 0), SM2 = outputs, SM3 = inputs
  - no mailbox / no CoE (SII mailbox_protocols = 0), the master builds the
    FMMUs directly from the SII SM section
  - no DC (FEATURE bit2 = 0)
  - PDO layout matches the firmware fallback mapping:
        outputs 8 B: controlword (0x6040) @0, target velocity (0x60FF) @2
        inputs  8 B: statusword  (0x6041) @0, position        (0x6064) @2

Usage:
    python ecat_slave_sim.py --list
    python ecat_slave_sim.py                      # auto-select the NIC
    python ecat_slave_sim.py --iface "Ethernet"   # pick by description keyword
    python ecat_slave_sim.py --verbose

Wiring:
    board "ECAT OUT" port -> switch/router -> PC NIC
    (EtherCAT frames are 0x88A4 broadcasts, a plain switch forwards them)
"""

import argparse
import csv
import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ETHERCAT_ETHERTYPE = 0x88A4
BROADCAST = b"\xff" * 6
MY_MAC = b"\x02\x00\x00\x00\x00\x01"

# ------------------------------------------------------------------ ESC 寄存器
REG_TYPE = 0x0000
REG_FMMU_NUM = 0x0004
REG_SYNCM_NUM = 0x0005
REG_RAM_SIZE = 0x0006
REG_PORT_DESC = 0x0007
REG_FEATURE = 0x0008
REG_STATION_ADDR = 0x0010
REG_DL_STAT = 0x0110
REG_AL_CTRL = 0x0120
REG_AL_STAT = 0x0130
REG_AL_STAT_CODE = 0x0134
REG_EEPROM_CFG = 0x0500
REG_EEPROM_CTRL = 0x0502
REG_EEPROM_ADDR = 0x0504
REG_EEPROM_DATA = 0x0508
REG_FMMU0 = 0x0600
REG_SM0 = 0x0800
REG_AL_EVENT = 0x0220

STATE_INIT = 0x01
STATE_PREOP = 0x02
STATE_SAFEOP = 0x04
STATE_OP = 0x08
STATE_NAMES = {
    0x01: "INIT", 0x02: "PREOP", 0x03: "BOOT", 0x04: "SAFEOP", 0x08: "OP", 0x00: "-",
}

# PDO 物理地址（必须与 SII 的 SM 分类一致）
# 从站报 4 个 SM：SM0/SM1 空置（留给 mailbox，长度 0），SM2=输出，SM3=输入。
# 主站 app 用的 sync index 就是 2/3，所以必须凑够 4 个 SM。
SM0_PHYS = 0x1100   # SM2: 输出
SM1_PHYS = 0x1180   # SM3: 输入
PDO_SIZE = 8        # 每个方向 8 字节

# CiA402 PDO 偏移（与主站 app 的 fallback 映射一致）
OFF_CW = 0          # 0x6040 u16
OFF_TV = 2          # 0x60FF i32
OFF_SW = 0          # 0x6041 u16
OFF_POS = 2         # 0x6064 i32


# --------------------------------------------------------------------- SII 镜像
def build_sii(vendor=0x00000F1C, product=0x0000CA40, revision=0x00010000):
    """构造一个最小但合法的 SII（2 Kbit 布局，和主站解析方式对齐）。"""
    size = 1024 * 2
    img = bytearray(b"\xff" * size)

    def put(byte_off, fmt, *vals):
        struct.pack_into(fmt, img, byte_off, *vals)

    def word(word_idx):
        return struct.unpack_from("<H", img, word_idx * 2)[0]

    def set_word(word_idx, val):
        struct.pack_into("<H", img, word_idx * 2, val)

    # 头部：word0 = ESC/PDI 配置
    set_word(0, 0x0C80)
    put(0x04, "<H", 0)             # alias（标准位置）

    # 注意：CherryECAT 的 sii_image 是 uint16_t*，但用它读头部的字节偏移，
    # 所以主站实际读到的位置是标准位置的 2 倍。两套位置都填，兼容两种解析。
    put(0x08, "<I", vendor)        # 标准布局
    put(0x0C, "<I", product)
    put(0x10, "<I", vendor)        # CherryECAT 实际读的位置 (sii_image + 0x08)
    put(0x14, "<I", product)       # + 0x0A
    put(0x18, "<I", revision)      # + 0x0C
    put(0x1C, "<I", 0)             # + 0x0E serial

    # 关键：mailbox_protocols 必须为 0，否则主站认为支持 CoE，
    # 会把 pdo_sm_count 算成 sm_count-2 = 0，PDO 就永远配不起来。
    put(0x38, "<H", 0x0000)        # CherryECAT 实际读的位置 (sii_image + 0x1C)
    put(0x1C, "<H", 0x0000)        # 标准位置（与 serial 重叠，取 0 也无害）

    # 分类目录（字节 0x80 处，见下方说明）
    cat = bytearray()

    def add_cat(cat_type, payload_words):
        cat.extend(struct.pack("<HH", cat_type, len(payload_words)))
        for w in payload_words:
            cat.extend(struct.pack("<H", w))

    # STRINGS: 0 个字符串
    add_cat(0x000A, [0x0000])
    # GENERAL: 32 字节全 0（coe_details 全 0 -> 不做 PDO assign/remap）
    add_cat(0x001E, [0] * 16)
    # SM: 4 个（SM0/SM1 空置长度 0，SM2/SM3 做 PDO），每个 8 字节
    sm_words = []
    for pa, ln, ctrl in ((0x1000, 0, 0x0026),
                         (0x1080, 0, 0x0022),
                         (SM0_PHYS, PDO_SIZE, 0x0064),
                         (SM1_PHYS, PDO_SIZE, 0x0020)):
        sm_words += [pa, ln, ctrl, (0x01 << 8) | 0x00]
    add_cat(0x0029, sm_words)
    # 结束标记
    cat.extend(struct.pack("<HH", 0xFFFF, 0x0000))

    # CherryECAT 扫长度用字地址 0x40、解析用 sii_image(uint16_t*)+0x40，
    # 两者都落在字节 0x80，所以分类表只放一份在这里。
    img[0x80:0x80 + len(cat)] = cat

    # word1 = ones complement checksum of words 0..6 (word1 itself reads as 0
    # while the sum is calculated)
    set_word(1, 0x0000)
    total = 0
    for i in range(7):
        total = (total + word(i)) & 0xFFFF
    set_word(1, (~total) & 0xFFFF)

    return bytes(img)


# ------------------------------------------------------------------- ESC 模型
class VirtualEsc:
    def __init__(self, sii, autoinc_index=0, verbose=False):
        self.mem = bytearray(0x10000)
        self.sii = sii
        self.autoinc_index = autoinc_index
        self.verbose = verbose
        self.station = 0
        self.al_state = STATE_INIT
        self.al_status_code = 0
        self.sii_ptr = 0
        self.pdo_cycles = 0
        self.seen_al_states = []
        self._init_registers()

    # -- 寄存器初始化 ------------------------------------------------------
    def _init_registers(self):
        m = self.mem
        m[REG_TYPE] = 0x11          # ET1100
        m[REG_TYPE + 1] = 0x01
        struct.pack_into("<H", m, 0x0002, 0x0000)
        m[REG_FMMU_NUM] = 8
        m[REG_SYNCM_NUM] = 8
        m[REG_RAM_SIZE] = 0x01
        m[REG_PORT_DESC] = 0x01     # port0 = MII
        struct.pack_into("<H", m, REG_FEATURE, 0x0000)   # 无 DC、无其他特性
        struct.pack_into("<H", m, REG_STATION_ADDR, 0x0000)
        # DL status: port0 link+signal, port1..3 loop closed
        #   link bits 4..7, loop bits 8/10/12/14, signal bits 9/11/13/15
        dl = (1 << 4) | (1 << 9) | (1 << 10) | (1 << 12) | (1 << 14)
        struct.pack_into("<H", m, REG_DL_STAT, dl)
        struct.pack_into("<H", m, REG_AL_STAT, self.al_state)
        struct.pack_into("<H", m, REG_AL_CTRL, 0x0000)
        m[REG_EEPROM_CFG] = 0x00
        struct.pack_into("<H", m, REG_EEPROM_CTRL, 0x0000)

    # -- 状态机 ------------------------------------------------------------
    def on_al_control_write(self, value):
        req = value & 0x000F
        if req == 0:
            return
        if req not in (STATE_INIT, STATE_PREOP, STATE_SAFEOP, STATE_OP, 0x03):
            return
        if req != self.al_state:
            self.al_state = req
            self.al_status_code = 0
            self.seen_al_states.append(req)
            if self.verbose:
                print("  [ESC] AL -> %s" % STATE_NAMES.get(req, hex(req)))
        struct.pack_into("<H", self.mem, REG_AL_STAT, self.al_state)
        struct.pack_into("<H", self.mem, REG_AL_STAT_CODE, 0)

    # -- EEPROM 仿真 -------------------------------------------------------
    def on_eeprom_write(self, data):
        if len(data) < 4:
            return
        cmd = data[1] & 0x0F
        offset = struct.unpack_from("<H", data, 2)[0]
        if cmd == 0x01:              # read
            self.sii_ptr = offset
        # write / reload 一律忽略

    def eeprom_read_block(self, total):
        """返回正好 total 字节：0x502 状态(2) + 0x504 地址(4) + 0x508 数据。"""
        ndata = max(0, total - 6)
        off = self.sii_ptr * 2
        chunk = self.sii[off:off + ndata]
        if len(chunk) < ndata:
            chunk = chunk + b"\xff" * (ndata - len(chunk))
        return b"\x00\x00" + struct.pack("<I", self.sii_ptr) + chunk

    # -- 内存访问 ----------------------------------------------------------
    def read(self, addr, length):
        if addr == REG_EEPROM_CTRL:
            return self.eeprom_read_block(length)
        if addr == REG_AL_STAT:
            struct.pack_into("<H", self.mem, REG_AL_STAT, self.al_state)
        return bytes(self.mem[addr:addr + length])

    def write(self, addr, data):
        if addr == REG_AL_CTRL and len(data) >= 2:
            self.on_al_control_write(struct.unpack_from("<H", data, 0)[0])
        elif addr == REG_STATION_ADDR and len(data) >= 2:
            self.station = struct.unpack_from("<H", data, 0)[0]
            if self.verbose:
                print("  [ESC] station address = %u" % self.station)
        elif addr == REG_EEPROM_CTRL:
            self.on_eeprom_write(data)
        self.mem[addr:addr + len(data)] = data

    # -- FMMU --------------------------------------------------------------
    def fmmu_map(self, logical, length):
        """返回 [(logical_off, phys_addr, nbytes), ...]"""
        out = []
        for i in range(8):
            base = REG_FMMU0 + 16 * i
            if self.mem[base + 0x0C] & 0x01 == 0:      # not active
                continue
            lstart = struct.unpack_from("<I", self.mem, base)[0]
            llen = struct.unpack_from("<H", self.mem, base + 0x04)[0]
            pstart = struct.unpack_from("<H", self.mem, base + 0x08)[0]
            if llen == 0:
                continue
            lo = max(lstart, logical)
            hi = min(lstart + llen, logical + length)
            if hi <= lo:
                continue
            out.append((lo - logical, pstart + (lo - lstart), hi - lo))
        return out

    # -- 数据报 ------------------------------------------------------------
    def handle(self, cmd, addr_bytes, data):
        """处理一个数据报，返回 (new_data, wkc_increment)。"""
        adp = struct.unpack_from("<H", addr_bytes, 0)[0]
        ado = struct.unpack_from("<H", addr_bytes, 2)[0]
        logical = struct.unpack_from("<I", addr_bytes, 0)[0]
        length = len(data)
        match = False
        physical = 0

        if cmd in (0x01, 0x02, 0x03):                     # APRD/APWR/APRW
            match = adp == ((-self.autoinc_index) & 0xFFFF)
            physical = ado
        elif cmd in (0x04, 0x05, 0x06):                   # FPRD/FPWR/FPRW
            match = self.station != 0 and adp == self.station
            physical = ado
        elif cmd in (0x07, 0x08, 0x09):                   # BRD/BWR/BRW
            match = True
            physical = ado
        elif cmd == 0x00:
            return data, 0

        if match:
            if cmd in (0x01, 0x04, 0x07):                 # read
                return self.read(physical, length), 1
            if cmd in (0x02, 0x05, 0x08):                 # write
                self.write(physical, data)
                return data, 1
            # APRW/FPRW/BRW: read then write
            old = self.read(physical, length)
            self.write(physical, data)
            return old, 2

        # 逻辑寻址（LRD/LWR/LRW/ARMW/FRMW）
        if cmd in (0x0A, 0x0B, 0x0C, 0x0D, 0x0E):
            maps = self.fmmu_map(logical, length)
            if cmd in (0x0D, 0x0E):                        # ARMW/FRMW: 只算一次
                maps = maps[:1]
            if not maps:
                return data, 0
            buf = bytearray(data)
            for off, phys, n in maps:
                buf[off:off + n] = self.mem[phys:phys + n]
            if cmd in (0x0B, 0x0C):                        # LWR/LRW 顺带写入
                for off, phys, n in maps:
                    self.mem[phys:phys + n] = data[off:off + n]
            if cmd == 0x0B:
                return data, len(maps)
            if cmd == 0x0C:
                self.pdo_cycles += 1
                return bytes(buf), 3
            return bytes(buf), len(maps)

        return data, 0


# ---------------------------------------------------------------- CiA402 应用
class Cia402App:
    """放在 ESC 进程数据后面的最小 CiA402 从站应用。"""

    def __init__(self, esc, accel=2000):
        self.esc = esc
        self.state = "SWITCH_ON_DISABLED"
        self.position = 0
        self.velocity = 0
        self.target_velocity = 0
        self.accel = accel            # counts/s^2
        self.last_t = time.time()
        self.statusword = 0x0040
        self.remote = 0x0200          # bit9: remote
        self.mode = 9                 # CSV

    def status(self):
        base = {
            "NOT_READY": 0x0000,
            "SWITCH_ON_DISABLED": 0x0040,
            "READY": 0x0021,
            "SWITCHED_ON": 0x0023,
            "OP_ENABLED": 0x0027,
            "FAULT": 0x0008,
        }[self.state]
        sw = base | self.remote
        if self.state == "OP_ENABLED" and abs(self.velocity - self.target_velocity) < 1:
            sw |= 0x0400              # bit10: target reached
        return sw & 0xFFFF

    def step(self, _ignored=None):
        m = self.esc.mem
        cw = struct.unpack_from("<H", m, SM0_PHYS + OFF_CW)[0]

        # CiA402 控制字译码（简化但符合标准迁移）
        if cw & 0x0080:               # fault reset
            if self.state == "FAULT":
                self.state = "SWITCH_ON_DISABLED"
        elif (cw & 0x000F) == 0x00:
            self.state = "SWITCH_ON_DISABLED"
        elif (cw & 0x000F) == 0x06:   # shutdown
            if self.state in ("SWITCH_ON_DISABLED", "SWITCHED_ON", "OP_ENABLED"):
                self.state = "READY"
        elif (cw & 0x000F) == 0x07:   # switch on
            if self.state == "READY":
                self.state = "SWITCHED_ON"
        elif (cw & 0x000F) == 0x0F:   # enable operation
            if self.state == "SWITCHED_ON":
                self.state = "OP_ENABLED"
        elif (cw & 0x0002) and not (cw & 0x0004):   # quick stop
            self.state = "SWITCH_ON_DISABLED"

        # 读输出 / 写输入
        tv = struct.unpack_from("<i", m, SM0_PHYS + OFF_TV)[0]
        self.target_velocity = tv

        now = time.time()
        dt = now - self.last_t
        self.last_t = now
        if self.state == "OP_ENABLED":
            dv = self.accel * dt * 5.0
            if self.velocity < self.target_velocity:
                self.velocity = min(self.velocity + dv, self.target_velocity)
            elif self.velocity > self.target_velocity:
                self.velocity = max(self.velocity - dv, self.target_velocity)
        else:
            self.velocity = 0
        self.position += int(self.velocity * dt)

        struct.pack_into("<H", m, SM1_PHYS + OFF_SW, self.status())
        struct.pack_into("<i", m, SM1_PHYS + OFF_POS, int(self.position))
        self.statusword = self.status()
        return cw


# --------------------------------------------------------------------- 主程序
def get_mac_for_guid(guid):
    """用 getmac 取本机网卡 MAC，按 GUID 精确匹配。"""
    try:
        out = subprocess.run(["getmac", "/v", "/fo", "csv"],
                             capture_output=True, timeout=10)
        txt = out.stdout.decode("gbk", errors="replace")
        for row in csv.reader(txt.splitlines()):
            if len(row) >= 4 and guid.lower() in row[3].lower():
                mac = row[2].replace("-", "").replace(":", "")
                if len(mac) == 12:
                    return bytes.fromhex(mac)
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iface", default=None, help="网卡名/描述里的关键字，缺省自动选择")
    ap.add_argument("--list", action="store_true", help="列出网卡")
    ap.add_argument("--verbose", action="store_true", help="逐条打印数据报")
    ap.add_argument("--quiet-pdo", action="store_true", help="不打印 PDO 变化")
    args = ap.parse_args()

    if args.list:
        from wpc import list_devices
        for n, d in list_devices():
            print("%-60s %s" % (n, d))
        return

    from wpc import PcapDev, list_devices, pick_device

    try:
        name, desc = pick_device(args.iface)
    except OSError as exc:
        print("网卡选择失败:", exc)
        for n, d in list_devices():
            print("  %-58s %s" % (n, d))
        raise SystemExit(1)

    global MY_MAC
    guid = name.split("{")[-1].rstrip("}") if "{" in name else ""
    mac = get_mac_for_guid(guid)
    if mac:
        MY_MAC = mac

    dev = PcapDev(name)
    print("== 虚拟 EtherCAT 从站 ==")
    print("网卡:", desc)
    print("设备:", name)
    print("MAC :", ":".join("%02X" % b for b in MY_MAC))

    esc = VirtualEsc(build_sii(), verbose=True)
    app = Cia402App(esc)
    print("SII : VID=0x%08X, SM0=0x%04X SM1=0x%04X, PDO %u+%u B"
          % (0x00000F1C, SM0_PHYS, SM1_PHYS, PDO_SIZE, PDO_SIZE))
    print("等待主站扫描... (Ctrl+C 结束)")

    last_report = time.time()
    cw_prev = sw_prev = None
    frames = 0
    bad_len = 0
    board_mac = None

    while True:
        try:
            raw = dev.recv()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print("接收异常:", exc)
            break
        if raw is None:
            continue
        if len(raw) < 18:
            continue
        if raw[12:14] != b"\x88\xa4":
            continue
        if raw[0:6] == MY_MAC:      # 本机发出的帧，丢弃防回环
            continue

        if board_mac is None:
            board_mac = raw[6:12]
            print("发现主站 MAC:", ":".join("%02X" % b for b in board_mac))

        body = bytearray(raw)
        dg_len = struct.unpack_from("<H", body, 14)[0] & 0x07FF
        if dg_len > len(body) - 14:
            bad_len += 1
            continue
        pos = 16
        end = min(16 + dg_len, len(body))
        modified = False
        lrw_spans = []
        frames += 1

        while pos + 12 <= end:
            cmd = body[pos]
            idx = body[pos + 1]
            addr = bytes(body[pos + 2:pos + 6])
            ln_flags = struct.unpack_from("<H", body, pos + 6)[0]
            dlen = ln_flags & 0x07FF
            more = ln_flags & 0x8000
            data_off = pos + 10
            if data_off + dlen + 2 > len(body):
                break
            data = bytes(body[data_off:data_off + dlen])
            wkc_off = data_off + dlen
            old_wkc = struct.unpack_from("<H", body, wkc_off)[0]

            if cmd == 0x0C:
                lrw_spans.append((data_off, struct.unpack_from("<I", addr, 0)[0], dlen))

            new_data, wkc_inc = esc.handle(cmd, addr, data)
            if wkc_inc:
                if new_data != data and len(new_data) == dlen:
                    body[data_off:data_off + dlen] = new_data
                struct.pack_into("<H", body, wkc_off, (old_wkc + wkc_inc) & 0xFFFF)
                modified = True
                if args.verbose:
                    print("  dg cmd=0x%02X idx=%u len=%u wkc+%u" % (cmd, idx, dlen, wkc_inc))

            pos = data_off + dlen + 2
            if not more:
                break

        if not modified:
            continue

        cw = app.step(None)
        for data_off, logical, dlen in lrw_spans:
            for off, phys, n in esc.fmmu_map(logical, dlen):
                body[data_off + off:data_off + off + n] = esc.mem[phys:phys + n]

        if (not args.quiet_pdo) and (cw != cw_prev or app.statusword != sw_prev):
            cw_prev, sw_prev = cw, app.statusword
            print("  CiA402: cw=0x%04X sw=0x%04X state=%-18s tv=%d v=%d pos=%d"
                  % (cw, app.statusword, app.state, app.target_velocity,
                     int(app.velocity), app.position))

        reply = bytearray(body)
        reply[0:6] = raw[6:12]
        reply[6:12] = MY_MAC
        dev.send(bytes(reply))

        now = time.time()
        if now - last_report >= 2.0:
            last_report = now
            print("  [al=%s] PDO=%u frames=%u rx=%u tx=%u txerr=%u badlen=%u pos=%d v=%d"
                  % (STATE_NAMES.get(esc.al_state), esc.pdo_cycles, frames,
                     dev.rx_count, dev.tx_count, dev.tx_err, bad_len,
                     app.position, int(app.velocity)))

    dev.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出")
