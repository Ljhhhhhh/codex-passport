// passport_storage.c - NVS persistence implementation
#include "passport_storage.h"
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char *TAG = "passport_storage";
static const char *NVS_NAMESPACE = "codex_passport";

static void init_default_data(passport_profile_t *p,
                              passport_stats_t *s,
                              passport_heatmap_t *h,
                              passport_footprints_t *f,
                              passport_directions_t *d)
{
    if (p) {
        memset(p, 0, sizeof(*p));
        strncpy(p->name, "GuanMo", sizeof(p->name) - 1);
        strncpy(p->interests, "读书 / 开发 / 运动", sizeof(p->interests) - 1);
        strncpy(p->signature, "In me the tiger sniffs the rose.", sizeof(p->signature) - 1);
        strncpy(p->homepage, "https://github.com/Ljhhhhhh", sizeof(p->homepage) - 1);
        strncpy(p->issue_date, "2026-09-08", sizeof(p->issue_date) - 1);
    }
    if (s) {
        memset(s, 0, sizeof(*s));
        s->total_tokens = 665631232ULL;
        s->today_tokens = 63045809UL;
        s->week_tokens = 105209956UL;
        s->streak_days = 2;
    }
    if (h) {
        memset(h, 0, sizeof(*h));
        strncpy(h->start_date, "2026-06-14", sizeof(h->start_date) - 1);
        strncpy(h->end_date, "2026-09-13", sizeof(h->end_date) - 1);
        h->active_days = 24;
        h->max_daily_tokens = 285105226UL;
        for (int i = 0; i < 91; i++) {
            if (i >= 80) {
                h->levels[i] = (uint8_t)((i % 4) + 1);
            } else if (i % 3 == 0) {
                h->levels[i] = (uint8_t)((i % 3) + 1);
            } else {
                h->levels[i] = 0;
            }
        }
    }
    if (f) {
        memset(f, 0, sizeof(*f));
        f->count = 3;
        strncpy(f->items[0].topic, "Frontend & Web", sizeof(f->items[0].topic) - 1);
        strncpy(f->items[0].first_date, "2026-09-03", sizeof(f->items[0].first_date) - 1);
        f->items[0].total_tokens = 180106118ULL;

        strncpy(f->items[1].topic, "AI Systems", sizeof(f->items[1].topic) - 1);
        strncpy(f->items[1].first_date, "2026-09-04", sizeof(f->items[1].first_date) - 1);
        f->items[1].total_tokens = 111502993ULL;

        strncpy(f->items[2].topic, "IoT & Hardware", sizeof(f->items[2].topic) - 1);
        strncpy(f->items[2].first_date, "2026-09-03", sizeof(f->items[2].first_date) - 1);
        f->items[2].total_tokens = 52804890ULL;
    }
    if (d) {
        memset(d, 0, sizeof(*d));
        d->count = 3;
        strncpy(d->items[0].name, "open-webui", sizeof(d->items[0].name) - 1);
        d->items[0].tokens = 23517743UL;
        d->items[0].percent = 45;

        strncpy(d->items[1].name, "ai-passport", sizeof(d->items[1].name) - 1);
        d->items[1].tokens = 15804200UL;
        d->items[1].percent = 30;

        strncpy(d->items[2].name, "gf-ai-server", sizeof(d->items[2].name) - 1);
        d->items[2].tokens = 13120000UL;
        d->items[2].percent = 25;
    }
}

esp_err_t passport_storage_init(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to open NVS namespace %s: %d", NVS_NAMESPACE, err);
        return err;
    }

    size_t required_len = sizeof(passport_profile_t);
    passport_profile_t test_profile;
    err = nvs_get_blob(handle, "profile", &test_profile, &required_len);
    if (err == ESP_ERR_NVS_NOT_FOUND || err != ESP_OK) {
        ESP_LOGI(TAG, "No profile found in NVS, writing default GuanMo credentials...");
        passport_profile_t def_p;
        passport_stats_t def_s;
        passport_heatmap_t def_h;
        passport_footprints_t def_f;
        passport_directions_t def_d;

        init_default_data(&def_p, &def_s, &def_h, &def_f, &def_d);

        nvs_set_blob(handle, "profile", &def_p, sizeof(def_p));
        nvs_set_blob(handle, "stats", &def_s, sizeof(def_s));
        nvs_set_blob(handle, "heatmap", &def_h, sizeof(def_h));
        nvs_set_blob(handle, "footprints", &def_f, sizeof(def_f));
        nvs_set_blob(handle, "directions", &def_d, sizeof(def_d));
        passport_quota_t def_q;
        memset(&def_q, 0, sizeof(def_q));
        def_q.short_window_hours = 5;
        nvs_set_blob(handle, "quota", &def_q, sizeof(def_q));
        nvs_commit(handle);
    } else {
        ESP_LOGI(TAG, "Loaded existing profile for: %s", test_profile.name);
    }

    nvs_close(handle);
    return ESP_OK;
}

esp_err_t passport_storage_load_all(passport_profile_t *profile,
                                    passport_stats_t *stats,
                                    passport_heatmap_t *heatmap,
                                    passport_footprints_t *footprints,
                                    passport_directions_t *directions)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        init_default_data(profile, stats, heatmap, footprints, directions);
        return err;
    }

    size_t len;
    if (profile) {
        len = sizeof(*profile);
        if (nvs_get_blob(handle, "profile", profile, &len) != ESP_OK) {
            init_default_data(profile, NULL, NULL, NULL, NULL);
        }
    }
    if (stats) {
        len = sizeof(*stats);
        if (nvs_get_blob(handle, "stats", stats, &len) != ESP_OK) {
            init_default_data(NULL, stats, NULL, NULL, NULL);
        }
    }
    if (heatmap) {
        len = sizeof(*heatmap);
        if (nvs_get_blob(handle, "heatmap", heatmap, &len) != ESP_OK) {
            init_default_data(NULL, NULL, heatmap, NULL, NULL);
        }
    }
    if (footprints) {
        len = sizeof(*footprints);
        if (nvs_get_blob(handle, "footprints", footprints, &len) != ESP_OK) {
            init_default_data(NULL, NULL, NULL, footprints, NULL);
        }
    }
    if (directions) {
        len = sizeof(*directions);
        if (nvs_get_blob(handle, "directions", directions, &len) != ESP_OK) {
            init_default_data(NULL, NULL, NULL, NULL, directions);
        }
    }

    nvs_close(handle);
    return ESP_OK;
}

esp_err_t passport_storage_save_profile(const passport_profile_t *profile)
{
    if (!profile) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    err = nvs_set_blob(handle, "profile", profile, sizeof(*profile));
    if (err == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t passport_storage_save_stats(const passport_stats_t *stats)
{
    if (!stats) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    err = nvs_set_blob(handle, "stats", stats, sizeof(*stats));
    if (err == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t passport_storage_save_heatmap(const passport_heatmap_t *heatmap)
{
    if (!heatmap) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    err = nvs_set_blob(handle, "heatmap", heatmap, sizeof(*heatmap));
    if (err == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t passport_storage_save_footprints(const passport_footprints_t *footprints)
{
    if (!footprints) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    err = nvs_set_blob(handle, "footprints", footprints, sizeof(*footprints));
    if (err == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t passport_storage_save_directions(const passport_directions_t *directions)
{
    if (!directions) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    err = nvs_set_blob(handle, "directions", directions, sizeof(*directions));
    if (err == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t passport_storage_save_quota(const passport_quota_t *quota)
{
    if (!quota) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    err = nvs_set_blob(handle, "quota", quota, sizeof(*quota));
    if (err == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t passport_storage_load_quota(passport_quota_t *quota)
{
    if (!quota) return ESP_ERR_INVALID_ARG;
    memset(quota, 0, sizeof(*quota));
    quota->short_window_hours = 5;

    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        return err;
    }
    size_t len = sizeof(*quota);
    err = nvs_get_blob(handle, "quota", quota, &len);
    nvs_close(handle);
    if (err != ESP_OK) {
        memset(quota, 0, sizeof(*quota));
        quota->short_window_hours = 5;
    }
    return ESP_OK;
}

#else

// Host stub implementation for unit testing
static passport_profile_t s_host_profile;
static passport_stats_t s_host_stats;
static passport_heatmap_t s_host_heatmap;
static passport_footprints_t s_host_footprints;
static passport_directions_t s_host_directions;
static passport_quota_t s_host_quota;
static bool s_host_initialized;

static void init_host_defaults(void)
{
    strncpy(s_host_profile.name, "GuanMo", sizeof(s_host_profile.name) - 1);
    strncpy(s_host_profile.interests, "读书 / 开发 / 运动", sizeof(s_host_profile.interests) - 1);
    strncpy(s_host_profile.signature, "In me the tiger sniffs the rose.", sizeof(s_host_profile.signature) - 1);
    strncpy(s_host_profile.homepage, "https://github.com/Ljhhhhhh", sizeof(s_host_profile.homepage) - 1);
    strncpy(s_host_profile.issue_date, "2026-09-08", sizeof(s_host_profile.issue_date) - 1);

    s_host_stats.total_tokens = 665631232ULL;
    s_host_stats.today_tokens = 63045809UL;
    s_host_stats.week_tokens = 105209956UL;
    s_host_stats.streak_days = 2;
    s_host_quota.short_window_hours = 5;

    s_host_initialized = true;
}

esp_err_t passport_storage_init(void)
{
    init_host_defaults();
    return 0;
}

esp_err_t passport_storage_load_all(passport_profile_t *p, passport_stats_t *s, passport_heatmap_t *h, passport_footprints_t *f, passport_directions_t *d)
{
    if (!s_host_initialized) init_host_defaults();
    if (p) *p = s_host_profile;
    if (s) *s = s_host_stats;
    if (h) *h = s_host_heatmap;
    if (f) *f = s_host_footprints;
    if (d) *d = s_host_directions;
    return 0;
}

esp_err_t passport_storage_save_profile(const passport_profile_t *p)
{
    if (p) s_host_profile = *p;
    return 0;
}

esp_err_t passport_storage_save_stats(const passport_stats_t *s)
{
    if (s) s_host_stats = *s;
    return 0;
}

esp_err_t passport_storage_save_heatmap(const passport_heatmap_t *h)
{
    if (h) s_host_heatmap = *h;
    return 0;
}

esp_err_t passport_storage_save_footprints(const passport_footprints_t *f)
{
    if (f) s_host_footprints = *f;
    return 0;
}

esp_err_t passport_storage_save_directions(const passport_directions_t *d)
{
    if (d) s_host_directions = *d;
    return 0;
}

esp_err_t passport_storage_save_quota(const passport_quota_t *q)
{
    if (q) s_host_quota = *q;
    return 0;
}

esp_err_t passport_storage_load_quota(passport_quota_t *q)
{
    if (!s_host_initialized) init_host_defaults();
    if (q) *q = s_host_quota;
    return 0;
}

#endif
