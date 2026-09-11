#include "bsp_i2c.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "bsp_battery.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "passport_protocol.h"
#include "passport_storage.h"
#include "passport_ble.h"
#include "passport_ui.h"
#include "passport_idle.h"
#include "passport_alert.h"

static const char *TAG = "codex-passport";
static passport_idle_t s_idle;
static QueueHandle_t s_buttons;

static void apply_idle(passport_idle_act_t act)
{
    if (act == PASSPORT_IDLE_SLEEP) {
        bsp_display_backlight(0);
        ESP_LOGI(TAG, "Backlight off: no unread tasks, idle timeout");
    } else if (act == PASSPORT_IDLE_WAKE) {
        bsp_display_backlight(100);
        ESP_LOGI(TAG, "Backlight on");
    }
}

static void on_button_event(bsp_btn_t btn, bsp_btn_ev_t ev, void *user)
{
    (void)user;
    if (ev == BSP_BTN_CLICK && s_buttons) {
        xQueueSend(s_buttons, &btn, 0);
    }
}

static void ui_input_task(void *arg)
{
    (void)arg;
    TickType_t previous = xTaskGetTickCount();
    while (1) {
        bsp_btn_t btn;
        bool pressed = xQueueReceive(s_buttons, &btn, pdMS_TO_TICKS(250)) == pdTRUE;
        TickType_t now = xTaskGetTickCount();
        uint32_t dt = (now - previous) * portTICK_PERIOD_MS;
        uint32_t unread = passport_ble_unread_count();
        apply_idle(passport_idle_set_unread(&s_idle, unread));
        apply_idle(passport_idle_on_tick(&s_idle, dt));
        previous = now;
        if (passport_ui_take_project_update()) {
            bool was_asleep = !s_idle.awake;
            s_idle.awake = 1;
            s_idle.idle_ms = 0;
            if (was_asleep) {
                passport_ui_show_projects();
                apply_idle(PASSPORT_IDLE_WAKE);
            }
        }
        if (!pressed) continue;
        passport_idle_act_t act = passport_idle_on_button(&s_idle, btn == BSP_BTN_OK);
        apply_idle(act);
        if (act != PASSPORT_IDLE_PASS) continue;
        if (btn == BSP_BTN_UP) passport_ui_prev_item();
        else if (btn == BSP_BTN_DOWN) passport_ui_next_item();
        else if (btn == BSP_BTN_OK) passport_ui_toggle_qr();
    }
}

static void alert_task(void *arg)
{
    (void)arg;
    while (1) {
        if (passport_ble_take_alert()) {
            ESP_LOGI(TAG, "Playing new message chime");
            passport_alert_play_chime();
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

static void battery_task(void *pvParameters)
{
    bool has_batt = (pvParameters != NULL);

    while (1) {
        if (has_batt) {
            int pct = bsp_battery_soc();
            int mv = bsp_battery_mv();
            bool is_chg = (mv > 4250);
            passport_ui_update_battery(pct >= 0 ? pct : 100, is_chg);
        } else {
            passport_ui_update_battery(100, false);
        }
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Starting Codex Passport Companion...");

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_ERROR_CHECK(bsp_i2c_init());

    if (bsp_display_init() != ESP_OK || !bsp_lvgl_init()) {
        ESP_LOGE(TAG, "Display / LVGL initialization failed!");
        return;
    }
    bsp_display_backlight(100);
    passport_idle_init(&s_idle);

    bool has_batt = (bsp_battery_init() == ESP_OK);
    ESP_LOGI(TAG, "Battery sensor CW2017: %s", has_batt ? "detected" : "not fitted (using default)");

    ESP_ERROR_CHECK(passport_storage_init());
    ESP_ERROR_CHECK(passport_ui_init());
    s_buttons = xQueueCreate(8, sizeof(bsp_btn_t));
    configASSERT(s_buttons);
    configASSERT(xTaskCreate(ui_input_task, "passport_input", 3072, NULL, 4, NULL) == pdPASS);
    ESP_ERROR_CHECK(bsp_button_init(on_button_event, NULL));
    ESP_ERROR_CHECK(passport_ble_init());
    configASSERT(xTaskCreate(alert_task, "passport_audio", 3072, NULL, 3, NULL) == pdPASS);

    xTaskCreate(battery_task, "battery_task", 3072, has_batt ? (void *)1 : NULL, 4, NULL);

    ESP_LOGI(TAG, "Codex Passport initialized successfully.");
}
