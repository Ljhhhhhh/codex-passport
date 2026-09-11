#include "passport_idle.h"

void passport_idle_init(passport_idle_t *idle)
{
    if (!idle) {
        return;
    }
    idle->awake = 1;
    idle->idle_ms = 0;
    idle->unread_count = UINT32_MAX;
}

passport_idle_act_t passport_idle_set_unread(passport_idle_t *idle, uint32_t count)
{
    if (!idle) return PASSPORT_IDLE_NONE;
    if (idle->unread_count != count) idle->idle_ms = 0;
    idle->unread_count = count;
    if (count && !idle->awake) {
        idle->awake = 1;
        return PASSPORT_IDLE_WAKE;
    }
    return PASSPORT_IDLE_NONE;
}

passport_idle_act_t passport_idle_on_tick(passport_idle_t *idle, uint32_t dt_ms)
{
    if (!idle || !idle->awake || idle->unread_count || dt_ms == 0U) {
        return PASSPORT_IDLE_NONE;
    }
    if (idle->idle_ms >= PASSPORT_IDLE_MS) {
        return PASSPORT_IDLE_NONE;
    }
    if (dt_ms >= (PASSPORT_IDLE_MS - idle->idle_ms)) {
        idle->idle_ms = PASSPORT_IDLE_MS;
        idle->awake = 0;
        return PASSPORT_IDLE_SLEEP;
    }
    idle->idle_ms += dt_ms;
    return PASSPORT_IDLE_NONE;
}

passport_idle_act_t passport_idle_on_button(passport_idle_t *idle, int is_ok)
{
    if (!idle) {
        return PASSPORT_IDLE_NONE;
    }
    if (!idle->awake) {
        if (!is_ok) {
            return PASSPORT_IDLE_NONE;
        }
        idle->awake = 1;
        idle->idle_ms = 0;
        return PASSPORT_IDLE_WAKE;
    }
    idle->idle_ms = 0;
    return PASSPORT_IDLE_PASS;
}
