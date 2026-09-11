// passport_ui.h - LVGL user interface for Codex Passport
#ifndef PASSPORT_UI_H
#define PASSPORT_UI_H

#include "passport_protocol.h"
#include <stdbool.h>

#ifdef ESP_PLATFORM
#include "esp_err.h"
#else
typedef int esp_err_t;
#define ESP_OK 0
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    PAGE_PROFILE    = 0,
    PAGE_QUOTA      = 1,
    PAGE_PROJECTS   = 2,
    PAGE_MESSAGES   = 2,
    PAGE_QR_CODE    = 3,
    PAGE_TASKS      = 4,
    PAGE_COUNT      = 5,
    PAGE_CYCLE      = 3,
} passport_page_t;

esp_err_t passport_ui_init(void);

void passport_ui_next_page(void);
void passport_ui_prev_page(void);
void passport_ui_toggle_qr(void);
uint8_t passport_ui_project_page(void);
bool passport_ui_take_project_update(void);
void passport_ui_show_projects(void);
void passport_ui_next_item(void);
void passport_ui_prev_item(void);

void passport_ui_update_profile(const passport_profile_t *profile);
void passport_ui_update_stats(const passport_stats_t *stats);
void passport_ui_update_heatmap(const passport_heatmap_t *heatmap);
void passport_ui_update_footprints(const passport_footprints_t *footprints);
void passport_ui_update_directions(const passport_directions_t *directions);
void passport_ui_update_quota(const passport_quota_t *quota);
void passport_ui_update_realtime(const passport_realtime_t *realtime);
bool passport_ui_update_projects(const passport_projects_page_t *projects);
bool passport_ui_update_messages(const passport_messages_page_t *messages);
void passport_ui_set_sync_error(bool error);
void passport_ui_update_tasks(const passport_tasks_page_t *tasks);
void passport_ui_set_ble_connected(bool connected);
void passport_ui_update_battery(int percent, bool is_charging);

#ifdef __cplusplus
}
#endif

#endif // PASSPORT_UI_H
