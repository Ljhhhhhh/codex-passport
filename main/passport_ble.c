// passport_ble.c - NimBLE GATT implementation for Codex Passport
#include "passport_ble.h"
#include "passport_protocol.h"
#include "passport_storage.h"
#include "passport_ui.h"
#include "passport_alert.h"
#include <string.h>
#include <stdatomic.h>

static _Atomic bool s_alert_pending;
static uint32_t s_alert_sequence;

bool passport_ble_take_alert(void)
{
    return atomic_exchange(&s_alert_pending, false);
}

static _Atomic uint32_t s_unread_count = UINT32_MAX;

uint32_t passport_ble_unread_count(void)
{
    return atomic_load(&s_unread_count);
}

#ifdef ESP_PLATFORM
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

static const char *TAG = "passport_ble";
static const char *DEVICE_NAME = "Codex-Passport";

static uint16_t s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static uint16_t s_tx_val_handle = 0;
static bool s_connected = false;
static uint8_t s_own_addr_type = BLE_OWN_ADDR_PUBLIC;
static passport_reassembler_t s_reassembler;

static int passport_gap_event(struct ble_gap_event *event, void *arg);

static void passport_ble_advertise(void)
{
    struct ble_gap_adv_params adv_params;
    struct ble_hs_adv_fields fields;
    int rc;

    memset(&fields, 0, sizeof(fields));
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (uint8_t *)DEVICE_NAME;
    fields.name_len = strlen(DEVICE_NAME);
    fields.name_is_complete = 1;

    // Advertise custom 16-bit Service UUID
    ble_uuid16_t svc_uuid = BLE_UUID16_INIT(PASSPORT_SVC_UUID);
    fields.uuids16 = &svc_uuid;
    fields.num_uuids16 = 1;
    fields.uuids16_is_complete = 1;

    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "Failed to set adv fields: %d", rc);
        return;
    }

    memset(&adv_params, 0, sizeof(adv_params));
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;

    rc = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER,
                           &adv_params, passport_gap_event, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "Failed to start adv: %d", rc);
    } else {
        ESP_LOGI(TAG, "BLE advertising started as '%s'", DEVICE_NAME);
    }
}

static int passport_gap_event(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            s_conn_handle = event->connect.conn_handle;
            s_connected = true;
            ESP_LOGI(TAG, "BLE host connected, handle: %d", s_conn_handle);
            passport_ui_set_ble_connected(true);
        } else {
            ESP_LOGW(TAG, "BLE connection failed, restarting adv");
            passport_ble_advertise();
        }
        break;

    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "BLE host disconnected, reason: %d", event->disconnect.reason);
        s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
        s_connected = false;
        atomic_store(&s_unread_count, UINT32_MAX);
        atomic_store(&s_alert_pending, false);
        s_alert_sequence = 0;
        passport_ui_set_ble_connected(false);
        passport_reassembler_reset(&s_reassembler);
        passport_ble_advertise();
        break;

    case BLE_GAP_EVENT_ADV_COMPLETE:
        passport_ble_advertise();
        break;

    default:
        break;
    }
    return 0;
}

static int gatt_chr_access_rx(uint16_t conn_handle, uint16_t attr_handle,
                             struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)conn_handle;
    (void)attr_handle;
    (void)arg;

    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
    if (len == 0 || len > PASSPORT_MAX_CHUNK_LEN + 16) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }

    uint8_t chunk_buf[PASSPORT_MAX_CHUNK_LEN + 16];
    int rc = ble_hs_mbuf_to_flat(ctxt->om, chunk_buf, sizeof(chunk_buf), &len);
    if (rc != 0) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    uint8_t out_msg_type = 0;
    uint8_t *out_payload = NULL;
    size_t out_payload_len = 0;

    bool complete = passport_reassembler_feed(&s_reassembler, chunk_buf, len,
                                              &out_msg_type, &out_payload, &out_payload_len);

    if (complete && out_payload && out_payload_len > 0) {
        ESP_LOGI(TAG, "Reassembled full message type 0x%02X, len %zu", out_msg_type, out_payload_len);

        switch (out_msg_type) {
        case MSG_TYPE_ALERT: {
            if (out_payload_len != sizeof(uint32_t)) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            uint32_t sequence;
            memcpy(&sequence, out_payload, sizeof(sequence));
            if (passport_alert_accept(&s_alert_sequence, sequence)) {
                atomic_store(&s_alert_pending, true);
            }
            passport_ble_send_ack(MSG_TYPE_ALERT, 0);
            break;
        }
        case MSG_TYPE_UNREAD: {
            if (out_payload_len != sizeof(uint32_t)) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            uint32_t count;
            memcpy(&count, out_payload, sizeof(count));
            atomic_store(&s_unread_count, count);
            passport_ble_send_ack(MSG_TYPE_UNREAD, 0);
            ESP_LOGI(TAG, "Unread count: %lu", (unsigned long)count);
            break;
        }
        case MSG_TYPE_PROJECTS:
            if (out_payload_len == sizeof(passport_projects_page_t)) {
                passport_projects_page_t page;
                memcpy(&page, out_payload, sizeof(page));
                if (page.count > PASSPORT_PROJECTS_PER_PAGE || !page.total_pages ||
                    page.page_index >= page.total_pages) {
                    return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
                }
                for (int i = 0; i < page.count; ++i) {
                    page.items[i].title[63] = 0;
                    page.items[i].project[31] = 0;
                }
                if (!passport_ui_update_projects(&page)) {
                    return BLE_ATT_ERR_INSUFFICIENT_RES;
                }
                passport_ble_send_ack(MSG_TYPE_PROJECTS, 0);
                ESP_LOGI(TAG, "Messages rendered: page %u/%u, count %u", page.page_index + 1, page.total_pages, page.count);
            } else {
                return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            }
            break;

        case MSG_TYPE_PROFILE:
            if (out_payload_len >= sizeof(passport_profile_t)) {
                passport_profile_t p;
                memcpy(&p, out_payload, sizeof(p));
                passport_storage_save_profile(&p);
                passport_ui_update_profile(&p);
                passport_ble_send_ack(MSG_TYPE_PROFILE, 0);
            }
            break;

        case MSG_TYPE_STATS:
            if (out_payload_len >= sizeof(passport_stats_t)) {
                passport_stats_t s;
                memcpy(&s, out_payload, sizeof(s));
                passport_storage_save_stats(&s);
                passport_ui_update_stats(&s);
                passport_ble_send_ack(MSG_TYPE_STATS, 0);
            }
            break;

        case MSG_TYPE_HEATMAP:
            if (out_payload_len >= sizeof(passport_heatmap_t)) {
                passport_heatmap_t h;
                memcpy(&h, out_payload, sizeof(h));
                passport_storage_save_heatmap(&h);
                passport_ui_update_heatmap(&h);
                passport_ble_send_ack(MSG_TYPE_HEATMAP, 0);
            }
            break;

        case MSG_TYPE_FOOTPRINTS:
            if (out_payload_len >= sizeof(passport_footprints_t)) {
                passport_footprints_t f;
                memcpy(&f, out_payload, sizeof(f));
                passport_storage_save_footprints(&f);
                passport_ui_update_footprints(&f);
                passport_ble_send_ack(MSG_TYPE_FOOTPRINTS, 0);
            }
            break;

        case MSG_TYPE_DIRECTIONS:
            if (out_payload_len >= sizeof(passport_directions_t)) {
                passport_directions_t d;
                memcpy(&d, out_payload, sizeof(d));
                passport_storage_save_directions(&d);
                passport_ui_update_directions(&d);
                passport_ble_send_ack(MSG_TYPE_DIRECTIONS, 0);
            }
            break;

        case MSG_TYPE_QUOTA:
            if (out_payload_len >= sizeof(passport_quota_t)) {
                passport_quota_t q;
                memcpy(&q, out_payload, sizeof(q));
                passport_storage_save_quota(&q);
                passport_ui_update_quota(&q);
                passport_ble_send_ack(MSG_TYPE_QUOTA, 0);
            }
            break;

        default:
            ESP_LOGW(TAG, "Unknown reassembled message type: 0x%02X", out_msg_type);
            break;
        }
    }

    return 0;
}

static int gatt_chr_access_tx(uint16_t conn_handle, uint16_t attr_handle,
                             struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)conn_handle;
    (void)attr_handle;
    (void)arg;

    if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
        uint8_t status[] = {s_connected ? 1 : 0, 0x50, 1, passport_ui_project_page(), 1, 1};
        os_mbuf_append(ctxt->om, status, sizeof(status));
        return 0;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

static int gatt_chr_access_live(uint16_t conn_handle, uint16_t attr_handle,
                              struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)conn_handle;
    (void)attr_handle;
    (void)arg;

    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
    if (len >= sizeof(passport_realtime_t)) {
        passport_realtime_t rt;
        uint16_t flat_len = 0;
        int rc = ble_hs_mbuf_to_flat(ctxt->om, &rt, sizeof(rt), &flat_len);
        if (rc == 0 && flat_len >= sizeof(rt)) {
            passport_ui_update_realtime(&rt);
        }
    }
    return 0;
}

static const struct ble_gatt_svc_def s_gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = BLE_UUID16_DECLARE(PASSPORT_SVC_UUID),
        .characteristics = (struct ble_gatt_chr_def[]) {
            {
                // RX Sync (Host -> Device)
                .uuid = BLE_UUID16_DECLARE(PASSPORT_CHR_RX_UUID),
                .access_cb = gatt_chr_access_rx,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
            },
            {
                // TX Status / ACK (Device -> Host)
                .uuid = BLE_UUID16_DECLARE(PASSPORT_CHR_TX_UUID),
                .access_cb = gatt_chr_access_tx,
                .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &s_tx_val_handle,
            },
            {
                // Live Telemetry (Host -> Device)
                .uuid = BLE_UUID16_DECLARE(PASSPORT_CHR_LIVE_UUID),
                .access_cb = gatt_chr_access_live,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
            },
            { 0 }
        },
    },
    { 0 }
};

static void passport_ble_on_sync(void)
{
    int rc = ble_hs_util_ensure_addr(0);
    if (rc == 0) {
        rc = ble_hs_id_infer_auto(0, &s_own_addr_type);
    }
    if (rc != 0) {
        ESP_LOGE(TAG, "Error ensuring BLE address: %d", rc);
        return;
    }
    passport_ble_advertise();
}

static void passport_ble_host_task(void *param)
{
    (void)param;
    ESP_LOGI(TAG, "NimBLE host task started");
    nimble_port_run();
    nimble_port_freertos_deinit();
}

esp_err_t passport_ble_init(void)
{
    passport_reassembler_init(&s_reassembler);

    int rc = nimble_port_init();
    if (rc != 0) {
        ESP_LOGE(TAG, "Failed to init nimble port: %d", rc);
        return ESP_FAIL;
    }

    ble_hs_cfg.sync_cb = passport_ble_on_sync;

    ble_svc_gap_init();
    ble_svc_gatt_init();

    rc = ble_gatts_count_cfg(s_gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "Failed to count GATT svcs: %d", rc);
        return ESP_FAIL;
    }

    rc = ble_gatts_add_svcs(s_gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "Failed to add GATT svcs: %d", rc);
        return ESP_FAIL;
    }

    rc = ble_svc_gap_device_name_set(DEVICE_NAME);
    if (rc != 0) {
        ESP_LOGW(TAG, "Failed to set device name: %d", rc);
    }

    nimble_port_freertos_init(passport_ble_host_task);
    ESP_LOGI(TAG, "Codex Passport BLE initialized successfully.");
    return ESP_OK;
}

bool passport_ble_is_connected(void)
{
    return s_connected;
}

esp_err_t passport_ble_send_ack(uint8_t ack_msg_type, uint8_t status)
{
    if (!s_connected || s_conn_handle == BLE_HS_CONN_HANDLE_NONE || s_tx_val_handle == 0) {
        return ESP_FAIL;
    }

    passport_ack_t ack = {
        .ack_msg_type = ack_msg_type,
        .status = status,
    };

    uint8_t frame_buf[sizeof(passport_frame_header_t) + sizeof(passport_ack_t) + 2];
    size_t frame_len = passport_create_frame(MSG_TYPE_ACK, 0, 1,
                                            (const uint8_t *)&ack, sizeof(ack),
                                            frame_buf, sizeof(frame_buf));

    if (frame_len == 0) return ESP_FAIL;

    struct os_mbuf *om = ble_hs_mbuf_from_flat(frame_buf, frame_len);
    if (!om) return ESP_FAIL;

    int rc = ble_gatts_notify_custom(s_conn_handle, s_tx_val_handle, om);
    if (rc != 0) {
        ESP_LOGW(TAG, "Failed to send BLE notification: %d", rc);
        return ESP_FAIL;
    }
    return ESP_OK;
}

#else

// Host stub
esp_err_t passport_ble_init(void) { return 0; }
bool passport_ble_is_connected(void) { return false; }
esp_err_t passport_ble_send_ack(uint8_t ack_msg_type, uint8_t status)
{
    (void)ack_msg_type; (void)status;
    return 0;
}

#endif
