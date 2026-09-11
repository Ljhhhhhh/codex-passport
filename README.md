<p align="right">
  <a href="README.zh_CN.md">简体中文</a> · <strong>English</strong>
</p>

# Codex Passport (`codex-passport`)

A smart ambient desktop AI companion hardware built for OpenAI Codex and OpenCodex users, running on the FoloToy AI Passport (ESP32-C3 wearable card with a 240 × 320 color LCD).

Codex Passport sits gracefully under your monitor as a dedicated status display or clips to your lanyard as a digital badge. Communicating over Bluetooth Low Energy (NimBLE) with your Mac, it ambiently mirrors your coding agents' activities, pending user prompts, task completions, and account quotas with soft, unobtrusive sound alerts.

---

## Key Features

- 📡 **Real-time Task Status & Messages**: Displays live Codex tasks at a glance, highlighting **waiting for user input**, **unread completed**, and **failed** tasks with verified task titles and project directory names.
- 🔔 **Intelligent Event-Driven Alerts**: Chimes softly (gentle C5/E5 double tone with a 15 ms fade-in and smooth release) only when a new actionable event arises; initial syncing of historical tasks, paging, polling, and reconnects remain completely silent.
- 💤 **Unread-Aware Backlight & Power Saving**: The display stays illuminated while there are actionable unread tasks across hosts and projects. Once all tasks are inspected in Codex, the backlight smoothly sleeps after 30 seconds of inactivity. Tap OK anytime to wake.
- 📊 **Account Quota & Token Meter**: Reads local OpenCodex and Codex ledgers to report 5-hour and weekly usage percentages across 3 accounts, today's token consumption, lifetime usage, and activity streaks.
- 📶 **Zero-Configuration Mac Sync**: Backed by a lightweight macOS login background service (LaunchAgent) that auto-discovers and connects over BLE. No Wi-Fi passwords or manual pairing codes required on the device.
- 🔤 **Complete High-Definition Chinese Typography**: Includes a pre-rendered 30,440-glyph bitmap font derived from Source Han Sans (SIL OFL 1.1 license), ensuring crisp Chinese text without missing character boxes or encoding corruption.

---

## 1-Minute Quick Start Guide

### What You Need

1. A **FoloToy AI Passport** device
2. A USB Type-C cable supporting **data transfer** (not power-only)
3. A Mac running macOS

---

### Step 1: Flash Firmware to Device

Choose either of the two installation paths:

#### Method A: Web Flasher (No Toolchain Required, Recommended)

1. Open Chrome or Edge and navigate to the [ESP Web Flasher](https://espressif.github.io/esptool-js/).
2. Connect the AI Passport to your Mac with your USB-C data cable.
3. Download the ready-to-flash merged binary: `codex-passport-full.bin` (from Releases or build artifacts).
4. Configure flashing options:
   - Baud rate: `460800`
   - Flash address: `0x0`
5. Click **Connect**, choose the USB serial port, and click **Program**. Once flashing completes, the device will reboot into the application.

#### Method B: Local Command Line Build (For Developers)

If you have **ESP-IDF 5.5.3** installed and active:

```bash
# Compile and flash to connected device, then launch the serial monitor
idf.py flash monitor
```

---

### Step 2: Install Mac Companion Sync Service

From the root of this repository on your Mac, run the one-command installer:

```bash
./tools/passport-sync install
```

- **Automated Setup**: Creates an isolated virtual environment, installs necessary dependencies (`bleak`), and registers a macOS LaunchAgent.
- **Background Daemon**: Starts syncing immediately, launches on user login, and automatically restarts on unexpected exits.
- **Helpful Commands**:
  ```bash
  ./tools/passport-sync status   # Show running status and PID
  ./tools/passport-sync logs     # Print recent sync logs
  ./tools/passport-sync restart  # Restart the service
  ./tools/passport-sync stop     # Temporarily stop the service
  ```
- **Raycast Integration**: In Raycast Settings → Extensions → Script Commands → Add Directories, select `tools/raycast` to control sync directly from Raycast.

---

### Step 3: Power On & Enjoy

1. Turn on the AI Passport power switch; the device boots directly into **MESSAGES**.
2. The Mac service will detect the advertising peripheral `Codex-Passport` and establish a BLE connection automatically.
3. As you code with Codex:
   - When an agent asks a question requiring your input, the screen wakes and a soft chime sounds.
   - When background tasks complete, cards populate the unread message queue.
   - Once reviewed in Codex, unread tasks clear and the device gently sleeps after 30 seconds idle.

---

## Screen Views & Button Controls

The front panel features three tactile buttons:

| Button | Messages View (MESSAGES) | Home / Quota Views | QR View | When Asleep |
| :--- | :--- | :--- | :--- | :--- |
| **UP** | Previous view | Previous view | - | Ignored (prevents accidental wake) |
| **DOWN** | Next view | Next view | - | Ignored (prevents accidental wake) |
| **OK** | **Next page of 3 messages** | **Open homepage QR** | **Close QR** | **Wake screen** (stays awake 30s) |

### Views Overview

- **Messages View (MESSAGES)**: Default home view displaying unread completed, waiting input, and failed tasks, 3 per page. Shows status badges (`WAIT` / `DONE` / `ERR`), real task titles, and project names.
- **Home View**: Your nickname, last sync timestamp, today's tokens, plus lifetime volume, 7-day usage, and consecutive active days.
- **Quota View**: Live visual progress bars and percentages for 5-hour and weekly limits across 3 Codex login accounts.
- **QR View**: Displays your personal GitHub or website QR code. Toggle with the OK key on other views.
- **Top Status Bar**: Live indicators for BLE connection, current Codex agent status (`IDLE` / `RUN` / `WAIT` / `DONE` / `ERR`), and battery fuel gauge percentage.

---

## Troubleshooting & FAQ

<details>
<summary><strong>Q: Why does the screen turn off automatically?</strong></summary>

This is an intentional power-saving feature. When all tasks in Codex are marked read and no questions are pending, the unread count drops to zero. After 30 seconds of inactivity, the backlight turns off. Pressing the OK button immediately wakes the screen for 30 seconds.
</details>

<details>
<summary><strong>Q: When will the audio chime sound? Will it interrupt my flow?</strong></summary>

The chime is **strictly event-driven**:
- Plays only when a **new user-input question**, a **new unread completed task**, or an **error** is detected.
- Startup historical task loading, page cycling, background polling, and BLE reconnects remain completely silent.
</details>

<details>
<summary><strong>Q: My computer cannot find the USB serial port?</strong></summary>

1. Verify your USB cable has **data transfer lines**; charge-only cables will not expose serial ports.
2. The ESP32-C3 uses native USB-Serial-JTAG, which requires no external drivers on macOS or modern Linux (devices appear as `/dev/cu.usbmodem*`).
</details>

<details>
<summary><strong>Q: BLE connection drops or fails to connect?</strong></summary>

1. Confirm the Mac background service is running via `./tools/passport-sync status`.
2. Inspect connection details with `./tools/passport-sync logs`. The device advertises as `Codex-Passport` and connects automatically without manual Bluetooth pairing.
</details>

---

## Development & Customization

### Building Firmware Locally

Make sure **ESP-IDF 5.5.3** is activated in your environment:

```bash
# Build firmware
idf.py build

# Flash and view logs
idf.py flash monitor

# Generate merged binary for web flashing
idf.py merge-bin -o build/codex-passport-full.bin
```

### Running Unit Tests

```bash
# Audio chime envelope validation
python3 tests/test_passport_audio.py

# 30,440-character font bitmap integrity test
python3 tests/test_passport_font.py

# Event-driven alert and task deduplication test
python3 tests/test_project_sync.py

# Usage analytics parsing and deduplication test
python3 tests/test_codex_analytics.py
```

### Customizing Your Profile

Copy the template:

```bash
cp config.example.json profile.json
```

Edit `profile.json` with your name, interests, signature, and homepage URL. Upon sync, your AI Passport will reflect your personal digital profile and QR code.

---

## License & Acknowledgements

- Source code is released under the same license terms as the upstream project.
- Bundled Chinese font is based on Source Han Sans SC, licensed under the [SIL Open Font License 1.1](assets/fonts/OFL.txt).
- Hardware architecture powered by FoloToy AI Passport.
