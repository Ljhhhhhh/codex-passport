<p align="right">
  <a href="README.zh_CN.md">简体中文</a> · <strong>English</strong>
</p>

# Codex Passport (`codex-passport`)

A personal digital identity and activity companion for OpenAI Codex on the ESP32-C3 FoloToy AI Passport (240 × 320).

## Message List and Status

The device starts on **MESSAGES**. UP/DOWN cycles Home, Quota and Messages; on Messages, OK requests the next group of three messages. OK opens QR on other pages. A changed message snapshot wakes a sleeping screen for 30 seconds.

Restart the Mac service after upgrading the firmware: `projects/codex-passport/tools/passport-sync restart`. `passport-sync logs` reports **Projects ACK** only after the device acknowledges a message page. An older firmware produces an explicit upgrade message.

Messages display unread completed, waiting input, and failed tasks, each showing real task title, status, and project name. Tasks in the same project are listed individually. Outstanding input questions take precedence as waiting input. Waiting input and failed tasks are not limited to today's records; unread completed tasks are backfilled using desktop unread IDs. If unread source fails, synchronization error is reported. Running and interrupted tasks are excluded; re-running a task removes previous message status. Sorted by status update time descending; empty list shows "No Messages".

Device-side read-receipt marking is not included. Short ID is displayed if title is missing. Usage statistics still come from the existing usage collector.

## Screens

- **Home**: Name, last BLE sync time, today's tokens, plus lifetime / last 7 days / streak.
- **Quota**: Three Codex login accounts, each with 5-hour and weekly limit percent.
- **Messages**: Message list of unread completed, waiting input, and failed tasks, three per page.
- **QR** (OK on other pages): GitHub homepage.

Status bar: BLE, Codex state (`IDLE` / `RUN` / `WAIT` / `DONE` / `ERR`), battery. While a session is active, a live line shows the active task's project and duration.

## Buttons

| Button | Action |
| :--- | :--- |
| `UP` | Previous page |
| `DOWN` | Next page |
| `OK` | Next group on Messages; open or close QR elsewhere |

The screen stays on while the Codex app has unread tasks across hosts and projects. Open the corresponding tasks in Codex to clear them; device buttons do not mark tasks read. Once the unread count reaches zero, the backlight turns off after 30 seconds idle. `OK` wakes it without toggling QR. `UP` and `DOWN` do not wake the screen. Until the unread count is available, or if BLE disconnects or the app state cannot be read, the screen stays on.

The Mac reads `electron-thread-read-state-v1` (with fallback to legacy `unread-thread-ids-by-host-v1`) from `$CODEX_HOME/.codex-global-state.json` (default `~/.codex`), syncing changes every two seconds.

## Flash

Merged image (flash at `0x0`):

`build/codex-passport-full.bin`

Web flasher: connect the ESP32-C3 USB JTAG port, start address `0x0`, baud `460800`.

Or from an ESP-IDF 5.5.3 shell:

```bash
idf.py -C projects/codex-passport flash
```

Flashing the merged image from `0x0` reloads factory profile defaults.

## Sync from the Mac

The device advertises as `Codex-Passport`. Install the login agent once:

```bash
projects/codex-passport/tools/passport-sync install
```

That starts BLE sync now, again at login, and after crashes. Control it with `start` / `stop` / `restart` / `status` / `logs`, or from Raycast: Settings → Extensions → Script Commands → Add Directories → `projects/codex-passport/tools/raycast`. Search `Codex Passport`.

Foreground (no login agent): `python3 projects/codex-passport/tools/assistant.py --sync --interval 60` after `pip install bleak`. Optional: `--device <address>`, `--config path/to/config.json`, `--interval 120`.

The device is BLE-only. Wi-Fi is not used: the ESP32-C3 already runs LVGL and NimBLE without PSRAM, and the Mac must be nearby to read `~/.opencodex`.

This prefers local `~/.opencodex/usage.jsonl` (the same ledger as the OpenCodex dashboard at `/#usage`), deduplicates by `requestId`, and maps the last 30 days' top models onto the directions page. If that file is absent, it falls back to `~/.codex/sessions` and `response_id`.

A sanitized template is `projects/codex-passport/config.example.json`. Keep a real profile out of git.

## Validation

```bash
./tools/validate.sh --static
./tools/validate.sh --firmware codex-passport
```

## Design

[docs/software-design/codex-passport-design.md](docs/codex-passport-design.md)
