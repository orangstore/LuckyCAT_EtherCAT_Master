/*
 * Copyright (c) 2025 LuckyCAT_EtherCAT_Master contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * EtherCAT master application for the LuckyCAT (HPM5E31) board:
 *   - CherryECAT master on ENET0 (MII + JL1111)
 *   - CiA402 cyclic synchronous velocity control (0x1602/0x1A02 mapping)
 *   - SSD1306 OLED status display + on-board keys
 *   - shell commands: ethercat (CherryECAT built-in), motor
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

#include "board.h"
#include "FreeRTOS.h"
#include "task.h"
#include "hpm_gpio_drv.h"
#include "hpm_enet_drv.h"

#include "ec_master.h"
#include "cia402_def.h"
#include "ecat_app.h"
#include "oled.h"
#include "shell.h"

extern volatile uint32_t g_ec_netdev_tx_stall;
extern volatile uint32_t g_ec_netdev_tx_queued;
extern volatile uint32_t g_ec_netdev_tx_done;
extern volatile uint32_t g_ec_netdev_tx_recycled;

/* Default PDO cycle in microseconds.
 *
 * 4000 us is a safe default for bring-up: when the slave is the Python
 * simulator running on a PC, a reply takes 1~2 ms and a 1 ms cycle would be
 * missed. With a real servo set it back to 1000 us, either by editing this
 * macro or at runtime with "motor cycle 1000" before starting the master. */
#ifndef APP_CYCLE_TIME_US
#define APP_CYCLE_TIME_US     (4000U)
#endif

/* JL1111 PHY of the "ECAT OUT" port (MDIO address 2) */
#define ENET_PHY_ADDR_DATA    (2U)

#define APP_MAX_SLAVES        (8U)
#define APP_TASK_STACK_SIZE   (1024U)
#define APP_TASK_PRIORITY     (4U)
#define APP_POLL_PERIOD_MS    (50U)
#define APP_UI_PERIOD_MS      (200U)

/* velocity ramp step per 1 ms cycle (user units per second) */
#define APP_VEL_RAMP_STEP     (5)
#define APP_VEL_DEFAULT       (60)
#define APP_VEL_MAX           (2000)

/* runtime adjustable PDO cycle, see "motor cycle" */
static uint32_t s_cycle_us = APP_CYCLE_TIME_US;

typedef struct {
    int16_t cw_off;
    int16_t tv_off;
    int16_t sw_off;
    int16_t pos_off;
    int16_t vel_off;
    uint16_t osize;
    uint16_t isize;
    bool valid;
} pdo_layout_t;

typedef struct {
    ec_master_t *master;

    pdo_layout_t layout;

    volatile uint32_t cycles;
    volatile uint32_t wkc_actual;
    volatile uint32_t wkc_expected;
    volatile uint16_t controlword;
    volatile uint16_t statusword;
    volatile int32_t position;
    volatile int32_t target_velocity; /* ramped value actually sent to the slave */
    volatile uint8_t slave_state;
    volatile bool run_request;

    int32_t cmd_velocity;   /* requested velocity */
    int32_t velocity_actual;/* derived from position */
    int32_t last_position;
    uint32_t last_sample_ms;

    bool auto_start_done;
    bool auto_start_failed;
    bool last_link;
    uint32_t last_rescan_ms;
    uint32_t key_a_cnt;
    uint32_t key_b_cnt;
    bool key_a_level;
    bool key_b_level;

    char msg[32];
} app_ctx_t;

static app_ctx_t s_app;

/* ------------------------------------------------------------------------- */
/* CiA402 state machine (runs in the EtherCAT cyclic context)                */
/* ------------------------------------------------------------------------- */
static uint16_t cia402_step(uint16_t statusword, bool run)
{
    static uint32_t fault_reset_cnt;

    uint16_t state = statusword & STATUSWORD_STATE_MASK;

    if (state == STATUSWORD_STATE_FAULT) {
        /* toggle fault reset bit until the drive leaves the fault state */
        fault_reset_cnt++;
        if ((fault_reset_cnt % 200U) < 100U) {
            return CONTROLWORD_COMMAND_FAULTRESET;
        }
        return 0x0000;
    }
    fault_reset_cnt = 0;

    switch (state) {
    case STATUSWORD_STATE_NOTREADYTOSWITCHON:
        /* wait for the drive to finish its self test */
        return 0x0000;
    case STATUSWORD_STATE_SWITCHEDONDISABLED:
        return CONTROLWORD_COMMAND_SHUTDOWN;
    case STATUSWORD_STATE_READYTOSWITCHON:
        return CONTROLWORD_COMMAND_SWITCHON;
    case STATUSWORD_STATE_SWITCHEDON:
        return run ? CONTROLWORD_COMMAND_ENABLEOPERATION : CONTROLWORD_COMMAND_SWITCHON;
    case STATUSWORD_STATE_OPERATIONENABLED:
        return run ? CONTROLWORD_COMMAND_ENABLEOPERATION : CONTROLWORD_COMMAND_SHUTDOWN;
    case STATUSWORD_STATE_QUICKSTOPACTIVE:
        return CONTROLWORD_COMMAND_DISABLEOPERATION;
    case STATUSWORD_STATE_FAULTREACTIONACTIVE:
        return 0x0000;
    default:
        return CONTROLWORD_COMMAND_SHUTDOWN;
    }
}

/* Strong override of the weak callback in ec_cmd.c */
void ec_pdo_callback(ec_slave_t *slave, uint8_t *output, uint8_t *input)
{
    app_ctx_t *app = &s_app;
    pdo_layout_t *l = &app->layout;

    if (slave->index != 0) {
        return;
    }

    app->cycles++;
    app->slave_state = slave->current_state;
    /* 注意：回调是在 master->actual_working_counter 被赋值之前调用的，
     * 这里直接取 PDO 数据报自己的 WKC，否则永远读成 0。 */
    app->wkc_actual = slave->master->pdo_datagram.working_counter;
    app->wkc_expected = slave->master->expected_working_counter;

    if (!l->valid) {
        return;
    }

    uint16_t sw = EC_READ_U16(input + l->sw_off);
    uint16_t cw = cia402_step(sw, app->run_request);

    int32_t goal = app->run_request ? app->cmd_velocity : 0;
    int32_t vel = app->target_velocity;

    if (vel < goal) {
        vel += APP_VEL_RAMP_STEP;
        if (vel > goal) {
            vel = goal;
        }
    } else if (vel > goal) {
        vel -= APP_VEL_RAMP_STEP;
        if (vel < goal) {
            vel = goal;
        }
    }

    app->target_velocity = vel;

    EC_WRITE_U16(output + l->cw_off, cw);
    if (l->tv_off >= 0) {
        EC_WRITE_U32(output + l->tv_off, (uint32_t)vel);
    }

    app->controlword = cw;
    app->statusword = sw;

    if (l->pos_off >= 0) {
        app->position = (int32_t)EC_READ_U32(input + l->pos_off);
    }
}

/* ------------------------------------------------------------------------- */
/* PDO mapping inspection                                                    */
/* ------------------------------------------------------------------------- */
static void layout_from_syncs(const ec_sync_info_t *syncs, uint8_t sync_count, pdo_layout_t *l)
{
    memset(l, 0, sizeof(*l));
    l->cw_off = -1;
    l->tv_off = -1;
    l->sw_off = -1;
    l->pos_off = -1;
    l->vel_off = -1;

    for (uint8_t i = 0; i < sync_count; i++) {
        uint32_t bit_off = 0;

        for (uint32_t p = 0; p < syncs[i].n_pdos; p++) {
            const ec_pdo_info_t *pdo = &syncs[i].pdos[p];

            for (uint32_t e = 0; e < pdo->n_entries; e++) {
                const ec_pdo_entry_info_t *entry = &pdo->entries[e];
                int16_t byte_off = (int16_t)(bit_off / 8);

                if (syncs[i].dir == EC_DIR_OUTPUT) {
                    if (entry->index == 0x6040 && entry->subindex == 0) {
                        l->cw_off = byte_off;
                    } else if (entry->index == 0x60FF && entry->subindex == 0) {
                        l->tv_off = byte_off;
                    }
                } else {
                    if (entry->index == 0x6041 && entry->subindex == 0) {
                        l->sw_off = byte_off;
                    } else if (entry->index == 0x6064 && entry->subindex == 0) {
                        l->pos_off = byte_off;
                    } else if (entry->index == 0x606C && entry->subindex == 0) {
                        l->vel_off = byte_off;
                    }
                }
                bit_off += entry->bit_length;
            }
        }

        if (syncs[i].dir == EC_DIR_OUTPUT) {
            l->osize = (uint16_t)(bit_off / 8);
        } else {
            l->isize = (uint16_t)(bit_off / 8);
        }
    }

    l->valid = (l->cw_off >= 0) && (l->sw_off >= 0) && (l->tv_off >= 0);
}

/* Fallback mapping used when the slave is not in CherryECAT's device table:
 * standard CiA402 RxPDO2/TxPDO2 (controlword + target velocity) */
static ec_pdo_entry_info_t fb_out_entries[] = {
    { 0x6040, 0x00, 0x10 },
    { 0x60FF, 0x00, 0x20 },
    { 0x0000, 0x00, 0x10 },
};

static ec_pdo_entry_info_t fb_in_entries[] = {
    { 0x6041, 0x00, 0x10 },
    { 0x6064, 0x00, 0x20 },
    { 0x0000, 0x00, 0x10 },
};

static ec_pdo_info_t fb_rxpdo[] = {
    { 0x1602, 3, fb_out_entries },
};

static ec_pdo_info_t fb_txpdo[] = {
    { 0x1A02, 3, fb_in_entries },
};

static ec_sync_info_t fb_syncs[] = {
    { 2, EC_DIR_OUTPUT, 1, fb_rxpdo },
    { 3, EC_DIR_INPUT, 1, fb_txpdo },
};

static ec_slave_config_t s_slave_cfg[APP_MAX_SLAVES];

static void app_log(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(s_app.msg, sizeof(s_app.msg), fmt, ap);
    va_end(ap);

    printf("%s\r\n", s_app.msg);
}

static int app_configure_and_start(void)
{
    ec_master_t *master = s_app.master;

    if (!master->scan_done || master->slave_count == 0) {
        return -1;
    }

    if (master->slave_count > APP_MAX_SLAVES) {
        app_log("Too many slaves: %u", (unsigned)master->slave_count);
        return -1;
    }

    for (uint32_t i = 0; i < master->slave_count; i++) {
        ec_sync_info_t *syncs = NULL;
        uint8_t sync_count = 0;
        bool fallback = false;

        if (ec_master_find_slave_sync_info(master->slaves[i].sii.vendor_id,
                                           master->slaves[i].sii.product_code,
                                           master->slaves[i].sii.revision_number,
                                           EC_CIA402_OPERATION_MODE_CSV,
                                           &syncs,
                                           &sync_count) != 0) {
            syncs = fb_syncs;
            sync_count = sizeof(fb_syncs) / sizeof(fb_syncs[0]);
            fallback = true;
        }

        memset(&s_slave_cfg[i], 0, sizeof(s_slave_cfg[i]));
        /* DC is only used when the slave really supports it. A slave without DC
         * (e.g. a PC-side ESC emulator) would otherwise trip the master's
         * "slave does not support DC" assertion. */
        s_slave_cfg[i].dc_assign_activate = master->slaves[i].base_dc_supported ? 0x300 : 0;
        s_slave_cfg[i].dc_sync[0].cycle_time = s_cycle_us * 1000;
        s_slave_cfg[i].dc_sync[0].shift_time = 1000000;
        s_slave_cfg[i].dc_sync[1].cycle_time = 0;
        s_slave_cfg[i].dc_sync[1].shift_time = 0;
        s_slave_cfg[i].sync = syncs;
        s_slave_cfg[i].sync_count = sync_count;
        s_slave_cfg[i].pdo_callback = ec_pdo_callback;

        master->slaves[i].config = &s_slave_cfg[i];

        if (i == 0) {
            layout_from_syncs(syncs, sync_count, &s_app.layout);
        }

        printf("Slave %u: VID 0x%08X PID 0x%08X rev 0x%08X%s\r\n",
               (unsigned)i,
               (unsigned)master->slaves[i].sii.vendor_id,
               (unsigned)master->slaves[i].sii.product_code,
               (unsigned)master->slaves[i].sii.revision_number,
               fallback ? " (fallback mapping)" : "");

        /* 只有从站真的支持 CoE 且 mailbox 已配置好，才发 SDO；
         * 否则 ec_coe_download 会因为 rx mailbox 为 0 触发断言。 */
        bool coe_ready = ((master->slaves[i].sii.mailbox_protocols & EC_MBXPROT_COE) != 0) &&
                         (master->slaves[i].configured_rx_mailbox_size > 0);

        if (s_app.layout.valid && coe_ready) {
            /* select cyclic synchronous velocity mode (0x6060 = 9) */
            ec_datagram_t datagram;
            uint8_t operation_mode = CYCLIC_SYNC_VELOCITY_MODE;

            ec_datagram_init(&datagram, 1024);
            int ret = ec_coe_download(master, i, &datagram, 0x6060, 0x00,
                                      &operation_mode, 1, false);
            ec_datagram_clear(&datagram);

            if (ret < 0) {
                printf("Slave %u: set 0x6060=9 failed (%d)\r\n", (unsigned)i, ret);
            } else {
                printf("Slave %u: operation mode set to CSV (9)\r\n", (unsigned)i);
            }
        } else if (s_app.layout.valid) {
            printf("Slave %u: no CoE mailbox, skip 0x6060 (assuming CSV)\r\n", (unsigned)i);
        }
    }

    if (!s_app.layout.valid) {
        app_log("No CiA402 PDO mapping found");
        return -1;
    }

    master->cycle_time = s_cycle_us * 1000;
    master->shift_time = s_cycle_us * 1000 * 0.2;
    master->dc_sync_with_dc_ref_enable = (master->dc_ref_clock != NULL);

    printf("Starting EtherCAT cyclic operation, cycle = %u us\r\n", (unsigned)s_cycle_us);
    if (ec_master_start(master) != 0) {
        app_log("ec_master_start failed");
        return -1;
    }

    return 0;
}

/* ------------------------------------------------------------------------- */
/* Keys / state polling                                                      */
/* ------------------------------------------------------------------------- */
static void app_poll_keys(void)
{
    bool a = gpio_read_pin(BOARD_KEYA_GPIO_CTRL, BOARD_KEYA_GPIO_INDEX, BOARD_KEYA_GPIO_PIN)
             == BOARD_BUTTON_PRESSED_VALUE;
    bool b = gpio_read_pin(BOARD_KEYB_GPIO_CTRL, BOARD_KEYB_GPIO_INDEX, BOARD_KEYB_GPIO_PIN)
             == BOARD_BUTTON_PRESSED_VALUE;

    if (a) {
        if (!s_app.key_a_level && ++s_app.key_a_cnt >= 2) {
            s_app.key_a_cnt = 0;
            s_app.run_request = !s_app.run_request;
            printf("KEYA: motor %s\r\n", s_app.run_request ? "ENABLE" : "DISABLE");
        }
    } else {
        s_app.key_a_cnt = 0;
    }
    s_app.key_a_level = a;

    if (b) {
        if (!s_app.key_b_level && ++s_app.key_b_cnt >= 2) {
            s_app.key_b_cnt = 0;
            if (s_app.cmd_velocity < 30) {
                s_app.cmd_velocity = 30;
            } else if (s_app.cmd_velocity < 60) {
                s_app.cmd_velocity = 60;
            } else if (s_app.cmd_velocity < 120) {
                s_app.cmd_velocity = 120;
            } else if (s_app.cmd_velocity < 240) {
                s_app.cmd_velocity = 240;
            } else {
                s_app.cmd_velocity = 0;
            }
            printf("KEYB: target velocity = %ld\r\n", (long)s_app.cmd_velocity);
        }
    } else {
        s_app.key_b_cnt = 0;
    }
    s_app.key_b_level = b;
}

static void app_poll(void)
{
    ec_master_t *master = s_app.master;
    uint32_t now = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);

    app_poll_keys();

    bool link = master->netdev[EC_NETDEV_MAIN] && master->netdev[EC_NETDEV_MAIN]->link_state;

    if (link && !s_app.last_link) {
        /* link came back: allow the master to be configured and started again */
        s_app.auto_start_done = false;
        s_app.auto_start_failed = false;
        s_app.last_rescan_ms = now;
    }
    s_app.last_link = link;

    if (!master->scan_done) {
        return;
    }

    if (master->slave_count == 0) {
        s_app.slave_state = 0;
        if (link && (now - s_app.last_rescan_ms) > 3000U) {
            s_app.last_rescan_ms = now;
            master->rescan_request = true;
        }
        return;
    }

    if (!master->started && !s_app.auto_start_done && !s_app.auto_start_failed) {
        s_app.auto_start_done = true;
        if (app_configure_and_start() != 0) {
            s_app.auto_start_failed = true;
        }
    }

    if (master->started) {
        /* derive actual velocity from the position feedback */
        if ((now - s_app.last_sample_ms) >= 100U) {
            int32_t delta = s_app.position - s_app.last_position;
            uint32_t dt = now - s_app.last_sample_ms;

            s_app.velocity_actual = (int32_t)((int64_t)delta * 1000 / (int32_t)dt);
            s_app.last_position = s_app.position;
            s_app.last_sample_ms = now;
        }
    }
}

/* ------------------------------------------------------------------------- */
/* OLED user interface                                                       */
/* ------------------------------------------------------------------------- */
static const char *slave_state_str(uint8_t state)
{
    switch (state & EC_SLAVE_STATE_MASK) {
    case EC_SLAVE_STATE_INIT:
        return "INIT";
    case EC_SLAVE_STATE_PREOP:
        return "PREOP";
    case EC_SLAVE_STATE_BOOT:
        return "BOOT";
    case EC_SLAVE_STATE_SAFEOP:
        return "SAFEOP";
    case EC_SLAVE_STATE_OP:
        return "OP";
    default:
        return "----";
    }
}

static void oled_write_line(uint8_t page, const char *fmt, ...)
{
    char line[24];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);

    OLED_ShowString(0, page * 8, (uint8_t *)line, 8, 1);
}

static void app_ui(void)
{
    ec_master_t *master = s_app.master;
    bool link = master->netdev[EC_NETDEV_MAIN] && master->netdev[EC_NETDEV_MAIN]->link_state;
    const char *state = master->started ? slave_state_str(s_app.slave_state) : "STOP";

    OLED_ClearBuffer();

    oled_write_line(0, "LuckyCAT ECAT MST");

    if (master->slave_count == 0) {
        oled_write_line(1, "LNK:%s  SCANNING..", link ? "UP" : "DN");
    } else {
        oled_write_line(1, "LNK:%s SLV:%u %s", link ? "UP" : "DN",
                        (unsigned)master->slave_count, state);
    }

    oled_write_line(2, "CW:%04X SW:%04X",
                    (unsigned)s_app.controlword, (unsigned)s_app.statusword);
    oled_write_line(3, "TGT:%7ld", (long)(s_app.run_request ? s_app.cmd_velocity : 0));
    oled_write_line(4, "POS:%9ld", (long)s_app.position);
    oled_write_line(5, "VEL:%7ld/s", (long)s_app.velocity_actual);
    oled_write_line(6, "WKC:%u/%-2u TXE:%lu",
                    (unsigned)s_app.wkc_actual, (unsigned)s_app.wkc_expected,
                    (unsigned long)g_ec_netdev_tx_stall);

    if (master->slave_count == 0) {
        if (g_ec_netdev_tx_stall) {
            oled_write_line(7, "NO TX (ENET DMA)");
        } else if (!master->netdev[EC_NETDEV_MAIN]->link_state) {
            oled_write_line(7, "CHECK ETHERCAT CABLE");
        } else {
            oled_write_line(7, "TX OK, NO SLAVE");
        }
    } else if (!master->started) {
        oled_write_line(7, "STARTING PDO..");
    } else if (s_app.run_request) {
        oled_write_line(7, "K1:STOP K2:SPD%ld", (long)s_app.cmd_velocity);
    } else {
        oled_write_line(7, "K1:RUN  K2:SPD%ld", (long)s_app.cmd_velocity);
    }

    OLED_Refresh();

    board_led_write(master->started && (s_app.slave_state & EC_SLAVE_STATE_MASK) == EC_SLAVE_STATE_OP
                        ? 0 : 1);
}

/* ------------------------------------------------------------------------- */
/* Task / init                                                               */
/* ------------------------------------------------------------------------- */
static void ecat_task(void *param)
{
    uint32_t ui_div = 0;

    (void)param;

    s_app.last_sample_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    s_app.last_position = s_app.position;

    for (;;) {
        app_poll();

        if (++ui_div >= (APP_UI_PERIOD_MS / APP_POLL_PERIOD_MS)) {
            ui_div = 0;
            app_ui();
        }

        vTaskDelay(pdMS_TO_TICKS(APP_POLL_PERIOD_MS));
    }
}

void ecat_app_start(ec_master_t *master)
{
    memset(&s_app, 0, sizeof(s_app));
    s_app.master = master;
    s_app.cmd_velocity = 0;
    s_app.layout.cw_off = -1;
    s_app.layout.sw_off = -1;
    s_app.layout.tv_off = -1;
    s_app.layout.pos_off = -1;
    s_app.layout.vel_off = -1;

    if (xTaskCreate(ecat_task, "ecat_app", APP_TASK_STACK_SIZE, NULL,
                    APP_TASK_PRIORITY, NULL) != pdPASS) {
        printf("Failed to create EtherCAT application task\r\n");
    }
}

/* ------------------------------------------------------------------------- */
/* Shell commands                                                            */
/* ------------------------------------------------------------------------- */
static void motor_help(void)
{
    printf("Usage: motor <start|stop|speed <n>|status|reset|cycle [us]|selftest>\r\n");
}

int motor(int argc, const char **argv)
{
    if (argc < 2) {
        motor_help();
        return -1;
    }

    if (strcmp(argv[1], "start") == 0) {
        s_app.run_request = true;
    } else if (strcmp(argv[1], "stop") == 0) {
        s_app.run_request = false;
    } else if (strcmp(argv[1], "speed") == 0) {
        if (argc < 3) {
            motor_help();
            return -1;
        }
        int32_t v = atoi(argv[2]);
        if (v > APP_VEL_MAX) {
            v = APP_VEL_MAX;
        } else if (v < -APP_VEL_MAX) {
            v = -APP_VEL_MAX;
        }
        s_app.cmd_velocity = v;
    } else if (strcmp(argv[1], "reset") == 0) {
        s_app.run_request = false;
        s_app.cmd_velocity = 0;
    } else if (strcmp(argv[1], "selftest") == 0) {
        /* PHY internal loopback: the frames sent by the MAC must come back
         * through the PHY and be counted by the receive path. This validates
         * the MII data/clock pins without an external slave. */
        uint16_t bmcr = 0;
        uint16_t bmsr = 0;
        uint32_t rx_before;
        uint32_t rx_after;
        uint32_t dma_status;

        (void)enet_read_phy(HPM_ENET0, ENET_PHY_ADDR_DATA, 0, &bmcr);
        rx_before = HPM_ENET0->RXFRAMECOUNT_GB;

        (void)enet_write_phy(HPM_ENET0, ENET_PHY_ADDR_DATA, 0, (uint16_t)(bmcr | 0x4000U));
        HPM_ENET0->DMA_TX_POLL_DEMAND = 1U;
        (void)HPM_ENET0->DMA_TX_POLL_DEMAND;
        board_delay_ms(30);
        rx_after = HPM_ENET0->RXFRAMECOUNT_GB;
        dma_status = HPM_ENET0->DMA_STATUS;
        (void)enet_read_phy(HPM_ENET0, ENET_PHY_ADDR_DATA, 1, &bmsr);
        (void)enet_write_phy(HPM_ENET0, ENET_PHY_ADDR_DATA, 0, bmcr);

        printf("selftest: PHY loopback BMCR 0x%04X -> 0x%04X, BMSR 0x%04X\r\n",
               bmcr, (unsigned)(bmcr | 0x4000U), bmsr);
        printf("selftest: RX frames %lu -> %lu, DMA_STATUS 0x%08X -> %s\r\n",
               (unsigned long)rx_before, (unsigned long)rx_after, (unsigned)dma_status,
               (rx_after != rx_before) ? "PASS" : "NO FRAME");
        return 0;
    } else if (strcmp(argv[1], "cycle") == 0) {
        if (argc < 3) {
            printf("cycle = %u us\r\n", (unsigned)s_cycle_us);
            return 0;
        }
        if (s_app.master->started) {
            printf("master is running, stop it first\r\n");
            return 0;
        }
        s_cycle_us = (uint32_t)strtoul(argv[2], NULL, 0);
        if (s_cycle_us < 200U) {
            s_cycle_us = 200U;
        }
        printf("cycle = %u us (take effect on next start)\r\n", (unsigned)s_cycle_us);
        return 0;
    } else if (strcmp(argv[1], "status") == 0) {
        printf("master  : %s, slaves %u, link %s\r\n",
               s_app.master->started ? "started" : "stopped",
               (unsigned)s_app.master->slave_count,
               s_app.master->netdev[EC_NETDEV_MAIN]->link_state ? "up" : "down");
        printf("scan    : done %u, phase %u, wkc_exp %u\r\n",
               (unsigned)s_app.master->scan_done, (unsigned)s_app.master->phase,
               (unsigned)s_app.master->expected_working_counter);
        if (s_app.master->slave_count) {
            printf("sii     : VID 0x%08X PID 0x%08X rev 0x%08X, sm %u, mbx 0x%04X\r\n",
                   (unsigned)s_app.master->slaves[0].sii.vendor_id,
                   (unsigned)s_app.master->slaves[0].sii.product_code,
                   (unsigned)s_app.master->slaves[0].sii.revision_number,
                   (unsigned)s_app.master->slaves[0].sm_count,
                   (unsigned)s_app.master->slaves[0].sii.mailbox_protocols);
        }
        printf("slave0  : state %s, AL 0x%04X\r\n",
               slave_state_str(s_app.slave_state),
               (unsigned)(s_app.master->slave_count ? s_app.master->slaves[0].alstatus_code : 0));
        printf("cia402  : cw 0x%04X, sw 0x%04X, run %u\r\n",
               (unsigned)s_app.controlword, (unsigned)s_app.statusword, s_app.run_request);
        printf("pdo     : cycles %lu, wkc %u/%u, size %u (o%u i%u) lwkc %u sync %u\r\n",
               (unsigned long)s_app.cycles, (unsigned)s_app.wkc_actual,
               (unsigned)s_app.wkc_expected,
               (unsigned)s_app.master->actual_pdo_size,
               (unsigned)(s_app.master->slave_count ? s_app.master->slaves[0].odata_size : 0),
               (unsigned)(s_app.master->slave_count ? s_app.master->slaves[0].idata_size : 0),
               (unsigned)s_app.master->pdo_datagram.working_counter,
               (unsigned)(s_app.master->slave_count && s_app.master->slaves[0].config
                              ? s_app.master->slaves[0].config->sync_count : 0));
        {
            uint16_t bmsr_p0 = 0, bmsr_p1 = 0;
            (void)enet_read_phy(HPM_ENET0, 1, 1, &bmsr_p0);
            (void)enet_read_phy(HPM_ENET0, 2, 1, &bmsr_p1);
            printf("phy     : P0 BMSR 0x%04X (link %u), P1 BMSR 0x%04X (link %u)\r\n",
                   bmsr_p0, (unsigned)((bmsr_p0 >> 2) & 1),
                   bmsr_p1, (unsigned)((bmsr_p1 >> 2) & 1));
        }
        printf("tx      : queued %lu, done %lu, recycled %lu, stalled %lu\r\n",
               (unsigned long)g_ec_netdev_tx_queued,
               (unsigned long)g_ec_netdev_tx_done,
               (unsigned long)g_ec_netdev_tx_recycled,
               (unsigned long)g_ec_netdev_tx_stall);
        printf("motion  : target %ld, ramped %ld, actual %ld, pos %ld\r\n",
               (long)(s_app.run_request ? s_app.cmd_velocity : 0),
               (long)s_app.target_velocity, (long)s_app.velocity_actual, (long)s_app.position);
        return 0;
    } else {
        motor_help();
        return -1;
    }

    printf("OK\r\n");
    return 0;
}
CSH_CMD_EXPORT(motor, );
