#include "passport_alert.h"
#include <assert.h>
#include <stdio.h>

static void test_alert_lifecycle(void)
{
    passport_alert_mgr_t mgr;
    passport_alert_init(&mgr);
    assert(!passport_alert_should_stay_awake(&mgr));
    assert(!passport_alert_tick(&mgr, 1000));

    // 1 pending alert arrives
    passport_alert_set_pending(&mgr, 1);
    assert(passport_alert_should_stay_awake(&mgr));
    // First tick triggers sound immediately
    assert(passport_alert_tick(&mgr, 10));
    // Next ticks before 60s do not trigger sound
    assert(!passport_alert_tick(&mgr, 30000));
    assert(!passport_alert_tick(&mgr, 29990));
    // Exactly at 60s since first sound, triggers second beep
    assert(passport_alert_tick(&mgr, 10));

    // Mark read
    passport_alert_mark_read(&mgr);
    assert(!passport_alert_should_stay_awake(&mgr));
    assert(!passport_alert_tick(&mgr, 100000));
}

int main(void)
{
    test_alert_lifecycle();
    printf("passport alert tests passed\n");
    return 0;
}
