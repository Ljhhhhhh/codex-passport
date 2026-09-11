// test_passport_protocol.c - Host unit tests for Codex Passport protocol and reassembly
#include "passport_protocol.h"
#include "passport_storage.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void test_crc16(void)
{
    printf("[TEST] Running test_crc16...\n");
    const char *test_str = "123456789";
    uint16_t crc = passport_crc16((const uint8_t *)test_str, strlen(test_str));
    // Standard CRC-16-CCITT (polynomial 0x1021, init 0xFFFF) for "123456789" is 0x29B1
    assert(crc == 0x29B1);
    printf("[TEST] test_crc16 PASSED (CRC=0x%04X)\n", crc);
}

static void test_frame_creation(void)
{
    printf("[TEST] Running test_frame_creation...\n");
    uint8_t payload[32];
    for (int i = 0; i < 32; i++) payload[i] = (uint8_t)(i * 3 + 1);

    uint8_t frame[256];
    size_t frame_len = passport_create_frame(MSG_TYPE_STATS, 0, 1, payload, sizeof(payload), frame, sizeof(frame));
    assert(frame_len == sizeof(passport_frame_header_t) + sizeof(payload) + 2);

    const passport_frame_header_t *hdr = (const passport_frame_header_t *)frame;
    assert(hdr->magic[0] == PASSPORT_MAGIC_0);
    assert(hdr->magic[1] == PASSPORT_MAGIC_1);
    assert(hdr->version == PASSPORT_PROTOCOL_VER);
    assert(hdr->msg_type == MSG_TYPE_STATS);
    assert(hdr->seq == 0);
    assert(hdr->total_seq == 1);

    uint16_t plen = ((uint16_t)frame[sizeof(passport_frame_header_t) - 2] << 8) | frame[sizeof(passport_frame_header_t) - 1];
    assert(plen == sizeof(payload));

    uint16_t expected_crc = passport_crc16(frame, frame_len - 2);
    uint16_t frame_crc = ((uint16_t)frame[frame_len - 2] << 8) | frame[frame_len - 1];
    assert(expected_crc == frame_crc);
    printf("[TEST] test_frame_creation PASSED\n");
}

static void test_reassembly_single_frame(void)
{
    printf("[TEST] Running test_reassembly_single_frame...\n");
    passport_reassembler_t r;
    passport_reassembler_init(&r);

    passport_stats_t stats = {
        .total_tokens = 123456789ULL,
        .today_tokens = 987654UL,
        .week_tokens = 5432100UL,
        .streak_days = 7,
    };

    uint8_t frame[256];
    size_t frame_len = passport_create_frame(MSG_TYPE_STATS, 0, 1,
                                            (const uint8_t *)&stats, sizeof(stats),
                                            frame, sizeof(frame));

    uint8_t out_type = 0;
    uint8_t *out_payload = NULL;
    size_t out_len = 0;

    bool ok = passport_reassembler_feed(&r, frame, frame_len, &out_type, &out_payload, &out_len);
    assert(ok == true);
    assert(out_type == MSG_TYPE_STATS);
    assert(out_len == sizeof(passport_stats_t));

    const passport_stats_t *received = (const passport_stats_t *)out_payload;
    assert(received->total_tokens == 123456789ULL);
    assert(received->today_tokens == 987654UL);
    assert(received->week_tokens == 5432100UL);
    assert(received->streak_days == 7);
    printf("[TEST] test_reassembly_single_frame PASSED\n");
}

static void test_reassembly_multi_frame(void)
{
    printf("[TEST] Running test_reassembly_multi_frame...\n");
    passport_reassembler_t r;
    passport_reassembler_init(&r);

    passport_profile_t prof;
    memset(&prof, 0, sizeof(prof));
    strcpy(prof.name, "GuanMo");
    strcpy(prof.interests, "读书 / 开发 / 运动");
    strcpy(prof.signature, "难，是幸福的开始");
    strcpy(prof.homepage, "https://github.com/Ljhhhhhh");
    strcpy(prof.issue_date, "2026-09-08");

    // Profile is 384 bytes, split into two chunks: 240 + 144
    size_t total_payload_len = sizeof(passport_profile_t);
    size_t chunk0_len = 240;
    size_t chunk1_len = total_payload_len - chunk0_len;

    uint8_t frame0[300];
    uint8_t frame1[300];

    size_t flen0 = passport_create_frame(MSG_TYPE_PROFILE, 0, 2,
                                         (const uint8_t *)&prof, chunk0_len,
                                         frame0, sizeof(frame0));
    size_t flen1 = passport_create_frame(MSG_TYPE_PROFILE, 1, 2,
                                         ((const uint8_t *)&prof) + chunk0_len, chunk1_len,
                                         frame1, sizeof(frame1));

    uint8_t out_type = 0;
    uint8_t *out_payload = NULL;
    size_t out_len = 0;

    // Feeding chunk 0: not complete yet
    bool ok0 = passport_reassembler_feed(&r, frame0, flen0, &out_type, &out_payload, &out_len);
    assert(ok0 == false);

    // Feeding chunk 1: completes message
    bool ok1 = passport_reassembler_feed(&r, frame1, flen1, &out_type, &out_payload, &out_len);
    assert(ok1 == true);
    assert(out_type == MSG_TYPE_PROFILE);
    assert(out_len == sizeof(passport_profile_t));

    const passport_profile_t *p_rec = (const passport_profile_t *)out_payload;
    assert(strcmp(p_rec->name, "GuanMo") == 0);
    assert(strcmp(p_rec->interests, "读书 / 开发 / 运动") == 0);
    assert(strcmp(p_rec->signature, "难，是幸福的开始") == 0);
    assert(strcmp(p_rec->homepage, "https://github.com/Ljhhhhhh") == 0);
    assert(strcmp(p_rec->issue_date, "2026-09-08") == 0);

    printf("[TEST] test_reassembly_multi_frame PASSED\n");
}

static void test_corrupted_crc_rejection(void)
{
    printf("[TEST] Running test_corrupted_crc_rejection...\n");
    passport_reassembler_t r;
    passport_reassembler_init(&r);

    uint8_t data[] = "Corrupted frame test payload";
    uint8_t frame[128];
    size_t flen = passport_create_frame(MSG_TYPE_STATS, 0, 1, data, sizeof(data), frame, sizeof(frame));

    // Corrupt one byte in payload
    frame[sizeof(passport_frame_header_t) + 3] ^= 0x55;

    uint8_t out_type = 0;
    uint8_t *out_payload = NULL;
    size_t out_len = 0;

    bool ok = passport_reassembler_feed(&r, frame, flen, &out_type, &out_payload, &out_len);
    assert(ok == false);
    printf("[TEST] test_corrupted_crc_rejection PASSED\n");
}

static void test_out_of_order_sequence_rejection(void)
{
    printf("[TEST] Running test_out_of_order_sequence_rejection...\n");
    passport_reassembler_t r;
    passport_reassembler_init(&r);

    uint8_t data[100] = {0};
    uint8_t frame[200];
    // Create chunk 1 of 2 directly without chunk 0
    size_t flen = passport_create_frame(MSG_TYPE_HEATMAP, 1, 2, data, sizeof(data), frame, sizeof(frame));

    uint8_t out_type = 0;
    uint8_t *out_payload = NULL;
    size_t out_len = 0;

    bool ok = passport_reassembler_feed(&r, frame, flen, &out_type, &out_payload, &out_len);
    assert(ok == false);
    printf("[TEST] test_out_of_order_sequence_rejection PASSED\n");
}

static void test_storage_defaults(void)
{
    printf("[TEST] Running test_storage_defaults...\n");
    passport_profile_t p;
    passport_stats_t s;
    passport_heatmap_t h;
    passport_footprints_t f;
    passport_directions_t d;

    assert(passport_storage_init() == 0);
    assert(passport_storage_load_all(&p, &s, &h, &f, &d) == 0);

    assert(strcmp(p.name, "GuanMo") == 0);
    assert(strcmp(p.interests, "读书 / 开发 / 运动") == 0);
    assert(strcmp(p.signature, "In me the tiger sniffs the rose.") == 0);
    assert(strcmp(p.homepage, "https://github.com/Ljhhhhhh") == 0);
    assert(strcmp(p.issue_date, "2026-09-08") == 0);

    assert(s.total_tokens > 0);
    assert(s.today_tokens > 0);
    assert(s.streak_days >= 1);

    printf("[TEST] test_storage_defaults PASSED\n");
}

int main(void)
{
    printf("========================================\n");
    printf("  Running Codex Passport Protocol Tests \n");
    printf("========================================\n");

    test_crc16();
    test_frame_creation();
    test_reassembly_single_frame();
    test_reassembly_multi_frame();
    test_corrupted_crc_rejection();
    test_out_of_order_sequence_rejection();
    test_storage_defaults();

    printf("ALL CODEX PASSPORT PROTOCOL TESTS PASSED!\n");
    return 0;
}
