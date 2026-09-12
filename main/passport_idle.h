#pragma once

#include <stdint.h>

#define PASSPORT_IDLE_MS 15000U

typedef enum {
    PASSPORT_IDLE_NONE = 0,
    PASSPORT_IDLE_SLEEP,
    PASSPORT_IDLE_WAKE,
    PASSPORT_IDLE_PASS
} passport_idle_act_t;

typedef struct {
    uint8_t awake;
    uint32_t idle_ms;
    uint32_t unread_count;
} passport_idle_t;

void passport_idle_init(passport_idle_t *idle);
passport_idle_act_t passport_idle_set_unread(passport_idle_t *idle, uint32_t count);
passport_idle_act_t passport_idle_on_tick(passport_idle_t *idle, uint32_t dt_ms);
passport_idle_act_t passport_idle_on_button(passport_idle_t *idle, int is_ok);
