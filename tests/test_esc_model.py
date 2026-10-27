#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the virtual EtherCAT slave model (tools/ecat_slave_sim.py).

These tests do not touch the network or the board: they exercise the ESC
register model, the SII image layout and the CiA402 state machine directly.

Run from the repository root:

    python -m unittest discover -s tests -v
    python tests/run_tests.py
"""

import os
import struct
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ecat_slave_sim as sim  # noqa: E402


def addr(adp, ado):
    return struct.pack("<HH", adp, ado)


class SiiImageTest(unittest.TestCase):
    def setUp(self):
        self.img = sim.build_sii()

    def test_header_offsets_used_by_cherryecat(self):
        # CherryECAT reads the header through a uint16_t pointer with byte
        # offsets, so the values land at twice the standard position.
        self.assertEqual(struct.unpack_from("<I", self.img, 0x10)[0], 0x00000F1C)
        self.assertEqual(struct.unpack_from("<I", self.img, 0x14)[0], 0x0000CA40)
        self.assertEqual(struct.unpack_from("<H", self.img, 0x38)[0], 0x0000)

    def test_categories_are_at_byte_0x80(self):
        off = 0x80
        types = []
        for _ in range(8):
            cat_type, size = struct.unpack_from("<HH", self.img, off)
            types.append(cat_type)
            if cat_type == 0xFFFF:
                break
            off += 4 + size * 2
        self.assertEqual(types[:3], [0x000A, 0x001E, 0x0029])

    def test_sync_managers(self):
        off = self.img.find(struct.pack("<H", 0x0029))
        self.assertGreater(off, 0)
        size = struct.unpack_from("<H", self.img, off + 2)[0]
        self.assertEqual(size * 2 // 8, 4, "the master app uses sync index 2/3")

        entries = []
        for i in range(4):
            base = off + 4 + i * 8
            pa, ln, ctrl = struct.unpack_from("<HHH", self.img, base)
            entries.append((pa, ln, ctrl))

        self.assertEqual(entries[0][1], 0)
        self.assertEqual(entries[1][1], 0)
        self.assertEqual(entries[2][0], sim.SM0_PHYS)
        self.assertEqual(entries[2][1], sim.PDO_SIZE)
        self.assertEqual(entries[3][0], sim.SM1_PHYS)
        self.assertEqual(entries[3][1], sim.PDO_SIZE)

    def test_checksum_word(self):
        # word1 is the ones complement of words 0, 2..6, so the 16-bit sum of
        # the whole configuration header must be 0xFFFF
        words = struct.unpack_from("<7H", self.img, 0)
        self.assertEqual(sum(words) & 0xFFFF, 0xFFFF)

        partial = (words[0] + sum(words[2:])) & 0xFFFF
        self.assertEqual(words[1], (~partial) & 0xFFFF)


class EscModelTest(unittest.TestCase):
    def setUp(self):
        self.esc = sim.VirtualEsc(sim.build_sii())

    def test_broadcast_read_al_status(self):
        data, wkc = self.esc.handle(0x07, addr(0, sim.REG_AL_STAT), b"\x00\x00")
        self.assertEqual(wkc, 1)
        self.assertEqual(struct.unpack_from("<H", data, 0)[0], sim.STATE_INIT)

    def test_auto_increment_station_address(self):
        _, wkc = self.esc.handle(0x02, addr(0, sim.REG_STATION_ADDR), struct.pack("<H", 1001))
        self.assertEqual(wkc, 1)
        self.assertEqual(self.esc.station, 1001)

        # now only the assigned station answers
        _, wkc = self.esc.handle(0x04, addr(1001, sim.REG_AL_STAT), b"\x00\x00")
        self.assertEqual(wkc, 1)
        _, wkc = self.esc.handle(0x04, addr(1002, sim.REG_AL_STAT), b"\x00\x00")
        self.assertEqual(wkc, 0)

    def test_fprd_type_register(self):
        self.esc.handle(0x02, addr(0, sim.REG_STATION_ADDR), struct.pack("<H", 1001))
        data, wkc = self.esc.handle(0x04, addr(1001, sim.REG_TYPE), b"\x00" * 12)
        self.assertEqual(wkc, 1)
        self.assertEqual(data[0], 0x11)
        self.assertEqual(data[4], 8)   # FMMU count
        self.assertEqual(data[5], 8)   # SM count

    def test_eeprom_read_returns_requested_length(self):
        self.esc.handle(0x02, addr(0, sim.REG_STATION_ADDR), struct.pack("<H", 1001))
        # read command, word offset 0x40 -> byte offset 0x80 (STRINGS category)
        self.esc.handle(0x05, addr(1001, sim.REG_EEPROM_CTRL),
                        bytes([0x80, 0x01, 0x40, 0x00]))
        data, wkc = self.esc.handle(0x04, addr(1001, sim.REG_EEPROM_CTRL), b"\x00" * 10)
        self.assertEqual(wkc, 1)
        self.assertEqual(len(data), 10)
        self.assertEqual(struct.unpack_from("<H", data, 0)[0], 0x0000)
        self.assertEqual(struct.unpack_from("<H", data, 6)[0], 0x000A)

    def test_al_state_machine(self):
        self.esc.handle(0x02, addr(0, sim.REG_STATION_ADDR), struct.pack("<H", 1001))
        for state in (sim.STATE_PREOP, sim.STATE_SAFEOP, sim.STATE_OP):
            self.esc.handle(0x05, addr(1001, sim.REG_AL_CTRL), struct.pack("<H", state))
            data, _ = self.esc.handle(0x04, addr(1001, sim.REG_AL_STAT), b"\x00\x00")
            self.assertEqual(struct.unpack_from("<H", data, 0)[0], state)
        self.assertEqual(self.esc.seen_al_states,
                         [sim.STATE_PREOP, sim.STATE_SAFEOP, sim.STATE_OP])

    def test_invalid_al_request_is_ignored(self):
        self.esc.handle(0x05, addr(0, sim.REG_AL_CTRL), struct.pack("<H", 0x0006))
        self.assertEqual(self.esc.al_state, sim.STATE_INIT)


class PdoTest(unittest.TestCase):
    def setUp(self):
        self.esc = sim.VirtualEsc(sim.build_sii())
        self.esc.station = 1001
        self._program_mappings()

    def _program_mappings(self):
        # SM2 = outputs (write), SM3 = inputs (read), 8 bytes each
        sm = struct.pack("<HHBBBB", sim.SM0_PHYS, sim.PDO_SIZE, 0x0064, 0, 1, 0)
        self.esc.handle(0x05, addr(1001, sim.REG_SM0), sm)
        sm = struct.pack("<HHBBBB", sim.SM1_PHYS, sim.PDO_SIZE, 0x0020, 0, 1, 0)
        self.esc.handle(0x05, addr(1001, sim.REG_SM0 + 8), sm)

        # FMMU0: logical 0..7  -> 0x1100, FMMU1: logical 8..15 -> 0x1180
        for i, (lstart, pstart) in enumerate(((0, sim.SM0_PHYS), (8, sim.SM1_PHYS))):
            entry = struct.pack("<IHBBHBBB", lstart, 8, 0, 0x07, pstart, 0, 0x02, 1) + b"\x00\x00\x00"
            self.esc.handle(0x05, addr(1001, sim.REG_FMMU0 + 16 * i), entry)

    def test_lrw_exchanges_outputs_and_inputs(self):
        # 8 bytes of outputs + 8 bytes of inputs
        out = struct.pack("<Hi", 0x000F, 3000) + b"\x00" * 10
        data, wkc = self.esc.handle(0x0C, struct.pack("<I", 0), out)
        self.assertEqual(wkc, 3)
        self.assertEqual(len(data), 16)
        # outputs must have landed in the SM2 memory
        self.assertEqual(struct.unpack_from("<H", self.esc.mem, sim.SM0_PHYS)[0], 0x000F)
        self.assertEqual(struct.unpack_from("<i", self.esc.mem, sim.SM0_PHYS + 2)[0], 3000)

    def test_lrw_without_fmmu_has_zero_wkc(self):
        esc = sim.VirtualEsc(sim.build_sii())
        esc.station = 1001
        data, wkc = esc.handle(0x0C, struct.pack("<I", 0), b"\x00" * 16)
        self.assertEqual(wkc, 0)
        self.assertEqual(data, b"\x00" * 16)


class Cia402Test(unittest.TestCase):
    def setUp(self):
        self.esc = sim.VirtualEsc(sim.build_sii())
        self.esc.station = 1001
        PdoTest._program_mappings(self)
        self.app = sim.Cia402App(self.esc)

    def _write_cw(self, cw, target=0):
        out = struct.pack("<Hi", cw, target) + b"\x00\x00"
        self.esc.handle(0x0C, struct.pack("<I", 0), out)

    def test_enable_sequence(self):
        self.assertEqual(self.app.state, "SWITCH_ON_DISABLED")
        for cw, expected in ((0x0006, "READY"), (0x0007, "SWITCHED_ON"), (0x000F, "OP_ENABLED")):
            self._write_cw(cw)
            self.app.step()
            self.assertEqual(self.app.state, expected)

    def test_statusword_bits(self):
        for cw in (0x0006, 0x0007, 0x000F):
            self._write_cw(cw)
            self.app.step()

        self.assertTrue(self.app.statusword & 0x0004, "operation enabled")
        self.assertTrue(self.app.statusword & 0x0200, "remote")

    def test_velocity_ramp_and_position(self):
        for cw in (0x0006, 0x0007, 0x000F):
            self._write_cw(cw)
            self.app.step()

        start = self.app.position
        for _ in range(40):
            self._write_cw(0x000F, 1000)
            self.app.step()
            time.sleep(0.01)

        self.assertGreater(self.app.velocity, 0)
        self.assertLessEqual(self.app.velocity, 1000)
        self.assertGreater(self.app.position, start)
        # target reached once the ramp is done
        self.assertTrue(self.app.statusword & 0x0400)

    def test_quick_stop_disables(self):
        for cw in (0x0006, 0x0007, 0x000F):
            self._write_cw(cw)
            self.app.step()
        self._write_cw(0x0002)
        self.app.step()
        self.assertEqual(self.app.state, "SWITCH_ON_DISABLED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
