// passport_ble.h - NimBLE BLE GATT service for Codex Passport
#ifndef PASSPORT_BLE_H
#define PASSPORT_BLE_H

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

// BLE UUID definitions
#define PASSPORT_SVC_UUID             0xCD00
#define PASSPORT_CHR_RX_UUID          0xCD01 // Host -> Device (Sync data)
#define PASSPORT_CHR_TX_UUID          0xCD02 // Device -> Host (ACK / Notifications)
#define PASSPORT_CHR_LIVE_UUID        0xCD03 // Host -> Device (Realtime status)

// Initialize NimBLE stack, register GATT services and start advertising
esp_err_t passport_ble_init(void);

// Returns true if a host is currently connected via BLE
bool passport_ble_is_connected(void);
uint32_t passport_ble_unread_count(void);
bool passport_ble_take_alert(void);

// Send ACK packet to connected host
esp_err_t passport_ble_send_ack(uint8_t ack_msg_type, uint8_t status);

#ifdef __cplusplus
}
#endif

#endif // PASSPORT_BLE_H
