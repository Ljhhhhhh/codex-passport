#pragma once

#include <stdint.h>
#include <stdbool.h>

#define PASSPORT_ALERT_AUDIO_PERIOD_MS 60000U

typedef struct {
    uint32_t last_unread_count;   // previous unread count seen
    uint16_t pending_alerts;      // count of unread tasks requiring attention
    uint32_t ms_since_last_beep;  // counter for 60s periodic chime
    bool sound_requested;         // flag indicating beep should play on this tick
} passport_alert_mgr_t;

void passport_alert_init(passport_alert_mgr_t *mgr);
void passport_alert_set_pending(passport_alert_mgr_t *mgr, uint16_t count);
bool passport_alert_should_stay_awake(const passport_alert_mgr_t *mgr);
bool passport_alert_tick(passport_alert_mgr_t *mgr, uint32_t dt_ms);
void passport_alert_mark_read(passport_alert_mgr_t *mgr);
void passport_alert_update_unread(passport_alert_mgr_t *mgr, uint32_t unread_count);
void passport_alert_play_chime(void);
