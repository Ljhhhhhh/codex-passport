#include "passport_idle.h"

#include <assert.h>
#include <stdio.h>

static void test_sleeps_at_thirty_seconds(void)
{
    passport_idle_t idle;
    passport_idle_init(&idle);
    passport_idle_set_unread(&idle, 0);
    assert(idle.awake == 1);
    assert(passport_idle_on_tick(&idle, 29999U) == PASSPORT_IDLE_NONE);
    assert(idle.awake == 1);
    assert(passport_idle_on_tick(&idle, 1U) == PASSPORT_IDLE_SLEEP);
    assert(idle.awake == 0);
    assert(idle.idle_ms == PASSPORT_IDLE_MS);
    assert(passport_idle_on_tick(&idle, 1000U) == PASSPORT_IDLE_NONE);
    assert(idle.awake == 0);
}

static void test_ok_wakes_other_keys_do_not(void)
{
    passport_idle_t idle;
    passport_idle_init(&idle);
    passport_idle_set_unread(&idle, 0);
    assert(passport_idle_on_tick(&idle, PASSPORT_IDLE_MS) == PASSPORT_IDLE_SLEEP);

    assert(passport_idle_on_button(&idle, 0) == PASSPORT_IDLE_NONE);
    assert(idle.awake == 0);

    assert(passport_idle_on_button(&idle, 1) == PASSPORT_IDLE_WAKE);
    assert(idle.awake == 1);
    assert(idle.idle_ms == 0);
}

static void test_awake_button_resets_idle(void)
{
    passport_idle_t idle;
    passport_idle_init(&idle);
    passport_idle_set_unread(&idle, 0);
    assert(passport_idle_on_tick(&idle, 9000U) == PASSPORT_IDLE_NONE);
    assert(passport_idle_on_button(&idle, 0) == PASSPORT_IDLE_PASS);
    assert(idle.idle_ms == 0);
    assert(passport_idle_on_tick(&idle, 9000U) == PASSPORT_IDLE_NONE);
    assert(idle.awake == 1);
}

int main(void)
{
    passport_idle_t idle;
    passport_idle_init(&idle);
    assert(passport_idle_on_tick(&idle, 60000U) == PASSPORT_IDLE_NONE);
    passport_idle_set_unread(&idle, 2);
    assert(passport_idle_on_tick(&idle, 60000U) == PASSPORT_IDLE_NONE);
    passport_idle_set_unread(&idle, 1);
    passport_idle_on_button(&idle, 1);
    assert(passport_idle_on_tick(&idle, 60000U) == PASSPORT_IDLE_NONE);
    passport_idle_set_unread(&idle, 0);
    assert(passport_idle_on_tick(&idle, 29999U) == PASSPORT_IDLE_NONE);
    assert(passport_idle_on_tick(&idle, 1U) == PASSPORT_IDLE_SLEEP);
    assert(passport_idle_set_unread(&idle, 1) == PASSPORT_IDLE_WAKE);
    passport_idle_set_unread(&idle, 0);
    assert(passport_idle_on_tick(&idle, 30000U) == PASSPORT_IDLE_SLEEP);
    assert(passport_idle_set_unread(&idle, UINT32_MAX) == PASSPORT_IDLE_WAKE);
    assert(passport_idle_on_tick(&idle, UINT32_MAX) == PASSPORT_IDLE_NONE);
    test_sleeps_at_thirty_seconds();
    test_ok_wakes_other_keys_do_not();
    test_awake_button_resets_idle();
    printf("passport idle tests passed\n");
    return 0;
}
