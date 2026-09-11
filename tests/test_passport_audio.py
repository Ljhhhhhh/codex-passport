"""Run the actual audio generator with a capturing codec to check its envelope."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class AudioTests(unittest.TestCase):
    def test_soft_envelope_and_write_failure(self):
        main = Path(__file__).resolve().parents[1] / 'main'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bsp_audio.h').write_text('''#include <stddef.h>
#include <stdint.h>
#define ESP_OK 0
int bsp_audio_init(void);
int bsp_audio_set_format(uint32_t hz, uint8_t bits, uint8_t channels);
void bsp_audio_set_volume(uint8_t volume);
int bsp_audio_write(const void *pcm, size_t bytes);
''')
            (root / 'esp_log.h').write_text('#define ESP_LOGW(tag, ...) ((void)(tag))\n')
            (root / 'check.c').write_text('''#include "passport_alert.h"
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
static int16_t samples[10000];
static size_t count;
static int fail;
int bsp_audio_init(void) { return 0; }
int bsp_audio_set_format(uint32_t hz, uint8_t bits, uint8_t channels) {
    assert(hz == 16000 && bits == 16 && channels == 1); return 0;
}
void bsp_audio_set_volume(uint8_t volume) { assert(volume <= 60); }
int bsp_audio_write(const void *pcm, size_t bytes) {
    if (fail) return -1;
    const int16_t *p = pcm;
    for (size_t i = 0; i < bytes / 2; ++i) samples[count++] = p[i];
    return 0;
}
int main(void) {
    passport_alert_play_chime();
    assert(count == 6784);
    int peak = 0;
    for (size_t i = 0; i < count; ++i) {
        if (abs(samples[i]) > peak) peak = abs(samples[i]);
        if (i) assert(abs(samples[i] - samples[i-1]) < 2600);
    }
    assert(peak > 1000 && peak < 10000);
    assert(samples[0] == 0 && samples[2879] == 0 && samples[3392] == 0);
    assert(samples[count-1] == 0);
    fail = 1; count = 0; passport_alert_play_chime(); assert(count == 0);
}
''')
            binary = root / 'check'
            subprocess.run(['cc', '-DESP_PLATFORM', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(root), '-I' + str(main), str(root / 'check.c'),
                            str(main / 'passport_alert.c'), '-lm', '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
