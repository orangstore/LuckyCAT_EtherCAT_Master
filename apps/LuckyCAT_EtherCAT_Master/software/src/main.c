/*
 * Copyright (c) 2025 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * LuckyCAT_EtherCAT_Master - EtherCAT master demo for the LuckyCAT (HPM5E31) board
 */
#include <stdio.h>

#include "FreeRTOS.h"
#include "task.h"

#include "board.h"
#include "hpm_clock_drv.h"
#include "hpm_uart_drv.h"
#include "shell.h"
#include "ec_master.h"
#include "ecat_app.h"
#include "oled.h"

SDK_DECLARE_EXT_ISR_M(BOARD_CONSOLE_UART_IRQ, shell_uart_isr)

#define TASK_START_PRIORITY (configMAX_PRIORITIES - 2U)

#define PROJECT_NAME    "LuckyCAT_EtherCAT_Master"
#define PROJECT_VERSION "1.0.0"

ec_master_t g_ec_master;

/* Buffer required by the CherryECAT SII layer when a slave EEPROM image is
 * linked into the firmware. Unused by the master itself. */
unsigned char cherryecat_eepromdata[2048];

static void task_start(void *param);

int main(void)
{
    board_init();
    board_init_gpio_pins();

    if (pdPASS != xTaskCreate(task_start, "task_start", 1024U, NULL, TASK_START_PRIORITY, NULL)) {
        printf("Task start creation failed!\r\n");
        while (1) {
        }
    }

    vTaskStartScheduler();

    printf("Unexpected scheduler exit!\r\n");
    while (1) {
    }

    return 0;
}

static void task_start(void *param)
{
    uart_config_t shell_uart_config = { 0 };

    (void)param;

    /* console / shell on the board console UART */
    uart_default_config(BOARD_CONSOLE_UART_BASE, &shell_uart_config);
    shell_uart_config.src_freq_in_hz = clock_get_frequency(BOARD_CONSOLE_UART_CLK_NAME);
    shell_uart_config.baudrate = 115200;

    if (status_success != uart_init(BOARD_CONSOLE_UART_BASE, &shell_uart_config)) {
        printf("Failed to initialize uart\r\n");
        while (1) {
        }
    }

    if (0 != shell_init(BOARD_CONSOLE_UART_BASE, false)) {
        printf("Failed to initialize shell\r\n");
        while (1) {
        }
    }

    uart_enable_irq(BOARD_CONSOLE_UART_BASE, uart_intr_rx_data_avail_or_timeout);
    intc_m_enable_irq_with_priority(BOARD_CONSOLE_UART_IRQ, 1);

    /* OLED status display */
    OLED_Init();
    OLED_ColorTurn(0);
    OLED_DisplayTurn(0);
    OLED_Clear();
    OLED_ShowString(0, 0, (uint8_t *)"LuckyCAT EtherCAT", 8, 1);
    OLED_ShowString(0, 16, (uint8_t *)"Initializing..", 8, 1);
    OLED_Refresh();
    printf("OLED: %s (ack errors %u)\r\n",
           (OLED_GetAckErrors() == 0) ? "I2C OK" : "I2C ERROR",
           (unsigned)OLED_GetAckErrors());

    printf("\r\n==============================================\r\n");
    printf(" %s v%s\r\n", PROJECT_NAME, PROJECT_VERSION);
    printf(" HPM5E31 + CherryECAT, CiA402 CSV motor control\r\n");
    printf("==============================================\r\n");

    ec_master_cmd_init(&g_ec_master);

    printf("Initializing EtherCAT master (ENET0 / MII / JL1111)...\r\n");
    while (ec_master_init(&g_ec_master, 0) != 0) {
        printf("EtherCAT master initialization failed, retry in 2s\r\n");
        OLED_Clear();
        OLED_ShowString(0, 0, (uint8_t *)"ECAT INIT FAILED", 8, 1);
        OLED_ShowString(0, 16, (uint8_t *)"RETRY...", 8, 1);
        OLED_Refresh();
        board_led_toggle();
        vTaskDelay(pdMS_TO_TICKS(2000));
    }

    printf("EtherCAT master initialized, scanning bus...\r\n");

    ecat_app_start(&g_ec_master);

    vTaskDelete(NULL);
}

CSH_CMD_EXPORT(ethercat, );
