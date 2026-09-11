#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Codex Passport: Start Sync
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 📡
# @raycast.packageName Codex Passport
# @raycast.description Start the Codex Passport BLE login agent

set -euo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/passport-sync" start
