// passport_storage.h - NVS persistence for Codex Passport data
#ifndef PASSPORT_STORAGE_H
#define PASSPORT_STORAGE_H
#include "passport_protocol.h"

#ifdef ESP_PLATFORM
#include "esp_err.h"
#else
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Initializes NVS storage and loads or writes default profile data
esp_err_t passport_storage_init(void);

// Load all persistent sections into memory
esp_err_t passport_storage_load_all(passport_profile_t *profile,
                                    passport_stats_t *stats,
                                    passport_heatmap_t *heatmap,
                                    passport_footprints_t *footprints,
                                    passport_directions_t *directions);

// Save individual sections to NVS
esp_err_t passport_storage_save_profile(const passport_profile_t *profile);
esp_err_t passport_storage_save_stats(const passport_stats_t *stats);
esp_err_t passport_storage_save_heatmap(const passport_heatmap_t *heatmap);
esp_err_t passport_storage_save_footprints(const passport_footprints_t *footprints);
esp_err_t passport_storage_save_directions(const passport_directions_t *directions);
esp_err_t passport_storage_save_quota(const passport_quota_t *quota);
esp_err_t passport_storage_load_quota(passport_quota_t *quota);

#ifdef __cplusplus
}
#endif

#endif // PASSPORT_STORAGE_H
