#include "passport_alert.h"
#include <math.h>

void passport_alert_init(passport_alert_mgr_t *mgr)
{
    if (!mgr) {
        return;
    }
    mgr->last_unread_count = 0;
    mgr->pending_alerts = 0;
    mgr->ms_since_last_beep = PASSPORT_ALERT_AUDIO_PERIOD_MS; // trigger immediately on first alert
    mgr->sound_requested = false;
}

void passport_alert_update_unread(passport_alert_mgr_t *mgr, uint32_t unread_count)
{
    if (!mgr) {
        return;
    }
    // If unread count increased, trigger chime
    if (unread_count != UINT32_MAX && unread_count > mgr->last_unread_count) {
        mgr->sound_requested = true;
        mgr->ms_since_last_beep = 0;
    }
    if (unread_count != UINT32_MAX) {
        mgr->last_unread_count = unread_count;
        mgr->pending_alerts = unread_count > 0xFFFF ? 0xFFFF : (uint16_t)unread_count;
    }
}

#ifdef ESP_PLATFORM
#include "bsp_audio.h"
#include "esp_log.h"

static const char *TAG = "passport_alert";
static bool s_audio_inited = false;

void passport_alert_play_chime(void)
{
    if (!s_audio_inited) {
        if (bsp_audio_init() == ESP_OK && bsp_audio_set_format(16000, 16, 1) == ESP_OK) {
            bsp_audio_set_volume(80);
            s_audio_inited = true;
        } else {
            ESP_LOGW(TAG, "Audio init failed for alert chime");
            return;
        }
    }

    // Generate a pleasant two-tone chime (587 Hz - D5, 880 Hz - A5), 120ms each
    const uint32_t sample_rate = 16000;
    const float freqs[2] = {587.33f, 880.00f};
    const size_t samples_per_tone = (sample_rate * 120) / 1000;
    int16_t buffer[256];

    for (int t = 0; t < 2; t++) {
        float freq = freqs[t];
        size_t done = 0;
        while (done < samples_per_tone) {
            size_t chunk = samples_per_tone - done;
            if (chunk > sizeof(buffer) / sizeof(buffer[0])) {
                chunk = sizeof(buffer) / sizeof(buffer[0]);
            }
            for (size_t i = 0; i < chunk; i++) {
                size_t idx = done + i;
                float time = (float)idx / (float)sample_rate;
                float envelope = 1.0f - ((float)idx / (float)samples_per_tone);
                float val = sinf(2.0f * (float)M_PI * freq * time) * envelope;
                buffer[i] = (int16_t)(val * 14000.0f);
            }
            bsp_audio_write(buffer, chunk * sizeof(int16_t));
            done += chunk;
        }
    }
}
#else
void passport_alert_play_chime(void) {}
#endif
void passport_alert_set_pending(passport_alert_mgr_t *mgr, uint16_t count)
{
    if (!mgr) {
        return;
    }
    if (mgr->pending_alerts == 0 && count > 0) {
        // New alert arrived, request sound immediately
        mgr->sound_requested = true;
        mgr->ms_since_last_beep = 0;
    }
    mgr->pending_alerts = count;
}

bool passport_alert_should_stay_awake(const passport_alert_mgr_t *mgr)
{
    return (mgr && mgr->pending_alerts > 0);
}

bool passport_alert_tick(passport_alert_mgr_t *mgr, uint32_t dt_ms)
{
    if (!mgr || mgr->pending_alerts == 0) {
        return false;
    }
    if (mgr->sound_requested) {
        mgr->sound_requested = false;
        return true;
    }
    mgr->ms_since_last_beep += dt_ms;
    if (mgr->ms_since_last_beep >= PASSPORT_ALERT_AUDIO_PERIOD_MS) {
        mgr->ms_since_last_beep = 0;
        return true;
    }
    return false;
}

void passport_alert_mark_read(passport_alert_mgr_t *mgr)
{
    if (!mgr) {
        return;
    }
    if (mgr->pending_alerts > 0) {
        mgr->pending_alerts--;
    }
}
