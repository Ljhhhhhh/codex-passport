#pragma once

#include <stdbool.h>
#include <stdint.h>

bool passport_alert_accept(uint32_t *last_sequence, uint32_t sequence);
void passport_alert_play_chime(void);
