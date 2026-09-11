// passport_protocol.c - Protocol implementation and frame fragmentation
#include "passport_protocol.h"
#include <string.h>

uint16_t passport_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc = crc << 1;
            }
        }
    }
    return crc;
}

size_t passport_create_frame(uint8_t msg_type,
                             uint8_t seq,
                             uint8_t total_seq,
                             const uint8_t *payload,
                             uint16_t payload_len,
                             uint8_t *out_buf,
                             size_t out_max)
{
    size_t header_len = sizeof(passport_frame_header_t);
    size_t total_frame_len = header_len + payload_len + 2; // +2 for CRC

    if (!out_buf || out_max < total_frame_len || payload_len > PASSPORT_MAX_CHUNK_LEN) {
        return 0;
    }

    passport_frame_header_t *hdr = (passport_frame_header_t *)out_buf;
    hdr->magic[0] = PASSPORT_MAGIC_0;
    hdr->magic[1] = PASSPORT_MAGIC_1;
    hdr->version = PASSPORT_PROTOCOL_VER;
    hdr->msg_type = msg_type;
    hdr->seq = seq;
    hdr->total_seq = total_seq;
    hdr->payload_len = ((payload_len & 0xFF) << 8) | ((payload_len >> 8) & 0xFF); // Big-endian

    if (payload_len > 0 && payload) {
        memcpy(out_buf + header_len, payload, payload_len);
    }

    // CRC over header and payload
    uint16_t crc = passport_crc16(out_buf, header_len + payload_len);
    out_buf[header_len + payload_len] = (crc >> 8) & 0xFF;
    out_buf[header_len + payload_len + 1] = crc & 0xFF;

    return total_frame_len;
}

void passport_reassembler_init(passport_reassembler_t *r)
{
    if (!r) return;
    memset(r, 0, sizeof(passport_reassembler_t));
}

void passport_reassembler_reset(passport_reassembler_t *r)
{
    if (!r) return;
    r->active_msg_type = 0;
    r->expected_seq = 0;
    r->total_seq = 0;
    r->assembled_len = 0;
    r->in_progress = false;
}

bool passport_reassembler_feed(passport_reassembler_t *r,
                              const uint8_t *frame_data,
                              size_t frame_len,
                              uint8_t *out_msg_type,
                              uint8_t **out_payload,
                              size_t *out_payload_len)
{
    if (!r || !frame_data || frame_len < sizeof(passport_frame_header_t) + 2) {
        return false;
    }

    const passport_frame_header_t *hdr = (const passport_frame_header_t *)frame_data;
    if (hdr->magic[0] != PASSPORT_MAGIC_0 || hdr->magic[1] != PASSPORT_MAGIC_1) {
        return false;
    }
    if (hdr->version != PASSPORT_PROTOCOL_VER) {
        return false;
    }

    uint16_t payload_len = ((uint16_t)hdr->payload_len >> 8) | ((uint16_t)(hdr->payload_len & 0xFF) << 8);
    size_t expected_total_len = sizeof(passport_frame_header_t) + payload_len + 2;
    if (frame_len != expected_total_len) {
        return false;
    }

    // Verify CRC
    uint16_t expected_crc = ((uint16_t)frame_data[frame_len - 2] << 8) | frame_data[frame_len - 1];
    uint16_t computed_crc = passport_crc16(frame_data, frame_len - 2);
    if (expected_crc != computed_crc) {
        return false;
    }

    uint8_t seq = hdr->seq;
    uint8_t total_seq = hdr->total_seq;
    uint8_t msg_type = hdr->msg_type;

    if (total_seq == 0 || seq >= total_seq) {
        passport_reassembler_reset(r);
        return false;
    }

    // First frame of a message
    if (seq == 0) {
        passport_reassembler_reset(r);
        r->active_msg_type = msg_type;
        r->total_seq = total_seq;
        r->expected_seq = 1;
        r->in_progress = true;
        r->assembled_len = 0;
    } else {
        // Subsequent frame must match
        if (!r->in_progress || r->active_msg_type != msg_type || seq != r->expected_seq) {
            passport_reassembler_reset(r);
            return false;
        }
        r->expected_seq++;
    }

    // Check buffer overflow
    if (r->assembled_len + payload_len > PASSPORT_MAX_MSG_LEN) {
        passport_reassembler_reset(r);
        return false;
    }

    if (payload_len > 0) {
        const uint8_t *payload_ptr = frame_data + sizeof(passport_frame_header_t);
        memcpy(r->buffer + r->assembled_len, payload_ptr, payload_len);
        r->assembled_len += payload_len;
    }

    // Message complete
    if (seq == total_seq - 1) {
        if (out_msg_type) *out_msg_type = r->active_msg_type;
        if (out_payload) *out_payload = r->buffer;
        if (out_payload_len) *out_payload_len = r->assembled_len;
        r->in_progress = false;
        return true;
    }

    return false;
}
