#include "passport_alert.h"
#include <assert.h>
#include <stddef.h>

int main(void)
{
    uint32_t last = 0;
    assert(!passport_alert_accept(NULL, 1));
    assert(!passport_alert_accept(&last, 0));
    assert(passport_alert_accept(&last, 1));
    assert(!passport_alert_accept(&last, 1));
    assert(passport_alert_accept(&last, 3));
    assert(!passport_alert_accept(&last, 2));
    last = 0; /* reconnect starts a fresh session */
    assert(passport_alert_accept(&last, 1));
    return 0;
}
