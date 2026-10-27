/*
 * Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * LuckyCAT EtherCAT master application (CherryECAT + CiA402 + OLED UI)
 */
#ifndef ECAT_APP_H
#define ECAT_APP_H

#include "ec_master.h"

/* Create the application task (must be called from a FreeRTOS task) */
void ecat_app_start(ec_master_t *master);

/* Global master instance, shared with the shell command */
extern ec_master_t g_ec_master;

#endif /* ECAT_APP_H */
