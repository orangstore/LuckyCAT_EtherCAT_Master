#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
# SPDX-License-Identifier: Apache-2.0

"""Run all offline tests for LuckyCAT_EtherCAT_Master."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")


def main():
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", TESTS, "-v"]
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
