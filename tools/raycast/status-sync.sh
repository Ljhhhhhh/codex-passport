#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Codex Passport: Sync Status
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 📡
# @raycast.packageName Codex Passport
# @raycast.description Show whether Codex Passport BLE sync is running

set -euo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/passport-sync" status
