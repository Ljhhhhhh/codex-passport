#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Codex Passport: Restart Sync
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 📡
# @raycast.packageName Codex Passport
# @raycast.description Restart the Codex Passport BLE login agent

set -euo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/passport-sync" restart
