#include "passport_alert.h"
#include <math.h>

bool passport_alert_accept(uint32_t *last_sequence, uint32_t sequence)
{
    if (!last_sequence || sequence == 0 || sequence <= *last_sequence) return false;
    *last_sequence = sequence;
    return true;
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
            bsp_audio_set_volume(60);
            s_audio_inited = true;
        } else {
            ESP_LOGW(TAG, "Audio init failed for alert chime");
            return;
        }
    }

    // Soft C5/E5 major third; a short attack avoids an abrupt waveform edge.
    const uint32_t sample_rate = 16000;
    const float freqs[2] = {523.25f, 659.25f};
    const size_t samples_per_tone = (sample_rate * 180) / 1000;
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
                float attack = fminf(1.0f, (float)idx / (sample_rate * 0.015f));
                float release = 1.0f - (float)idx / (float)(samples_per_tone - 1);
                float envelope = attack * attack * release * release;
                float val = sinf(2.0f * (float)M_PI * freq * time) * envelope;
                buffer[i] = (int16_t)(val * 10000.0f);
            }
            if (bsp_audio_write(buffer, chunk * sizeof(int16_t)) != ESP_OK) {
                ESP_LOGW(TAG, "Alert audio write failed");
                return;
            }
            done += chunk;
        }
        // Silence separates the notes and drains the final samples through I2S.
        for (size_t i = 0; i < 256; ++i) buffer[i] = 0;
        for (int i = 0; i < 2; ++i) {
            if (bsp_audio_write(buffer, sizeof(buffer)) != ESP_OK) {
                ESP_LOGW(TAG, "Alert audio tail write failed");
                return;
            }
        }
    }
}
#else
void passport_alert_play_chime(void) {}
#endif
