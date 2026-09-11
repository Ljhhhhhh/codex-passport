<p align="right">
  <a href="codex-passport-design.zh_CN.md">简体中文</a> · <strong>English</strong>
</p>

# Codex Passport Software Design

This document specifies the software architecture, BLE communication protocol, state machine, data persistence, and user interface for the FoloToy AI Passport running as a dedicated **Codex Passport** companion.

## 1. System Overview

Codex Passport transforms the ESP32-C3 FoloToy AI Passport (240 × 320 ST7789P3 LCD, 3-button ADC ladder, CW2017 fuel gauge, NimBLE BLE) into a personal digital credential and activity visualizer for Codex coding sessions.

Key objectives:
1. **Personal Identity Credential**: Display owner name, motto, issue date, today's tokens, and GitHub QR code.
2. **Offline Local Token Analytics**: Parse local `~/.codex/sessions/**/*.jsonl` without cloud dependencies or external LLM calls. Extract incremental tokens via `token_usage_record`, deduplicate by `response_id`, and produce total, daily, weekly, streak, and 13-week activity heatmaps.
3. **Project Footprints & Directions**: Derive topic footprints (first active date and cumulative tokens) and recent 30-day top projects from directory paths and project names.
4. **Ambient Realtime Status**: Track live session events (Idle, Running, Waiting for Input, Completed, Error) with active project name, turn duration, turn tokens, today tokens, and automatic idle timeout.
5. **Robust BLE & Persistence**: BLE transport via NimBLE with packet fragmentation, versioning, length checks, and CRC16; persistent flash storage via NVS so the passport remains readable after reboot.

```text
+-------------------------------------------------------------+
|                      Host Workstation                       |
|                                                             |
|   ~/.codex/sessions/**/*.jsonl ──> [ Session Parser ]       |
|                                            │                |
|   Local Profile (config.json)  ──> [ Analytics Aggregator ] |
|                                            │                |
|   Active Session Watcher       ──> [ Realtime Engine ]      |
|                                            │                |
|                                   [ BLE Sync Manager ]      |
+--------------------------------------------┬----------------+
                                             │ BLE (NimBLE GATT)
                                             │ Chunked + CRC16
+--------------------------------------------┴----------------+
|                 FoloToy AI Passport (ESP32-C3)              |
|                                                             |
|   [ NimBLE Peripheral ] ──> [ Frame Reassembly & CRC ]      |
|                                            │                |
|                                     [ NVS Manager ]         |
|                                            │                |
|               [ Status Bar & LVGL UI ]                      |
|            (Home / Quota / Heatmap / Directions / QR)       |
+-------------------------------------------------------------+
```

---

## 2. Personal Profile Specification

Default initialization:
- Name: `GuanMo`
- Interests: `Reading / Dev / Sports` (synced, not shown on the home page)
- Signature: `In me the tiger sniffs the rose.`
- Homepage: `https://github.com/Ljhhhhhh`

Configuration rules:
- Stored locally at `~/.codex-passport/config.json` (or repo-local uncommitted file), never committed to Git.
- A sanitized template `config.example.json` is provided in the repository.
- Profile fields are synchronized to the device over BLE and saved in NVS namespace `codex_passport`.

---

## 3. Codex Usage Analytics Engine

- Preferred source: `~/.opencodex/usage.jsonl` when present (same local ledger as the OpenCodex `/#usage` dashboard). Deduplicate by `requestId`. Directions become the top 5 models in the last 30 days; footprints group by provider (`OpenAI / Codex`, `xAI Grok`, `Gemini`).
- Fallback source: `~/.codex/sessions/**/*.jsonl` and archived sessions in `~/.codex/archived_sessions/`.
- Event extraction (fallback): Parses `token_usage_record` lines.
- Deduplication (fallback): Uses `response_id` (or `(session_id, turn_id, ordinal)` fallback when `response_id` is empty) to ensure turn and thread cumulative totals are not re-summed.
- Metrics generated:
  - `total_tokens`: Grand total tokens recorded across all processed sessions.
  - `today_tokens`: Incremental tokens recorded on the current calendar day (local timezone).
  - `week_tokens`: Incremental tokens recorded in the current calendar week (Monday to Sunday).
  - `streak_days`: Current consecutive active days with recorded Codex usage.
  - `heatmap_91d`: 13-week (91-day) activity matrix with 5 normalized intensity levels (0 to 4).

### 3.2 Footprints & Recent Directions
- Path mapping: Analyzes `turn_context.payload.cwd` and directory structures.
- Deterministic heuristic topic classification:
  - Embedded / IoT: `ai-passport`, `esp32`, `bsp`, `hardware`, `iot`
  - Web & Frontend: `open-webui`, `frontend`, `ui`, `react`, `vue`, `web`
  - AI Systems & Agents: `agent`, `codex`, `llm`, `deepseek`, `draft`
  - Core Backend: `server`, `service`, `api`, `db`, `backend`
- Metrics:
  - Footprint topics: Topic title, first seen date (`YYYY-MM-DD`), and total tokens.
  - Focus directions: Top 5 projects (or OpenCodex models) by token volume in the last 30 days, including name, token count, and percentage share.
- Privacy guarantee: No session prompts, assistant outputs, or code contents are sent to external services or cloud models.

---

## 4. Realtime State Machine

Codex session events are mapped to five primary states:
1. `IDLE` (0): No active task in progress.
2. `RUNNING` (1): Agent active, executing LLM completion or tool calls.
3. `WAITING_INPUT` (2): Agent requires user confirmation, approval, or response.
4. `COMPLETED` (3): Turn or task finished successfully.
5. `ERROR` (4): Tool error or unrecoverable turn failure.

Auto-idle fallback:
- If no new event is detected within the configured timeout (default 90 seconds), state automatically transitions back to `IDLE`.
- Prevents the device from getting stuck in `RUNNING` if a terminal session is closed abruptly.

Realtime telemetry payload:
- `state`: Enum 0..4
- `duration_sec`: Elapsed seconds in active task
- `turn_tokens`: Token consumption of active turn
- `today_tokens`: Daily token accumulation
- `project_name`: Active workspace directory name

---

## 5. Device UI & Page Architecture

Screen resolution: 240 × 320 px.

### 5.1 Status Bar
- BLE connection indicator.
- Battery gauge from CW2017 when fitted.
- Live state stamp: `IDLE`, `RUN`, `WAIT`, `DONE`, `ERR`.
- When not idle, a live line shows the active project, duration, and turn tokens.

### 5.2 Pages
1. **Home**: Name, last BLE sync time, issue date, today's tokens, and a bottom strip of lifetime / last 7 days / streak.
2. **Quota**: Three Codex login accounts, each with 5-hour and weekly usage percent plus reset countdown, from local OpenCodex `/api/codex-auth/accounts`.
3. **Activity heatmap**: 13 × 7 (91 days), five gold intensity levels, active-day and peak summary.
4. **Directions**: Top 5 projects in the last 30 days with share bars.
5. **QR** (overlay): GitHub homepage; toggled with `OK` from any page.

Footprint topic payloads remain on BLE/NVS for host compatibility and are not shown on device.

### 5.3 Button Navigation
- `UP`: Previous page (closes QR first if open).
- `DOWN`: Next page (closes QR first if open).
- `OK`: Toggle QR code view.
- The backlight stays on while the Codex app has unread tasks. Open the corresponding tasks in Codex to clear unread status; device buttons do not mark them read. After the count reaches zero, 30 seconds idle turns the backlight off. Unknown unread state or BLE disconnection keeps it on. `OK` wakes it without toggling QR; `UP` and `DOWN` do not wake it.


---

## 6. BLE Protocol & Data Persistence

### 6.1 GATT Service Definition
- Service UUID: `0xCD00`
- RX Characteristic (`0xCD01`): Write / Write Without Response (Host -> Device, chunked frames).
- TX Characteristic (`0xCD02`): Read / Notify (Device -> Host, ACK and status).
- Live Characteristic (`0xCD03`): Write Without Response (Host -> Device, high-frequency realtime telemetry).

### 6.2 Framing & Fragmentation
Frame structure:
```text
+--------------+---------+----------+---------+-----------+-------------+---------+---------+
| Magic (2B)   | Ver(1B) | Type(1B) | Seq(1B) | Total(1B) | Len (2B BE) | Payload | CRC(2B) |
| 0x50 0x54    | 0x01    | 0x01..08 | 0..N    | N+1       | <= 240      | ...     | CRC-16  |
+--------------+---------+----------+---------+-----------+-------------+---------+---------+
```
Message types:
- `0x01`: Profile (Name, Interests, Signature, Homepage URL, Issue Date)
- `0x02`: Mileage Stats (Total, Today, Week, Streak)
- `0x03`: Heatmap (91 bytes activity levels 0..4)
- `0x04`: Footprint Topics (Serialized array of category, date, tokens)
- `0x05`: Focus Directions (Top 5 projects, tokens, percentages)
- `0x06`: Realtime Status (State, duration, turn tokens, today tokens, project)
- `0x07`: ACK (Acknowledged packet sequence or message completion)
- `0x08`: Quota (up to three Codex accounts: 5-hour percent, weekly percent, remaining seconds)

CRC-16-CCITT (`0x1021`) covers header and payload.

`0x0A` carries the app's global unread task count as a four-byte little-endian unsigned integer; `0xFFFFFFFF` means unknown. TX status byte 4 is `1` when this capability is supported. The host reads `electron-persisted-atom-state.unread-thread-ids-by-host-v1` in `.codex-global-state.json` and requires the device ACK before considering a changed count synchronized.

### 6.3 NVS Persistence
Namespace: `codex_passport`.
- Keys: `profile`, `stats`, `heatmap`, `footprints`, `directions`.
- Restored automatically upon system boot.
- If NVS is empty, factory default values for `GuanMo` are loaded immediately.

### 6.4 Host Sync Agent

On macOS the host assistant runs as the per-user launchd agent `local.codex-passport-sync`. `projects/codex-passport/tools/passport-sync` installs and controls it. Raycast script commands in `projects/codex-passport/tools/raycast/` call the same CLI.
