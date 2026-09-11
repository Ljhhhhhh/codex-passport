// passport_protocol.h - Binary protocol and frame fragmentation for Codex Passport
#ifndef PASSPORT_PROTOCOL_H
#define PASSPORT_PROTOCOL_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PASSPORT_MAGIC_0        0x50  // 'P'
#define PASSPORT_MAGIC_1        0x54  // 'T'
#define PASSPORT_PROTOCOL_VER   0x01
#define PASSPORT_MAX_CHUNK_LEN  240
#define PASSPORT_MAX_MSG_LEN    1024

typedef enum {
    MSG_TYPE_PROFILE     = 0x01,
    MSG_TYPE_STATS       = 0x02,
    MSG_TYPE_HEATMAP     = 0x03,
    MSG_TYPE_FOOTPRINTS  = 0x04,
    MSG_TYPE_DIRECTIONS  = 0x05,
    MSG_TYPE_REALTIME    = 0x06,
    MSG_TYPE_ACK         = 0x07,
    MSG_TYPE_QUOTA       = 0x08,
    MSG_TYPE_PROJECTS    = 0x09,
    MSG_TYPE_MESSAGES    = 0x09, // alias for task messages page
    MSG_TYPE_ALERT       = 0x0C, // session-local uint32 event sequence
    MSG_TYPE_UNREAD      = 0x0A, // uint32 little-endian; UINT32_MAX means unknown
} passport_msg_type_t;

typedef enum {
    CODEX_STATE_IDLE          = 0,
    CODEX_STATE_RUNNING       = 1,
    CODEX_STATE_WAITING_INPUT = 2,
    CODEX_STATE_COMPLETED     = 3,
    CODEX_STATE_ERROR         = 4,
} codex_realtime_state_t;

#pragma pack(push, 1)

typedef struct {
    uint8_t magic[2];      // 'P', 'T'
    uint8_t version;       // 1
    uint8_t msg_type;      // passport_msg_type_t
    uint8_t seq;           // chunk index 0..total_seq-1
    uint8_t total_seq;     // total number of chunks
    uint16_t payload_len;  // big-endian length of this chunk payload
} passport_frame_header_t;

typedef struct {
    char name[48];
    char interests[96];
    char signature[96];
    char homepage[128];
    char issue_date[16];
} passport_profile_t;

typedef struct {
    uint64_t total_tokens;
    uint32_t today_tokens;
    uint32_t week_tokens;
    uint16_t streak_days;
    char synced_at[16];  // host local "MM-DD HH:MM"
} passport_stats_t;


#define PASSPORT_QUOTA_ACCOUNTS 3

typedef struct {
    char name[12];
    uint8_t short_percent;
    uint8_t weekly_percent;
    uint32_t short_remaining_sec;
    uint32_t weekly_remaining_sec;
} passport_quota_account_t;

typedef struct {
    uint8_t count;
    uint8_t short_window_hours;
    passport_quota_account_t items[PASSPORT_QUOTA_ACCOUNTS];
} passport_quota_t;

typedef struct {
    uint8_t levels[91];  // 13 weeks * 7 days (0..4 intensity)
    char start_date[16];
    char end_date[16];
    uint16_t active_days;
    uint32_t max_daily_tokens;
} passport_heatmap_t;

typedef struct {
    char topic[32];
    char first_date[16];
    uint64_t total_tokens;
} passport_footprint_item_t;

typedef struct {
    uint8_t count;
    passport_footprint_item_t items[6];
} passport_footprints_t;

typedef struct {
    char name[32];
    uint32_t tokens;
    uint8_t percent;
} passport_direction_item_t;

#define PASSPORT_DIRECTIONS_MAX 5

typedef struct {
    uint8_t count;
    passport_direction_item_t items[PASSPORT_DIRECTIONS_MAX];
} passport_directions_t;

typedef struct {
    uint8_t state;         // codex_realtime_state_t
    uint16_t duration_sec;
    uint32_t turn_tokens;
    uint32_t today_tokens;
    char project_name[32];
} passport_realtime_t;

typedef struct {
    char title[64];
    char project[32];
    uint8_t status; // 1=WAIT, 2=DONE, 3=ERR
} passport_message_item_t;

#define PASSPORT_MESSAGES_PER_PAGE 3
#define PASSPORT_PROJECTS_PER_PAGE PASSPORT_MESSAGES_PER_PAGE

typedef struct {
    uint8_t count;
    uint8_t page_index;
    uint8_t total_pages;
    passport_message_item_t items[PASSPORT_MESSAGES_PER_PAGE];
} passport_messages_page_t;

typedef passport_message_item_t passport_project_item_t;
typedef passport_messages_page_t passport_projects_page_t;

typedef struct {
    char short_id[16];
    uint8_t state;
    uint8_t is_read;
    uint16_t duration_sec;
    char status_label[24];
} passport_task_item_t;

typedef struct {
    char project_name[32];
    uint8_t count;
    passport_task_item_t items[4];
} passport_tasks_page_t;


typedef struct {
    uint8_t ack_msg_type;
    uint8_t status;  // 0 = OK, 1 = CRC_ERR, 2 = SEQ_ERR
} passport_ack_t;

#pragma pack(pop)

typedef struct {
    uint8_t active_msg_type;
    uint8_t expected_seq;
    uint8_t total_seq;
    size_t assembled_len;
    uint8_t buffer[PASSPORT_MAX_MSG_LEN];
    bool in_progress;
} passport_reassembler_t;

// Checksum calculation (CRC-16-CCITT 0x1021)
uint16_t passport_crc16(const uint8_t *data, size_t len);

// Create a single framed chunk with header and CRC trailer
size_t passport_create_frame(uint8_t msg_type,
                             uint8_t seq,
                             uint8_t total_seq,
                             const uint8_t *payload,
                             uint16_t payload_len,
                             uint8_t *out_buf,
                             size_t out_max);

// Reassembler interface
void passport_reassembler_init(passport_reassembler_t *r);
void passport_reassembler_reset(passport_reassembler_t *r);

// Feeds incoming raw frame into reassembler.
// Returns true when a full message is completed and verified.
bool passport_reassembler_feed(passport_reassembler_t *r,
                              const uint8_t *frame_data,
                              size_t frame_len,
                              uint8_t *out_msg_type,
                              uint8_t **out_payload,
                              size_t *out_payload_len);

#ifdef __cplusplus
}
#endif

#endif // PASSPORT_PROTOCOL_H
