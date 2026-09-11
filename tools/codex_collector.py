#!/usr/bin/env python3
"""Codex / OpenCodex usage analytics collector and realtime state monitor.

Prefers ~/.opencodex/usage.jsonl when present (same ledger as the OpenCodex
dashboard). Falls back to ~/.codex/sessions token_usage_record lines.
Deduplicates by requestId / response_id. No cloud calls, no session bodies.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

DEFAULT_SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")
DEFAULT_ARCHIVED_DIR = os.path.expanduser("~/.codex/archived_sessions")
DEFAULT_CACHE_PATH = os.path.expanduser("~/.codex-passport/analytics_cache.json")
DEFAULT_OPENCODEX_USAGE = os.path.expanduser("~/.opencodex/usage.jsonl")
DEFAULT_OPENCODEX_QUOTA = os.path.expanduser("~/.opencodex/codex-quota-cache.json")

# State enum matching firmware
STATE_IDLE = 0
STATE_RUNNING = 1
STATE_WAITING_INPUT = 2
STATE_COMPLETED = 3
STATE_ERROR = 4

STATE_NAMES = {
    STATE_IDLE: "IDLE",
    STATE_RUNNING: "RUNNING",
    STATE_WAITING_INPUT: "WAITING_INPUT",
    STATE_COMPLETED: "COMPLETED",
    STATE_ERROR: "ERROR",
}


def classify_topic(project_name: str, cwd_path: str = "") -> str:
    """Deterministic, rule-based categorization without cloud models."""
    combined = f"{project_name} {cwd_path}".lower()

    if re.search(r"\b(esp32|bsp|hardware|iot|passport|sensor|ble|nimble|muyu|cards)\b", combined):
        return "IoT & Hardware"
    if re.search(r"\b(webui|frontend|react|vue|ui|tailwind|svelte|next|vite|css|html)\b", combined):
        return "Frontend & Web"
    if re.search(r"\b(agent|codex|llm|deepseek|omp|claude|chatcli|model|hermes|draft)\b", combined):
        return "AI Systems"
    if re.search(r"\b(server|service|api|backend|database|mysql|sqlite|redis|fastapi)\b", combined):
        return "Backend & Cloud"

    clean_name = project_name.replace("-", " ").replace("_", " ").title()
    return clean_name if clean_name else "General Dev"


def parse_timestamp_to_local_date(ts_str: Optional[str]) -> Optional[str]:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def parse_epoch_to_local_date(ts: Any) -> Optional[str]:
    """Convert OpenCodex epoch seconds or milliseconds to a local YYYY-MM-DD."""
    if ts is None:
        return None
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > 1e12:
        value /= 1000.0
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def provider_topic(provider: str) -> str:
    """Map OpenCodex provider ids onto compact footprint labels."""
    key = (provider or "").strip().lower()
    if key.startswith("openai"):
        return "OpenAI / Codex"
    if key.startswith("xai") or key.startswith("grok"):
        return "xAI Grok"
    if "google" in key or "gemini" in key or "antigravity" in key:
        return "Gemini"
    return (provider or "Other").strip()[:31] or "Other"


def opencodex_record_tokens(rec: Dict[str, Any]) -> int:
    """Prefer reported totalTokens; fall back to input+output."""
    usage = rec.get("usage") if isinstance(rec.get("usage"), dict) else {}
    for candidate in (rec.get("totalTokens"), usage.get("totalTokens")):
        try:
            tokens = int(candidate or 0)
        except (TypeError, ValueError):
            tokens = 0
        if tokens > 0:
            return tokens
    try:
        return int(usage.get("inputTokens") or 0) + int(usage.get("outputTokens") or 0)
    except (TypeError, ValueError):
        return 0


def _clamp_percent(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    if n < 0:
        return 0
    if n > 100:
        return 100
    return n


def _remaining_sec(reset_at: Any, now: float) -> int:
    try:
        ts = float(reset_at)
    except (TypeError, ValueError):
        return 0
    if ts > 1e12:
        ts /= 1000.0
    rem = int(ts - now)
    return rem if rem > 0 else 0


def load_opencodex_quota(
    path: Optional[str] = None,
    now: Optional[float] = None,
) -> Dict[str, int]:
    """Read 5-hour and weekly Codex quota percents from the OpenCodex cache."""
    empty = {
        "short_percent": 0,
        "weekly_percent": 0,
        "reset_credits": 0,
        "short_window_hours": 5,
        "short_remaining_sec": 0,
        "weekly_remaining_sec": 0,
    }
    quota_path = os.path.expanduser(path) if path else DEFAULT_OPENCODEX_QUOTA
    if not os.path.isfile(quota_path):
        return empty
    try:
        with open(quota_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return empty
    if not isinstance(data, dict):
        return empty

    block = None
    main = data.get("mainPolicyQuota")
    if isinstance(main, dict) and isinstance(main.get("quota"), dict):
        block = main["quota"]
    else:
        quotas = data.get("quotas")
        if isinstance(quotas, dict):
            candidate = quotas.get("__main__")
            if isinstance(candidate, dict):
                block = candidate
            else:
                for value in quotas.values():
                    if isinstance(value, dict):
                        block = value
                        break
    if not isinstance(block, dict):
        return empty

    clock = time.time() if now is None else now
    try:
        window = int(block.get("shortWindowSeconds") or 18000)
    except (TypeError, ValueError):
        window = 18000
    if window <= 0:
        window = 18000
    try:
        credits = int(block.get("resetCredits") or 0)
    except (TypeError, ValueError):
        credits = 0
    if credits < 0:
        credits = 0

    return {
        "short_percent": _clamp_percent(block.get("shortPercent")),
        "weekly_percent": _clamp_percent(block.get("weeklyPercent")),
        "reset_credits": credits,
        "short_window_hours": max(1, window // 3600),
        "short_remaining_sec": _remaining_sec(block.get("shortResetAt"), clock),
        "weekly_remaining_sec": _remaining_sec(block.get("weeklyResetAt"), clock),
    }


def _quota_account_name(acc: Dict[str, Any]) -> str:
    alias = str(acc.get("alias") or "").strip()
    if alias:
        return alias[:11]
    if acc.get("isMain"):
        return "MAIN"
    label = str(acc.get("logLabel") or "").strip()
    if label and label != "main":
        return label[:11]
    ident = str(acc.get("id") or "acct")
    return ident[-11:]


def _account_from_quota_block(name: str, block: Dict[str, Any], now: float) -> Dict[str, Any]:
    try:
        window = int(block.get("shortWindowSeconds") or 18000)
    except (TypeError, ValueError):
        window = 18000
    return {
        "name": name[:11],
        "short_percent": _clamp_percent(block.get("shortPercent", block.get("fiveHourPercent"))),
        "weekly_percent": _clamp_percent(block.get("weeklyPercent")),
        "short_window_hours": max(1, window // 3600) if window else 5,
        "short_remaining_sec": _remaining_sec(block.get("shortResetAt", block.get("fiveHourResetAt")), now),
        "weekly_remaining_sec": _remaining_sec(block.get("weeklyResetAt"), now),
    }


def _quota_fingerprint(block: Dict[str, Any]) -> tuple:
    return (
        _clamp_percent(block.get("shortPercent", block.get("fiveHourPercent"))),
        _clamp_percent(block.get("weeklyPercent")),
        block.get("shortResetAt", block.get("fiveHourResetAt")),
        block.get("weeklyResetAt"),
    )


def _is_main_account(acc: Dict[str, Any]) -> bool:
    return bool(acc.get("isMain") or acc.get("id") == "__main__")

def accounts_from_codex_auth(payload: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Normalize /api/codex-auth/accounts into three device quota rows."""
    clock = time.time() if now is None else now
    accounts = payload.get("accounts") if isinstance(payload, dict) else None
    if not isinstance(accounts, list):
        return []
    valid: List[Dict[str, Any]] = []
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        block = acc.get("quota")
        if not isinstance(block, dict):
            continue
        valid.append(acc)
    pool_emails = set()
    pool_fps = set()
    for acc in valid:
        if _is_main_account(acc):
            continue
        email = str(acc.get("email") or "").strip().lower()
        if email:
            pool_emails.add(email)
        pool_fps.add(_quota_fingerprint(acc["quota"]))
    rows: List[Dict[str, Any]] = []
    for acc in valid:
        block = acc["quota"]
        if _is_main_account(acc):
            email = str(acc.get("email") or "").strip().lower()
            if (email and email in pool_emails) or _quota_fingerprint(block) in pool_fps:
                continue
        rows.append(_account_from_quota_block(_quota_account_name(acc), block, clock))
        if len(rows) >= 3:
            break
    return rows


def accounts_from_quota_cache(data: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
    clock = time.time() if now is None else now
    quotas = data.get("quotas") if isinstance(data, dict) else None
    if not isinstance(quotas, dict):
        return []
    rows: List[Dict[str, Any]] = []
    order = []
    for key in quotas:
        if key not in order:
            order.append(key)
    pool_fps = set()
    for key, block in quotas.items():
        if key != "__main__" and isinstance(block, dict):
            pool_fps.add(_quota_fingerprint(block))
    for key in order:
        block = quotas.get(key)
        if not isinstance(block, dict):
            continue
        if key == "__main__" and _quota_fingerprint(block) in pool_fps:
            continue
        name = "MAIN" if key == "__main__" else key.replace("chatgpt-", "")[-11:]
        rows.append(_account_from_quota_block(name, block, clock))
        if len(rows) >= 3:
            break
    return rows


def _opencodex_port() -> int:
    for path in (
        os.path.expanduser("~/.opencodex/runtime-port.json"),
        os.path.expanduser("~/.opencodex/config.json"),
    ):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            port = int(data.get("port") or 0)
            if 1 <= port <= 65535:
                return port
        except Exception:
            continue
    return 10100


def _opencodex_admin_token() -> Optional[str]:
    path = os.path.expanduser("~/.opencodex/admin-api-token")
    try:
        token = open(path, "r", encoding="utf-8").read().strip()
    except OSError:
        return None
    return token or None


def load_codex_account_quotas(
    cache_path: Optional[str] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Three Codex login accounts: live local API, else quota cache."""
    empty = {"short_window_hours": 5, "accounts": []}
    clock = time.time() if now is None else now
    token = _opencodex_admin_token()
    if token:
        url = f"http://127.0.0.1:{_opencodex_port()}/api/codex-auth/accounts"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                payload = json.load(resp)
            rows = accounts_from_codex_auth(payload, clock)
            if rows:
                hours = int(rows[0].get("short_window_hours") or 5)
                return {"short_window_hours": hours, "accounts": rows}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
            pass

    path = os.path.expanduser(cache_path) if cache_path else DEFAULT_OPENCODEX_QUOTA
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows = accounts_from_quota_cache(data, clock)
            if rows:
                hours = int(rows[0].get("short_window_hours") or 5)
                return {"short_window_hours": hours, "accounts": rows}
        except Exception:
            pass
    return empty



class UsageCollector:
    """Scans session logs and aggregates token analytics."""

    def __init__(
        self,
        sessions_dir: str = DEFAULT_SESSIONS_DIR,
        archived_dir: str = DEFAULT_ARCHIVED_DIR,
        cache_path: Optional[str] = DEFAULT_CACHE_PATH,
        opencodex_usage_path: Optional[str] = None,
    ) -> None:
        self.sessions_dir = os.path.expanduser(sessions_dir)
        self.archived_dir = os.path.expanduser(archived_dir)
        self.cache_path = os.path.expanduser(cache_path) if cache_path else None
        self.opencodex_usage_path = (
            os.path.expanduser(opencodex_usage_path) if opencodex_usage_path else None
        )

        self.source = "codex-sessions"
        self.seen_response_ids: Set[str] = set()
        self.daily_tokens: Dict[str, int] = {}
        self.project_tokens_all: Dict[str, int] = Counter()
        self.project_tokens_30d: Dict[str, int] = Counter()
        self.project_daily: Dict[str, Dict[str, int]] = {}
        self.project_first_seen: Dict[str, str] = {}
        self.project_cwds: Dict[str, str] = {}
        self.total_tokens: int = 0
        self.processed_files: int = 0
        self.processed_records: int = 0

    def load_cache(self) -> bool:
        if not self.cache_path or not os.path.isfile(self.cache_path):
            return False
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            project_daily = data.get("project_daily")
            if not isinstance(project_daily, dict):
                return False
            self.seen_response_ids = set(data.get("seen_response_ids", []))
            self.daily_tokens = data.get("daily_tokens", {})
            self.project_tokens_all = Counter(data.get("project_tokens_all", {}))
            self.project_daily = {
                proj: {day: int(tok) for day, tok in days.items()}
                for proj, days in project_daily.items()
                if isinstance(days, dict)
            }
            self.project_first_seen = data.get("project_first_seen", {})
            self.project_cwds = data.get("project_cwds", {})
            self.total_tokens = int(data.get("total_tokens", 0))
            return True
        except Exception:
            return False

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            payload = {
                "seen_response_ids": list(self.seen_response_ids),
                "daily_tokens": self.daily_tokens,
                "project_tokens_all": dict(self.project_tokens_all),
                "project_daily": self.project_daily,
                "project_first_seen": self.project_first_seen,
                "project_cwds": self.project_cwds,
                "total_tokens": self.total_tokens,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def scan(self, use_cache: bool = True) -> Dict[str, Any]:
        """Full scan of OpenCodex usage or Codex session logs with deduplication."""
        ocx_path = self._resolved_opencodex_path()
        if ocx_path:
            self.source = "opencodex"
            self._scan_opencodex(ocx_path)
            return self.get_summary()

        self.source = "codex-sessions"
        if use_cache:
            self.load_cache()

        patterns = [
            os.path.join(self.sessions_dir, "**", "*.jsonl"),
            os.path.join(self.archived_dir, "**", "*.jsonl"),
        ]

        file_list: List[str] = []
        for pat in patterns:
            file_list.extend(glob.glob(pat, recursive=True))

        file_list = sorted(set(file_list))
        self.processed_files = len(file_list)

        for fpath in file_list:
            self._scan_single_file(fpath)

        if use_cache:
            self.save_cache()

        return self.get_summary()

    def _resolved_opencodex_path(self) -> Optional[str]:
        if self.opencodex_usage_path:
            return self.opencodex_usage_path if os.path.isfile(self.opencodex_usage_path) else None
        if os.path.abspath(self.sessions_dir) != os.path.abspath(DEFAULT_SESSIONS_DIR):
            return None
        if os.path.isfile(DEFAULT_OPENCODEX_USAGE):
            return DEFAULT_OPENCODEX_USAGE
        return None

    def _scan_opencodex(self, path: str) -> None:
        self.processed_files = 1
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    request_id = str(rec.get("requestId") or "").strip()
                    if not request_id:
                        continue
                    tokens = opencodex_record_tokens(rec)
                    if tokens <= 0:
                        continue
                    model = str(
                        rec.get("model")
                        or rec.get("resolvedModel")
                        or rec.get("requestedModel")
                        or "opencodex"
                    ).strip() or "opencodex"
                    provider = str(rec.get("provider") or "other").strip() or "other"
                    day_str = parse_epoch_to_local_date(rec.get("timestamp"))
                    self._ingest_tokens(request_id, tokens, day_str, model, provider)
        except OSError:
            pass

    def _ingest_tokens(
        self,
        response_id: str,
        tokens: int,
        day_str: Optional[str],
        project: str,
        cwd: str,
    ) -> None:
        if response_id in self.seen_response_ids:
            return
        self.seen_response_ids.add(response_id)
        self.processed_records += 1
        if tokens <= 0:
            return
        self.total_tokens += tokens
        if day_str:
            self.daily_tokens[day_str] = self.daily_tokens.get(day_str, 0) + tokens
            if project:
                if project not in self.project_first_seen or day_str < self.project_first_seen[project]:
                    self.project_first_seen[project] = day_str
                days = self.project_daily.setdefault(project, {})
                days[day_str] = days.get(day_str, 0) + tokens
        if project:
            self.project_tokens_all[project] += tokens
            if cwd:
                self.project_cwds[project] = cwd

    def _scan_single_file(self, fpath: str) -> None:
        current_cwd = ""
        current_project = ""

        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue

                    if "turn_context" in line:
                        try:
                            item = json.loads(line)
                            if item.get("type") == "turn_context":
                                cwd = item.get("payload", {}).get("cwd")
                                if cwd:
                                    current_cwd = cwd
                                    current_project = os.path.basename(cwd)
                                    self.project_cwds[current_project] = current_cwd
                        except Exception:
                            pass

                    if "token_usage_record" in line:
                        try:
                            item = json.loads(line)
                            if item.get("type") == "token_usage_record":
                                self._process_token_record(item, current_project, current_cwd)
                        except Exception:
                            pass
        except Exception:
            pass

    def _process_token_record(self, item: Dict[str, Any], project: str, cwd: str) -> None:
        payload = item.get("payload", {})
        response_id = payload.get("response_id")

        if not response_id:
            sid = payload.get("session_id", "")
            tid = payload.get("turn_id", "")
            ord_v = item.get("ordinal", 0)
            response_id = f"{sid}_{tid}_{ord_v}"

        usage = payload.get("usage", {})
        tokens = int(usage.get("total_tokens", 0))
        if tokens <= 0:
            tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))

        day_str = parse_timestamp_to_local_date(item.get("timestamp"))
        self._ingest_tokens(str(response_id), tokens, day_str, project, cwd)

    def get_summary(self) -> Dict[str, Any]:
        stats = self.calculate_stats()
        heatmap = self.calculate_heatmap_91d()
        footprints = self.calculate_footprints()
        directions = self.calculate_directions()

        return {
            "stats": stats,
            "heatmap": heatmap,
            "footprints": footprints,
            "directions": directions,
        }

    def calculate_stats(self) -> Dict[str, int]:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        today_tokens = self.daily_tokens.get(today_str, 0)

        # Rolling last 7 local days, matching OpenCodex /api/usage?range=7d
        start_of_week = (now - timedelta(days=6)).date()
        week_tokens = 0
        for day_str, count in self.daily_tokens.items():
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d").date()
                if d >= start_of_week:
                    week_tokens += count
            except Exception:
                pass

        # Streak calculation
        streak_days = 0
        cur_date = now.date()
        if self.daily_tokens.get(cur_date.strftime("%Y-%m-%d"), 0) > 0:
            streak_days += 1
            cur_date -= timedelta(days=1)
        else:
            yesterday = cur_date - timedelta(days=1)
            if self.daily_tokens.get(yesterday.strftime("%Y-%m-%d"), 0) > 0:
                streak_days += 1
                cur_date -= timedelta(days=2)
            else:
                cur_date = None

        while cur_date is not None:
            if self.daily_tokens.get(cur_date.strftime("%Y-%m-%d"), 0) > 0:
                streak_days += 1
                cur_date -= timedelta(days=1)
            else:
                break

        return {
            "total_tokens": self.total_tokens,
            "today_tokens": today_tokens,
            "week_tokens": week_tokens,
            "streak_days": streak_days,
        }

    def calculate_heatmap_91d(self, end_date: Optional[date] = None) -> Dict[str, Any]:
        """Calculates a 13-week (91-day) heatmap ending on current week's Sunday (or given end_date)."""
        if end_date is None:
            now = datetime.now()
            # Align end_date with Sunday of the current week (GitHub convention)
            days_to_sunday = 6 - now.weekday()
            end_date = (now + timedelta(days=days_to_sunday)).date()

        start_date = end_date - timedelta(days=90)  # Total 91 days inclusive

        levels: List[int] = []
        counts: List[int] = []
        active_days = 0
        max_tokens = 0

        for i in range(91):
            cur = start_date + timedelta(days=i)
            day_str = cur.strftime("%Y-%m-%d")
            tok = self.daily_tokens.get(day_str, 0)
            counts.append(tok)
            if tok > 0:
                active_days += 1
            if tok > max_tokens:
                max_tokens = tok

        # Map to 5 intensity levels (0..4). OpenCodex days are much larger than
        # Codex session increments, so scale against the window max.
        relative = self.source == "opencodex"
        for tok in counts:
            if tok == 0:
                levels.append(0)
            elif relative and max_tokens > 0:
                ratio = tok / max_tokens
                if ratio < 0.15:
                    levels.append(1)
                elif ratio < 0.40:
                    levels.append(2)
                elif ratio < 0.70:
                    levels.append(3)
                else:
                    levels.append(4)
            elif tok < 50_000:
                levels.append(1)
            elif tok < 300_000:
                levels.append(2)
            elif tok < 1_500_000:
                levels.append(3)
            else:
                levels.append(4)

        return {
            "levels": levels,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "active_days": active_days,
            "max_daily_tokens": max_tokens,
        }

    def calculate_footprints(self) -> List[Dict[str, Any]]:
        topic_totals: Dict[str, int] = Counter()
        topic_first_seen: Dict[str, str] = {}

        for proj, tokens in self.project_tokens_all.items():
            cwd = self.project_cwds.get(proj, "")
            if self.source == "opencodex":
                topic = provider_topic(cwd)
            else:
                topic = classify_topic(proj, cwd)
            topic_totals[topic] += tokens
            first_date = self.project_first_seen.get(proj, "")
            if first_date:
                if topic not in topic_first_seen or first_date < topic_first_seen[topic]:
                    topic_first_seen[topic] = first_date

        footprints: List[Dict[str, Any]] = []
        for topic, tok in topic_totals.most_common(6):
            footprints.append({
                "topic": topic,
                "first_date": topic_first_seen.get(topic, "2026-04-01"),
                "total_tokens": tok,
            })

        if not footprints:
            footprints = [
                {"topic": "IoT & Hardware", "first_date": "2026-04-20", "total_tokens": 12_400_000},
                {"topic": "Frontend & Web", "first_date": "2026-05-10", "total_tokens": 45_800_000},
                {"topic": "AI Systems", "first_date": "2026-06-01", "total_tokens": 89_200_000},
            ]

        return footprints

    def calculate_directions(self) -> List[Dict[str, Any]]:
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        self.project_tokens_30d = Counter()
        for proj, days in self.project_daily.items():
            for day, tok in days.items():
                if day >= cutoff:
                    self.project_tokens_30d[proj] += tok

        top = self.project_tokens_30d.most_common(5)
        total_30d = sum(self.project_tokens_30d.values())

        directions: List[Dict[str, Any]] = []
        for proj, tok in top:
            pct = round(tok / total_30d * 100) if total_30d > 0 else 0
            directions.append({
                "name": proj,
                "tokens": tok,
                "percent": pct,
            })

        if not directions:
            top_all = self.project_tokens_all.most_common(5)
            tot = sum(cnt for _, cnt in top_all)
            for proj, tok in top_all:
                pct = round(tok / tot * 100) if tot > 0 else 0
                directions.append({
                    "name": proj,
                    "tokens": tok,
                    "percent": pct,
                })

        return directions


class RealtimeWatcher:
    """Watches OpenCodex usage or Codex sessions with auto-idle timeout."""

    def __init__(
        self,
        sessions_dir: str = DEFAULT_SESSIONS_DIR,
        idle_timeout_sec: float = 90.0,
        opencodex_usage_path: Optional[str] = None,
    ) -> None:
        self.sessions_dir = os.path.expanduser(sessions_dir)
        self.idle_timeout_sec = idle_timeout_sec
        self.opencodex_usage_path = (
            os.path.expanduser(opencodex_usage_path) if opencodex_usage_path else None
        )

        self.current_file: Optional[str] = None
        self.file_pos: int = 0
        self.state: int = STATE_IDLE
        self.project_name: str = "codex-passport"
        self.turn_start_time: float = 0.0
        self.last_event_time: float = 0.0
        self.turn_tokens: int = 0
        self.today_tokens: int = 0
        self._opencodex_mode = False

    def _resolved_opencodex_path(self) -> Optional[str]:
        if self.opencodex_usage_path:
            return self.opencodex_usage_path if os.path.isfile(self.opencodex_usage_path) else None
        if os.path.abspath(self.sessions_dir) != os.path.abspath(DEFAULT_SESSIONS_DIR):
            return None
        if os.path.isfile(DEFAULT_OPENCODEX_USAGE):
            return DEFAULT_OPENCODEX_USAGE
        return None

    def find_latest_session_file(self) -> Optional[str]:
        files = glob.glob(os.path.join(self.sessions_dir, "**", "*.jsonl"), recursive=True)
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    def poll(self) -> Dict[str, Any]:
        now = time.time()
        ocx = self._resolved_opencodex_path()
        if ocx:
            self._opencodex_mode = True
            self._poll_opencodex(ocx, now)
        else:
            self._opencodex_mode = False
            self._poll_sessions(now)

        idle_states = (STATE_RUNNING, STATE_WAITING_INPUT)
        if self._opencodex_mode:
            idle_states = (STATE_RUNNING, STATE_WAITING_INPUT, STATE_COMPLETED, STATE_ERROR)
        if self.state in idle_states:
            if now - self.last_event_time > self.idle_timeout_sec:
                self.state = STATE_IDLE
                self.turn_start_time = 0.0

        duration_sec = 0
        if self.state == STATE_RUNNING and self.turn_start_time > 0:
            duration_sec = int(now - self.turn_start_time)

        return {
            "state": self.state,
            "state_name": STATE_NAMES.get(self.state, "IDLE"),
            "project": self.project_name,
            "duration_sec": duration_sec,
            "turn_tokens": self.turn_tokens,
            "today_tokens": self.today_tokens,
        }

    def _poll_sessions(self, now: float) -> None:
        latest = self.find_latest_session_file()

        if latest != self.current_file:
            self.current_file = latest
            if latest and os.path.isfile(latest):
                size = os.path.getsize(latest)
                self.file_pos = max(0, size - 8192)
            else:
                self.file_pos = 0

        if self.current_file and os.path.isfile(self.current_file):
            try:
                with open(self.current_file, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(self.file_pos)
                    lines = f.readlines()
                    self.file_pos = f.tell()

                for line in lines:
                    self._parse_live_line(line, now)
            except Exception:
                pass

    def _poll_opencodex(self, path: str, now: float) -> None:
        if path != self.current_file:
            self.current_file = path
            try:
                self.file_pos = os.path.getsize(path)
            except OSError:
                self.file_pos = 0

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(self.file_pos)
                lines = f.readlines()
                self.file_pos = f.tell()
        except OSError:
            return

        for line in lines:
            self._parse_opencodex_line(line, now)

    def _parse_opencodex_line(self, line: str, now: float) -> None:
        if not line.strip():
            return
        try:
            rec = json.loads(line)
        except Exception:
            return
        if not isinstance(rec, dict) or not rec.get("requestId"):
            return

        model = str(
            rec.get("model") or rec.get("resolvedModel") or rec.get("requestedModel") or "opencodex"
        ).strip() or "opencodex"
        self.project_name = model[:31]
        tokens = opencodex_record_tokens(rec)
        self.turn_tokens = tokens
        self.today_tokens += tokens
        status = rec.get("status", 200)
        try:
            status_i = int(status)
        except (TypeError, ValueError):
            status_i = 200
        self.state = STATE_ERROR if status_i >= 400 else STATE_COMPLETED

        rec_ts = rec.get("timestamp")
        event_time = now
        try:
            value = float(rec_ts)
            if value > 1e12:
                value /= 1000.0
            if value > 0:
                event_time = value
        except (TypeError, ValueError):
            pass
        self.last_event_time = event_time
        if self.turn_start_time == 0.0:
            self.turn_start_time = event_time

    def _parse_live_line(self, line: str, now: float) -> None:
        if not line.strip():
            return
        try:
            item = json.loads(line)
        except Exception:
            return

        ev_type = item.get("type")
        payload = item.get("payload", {})
        sub_type = payload.get("type") if isinstance(payload, dict) else ""

        if ev_type == "turn_context":
            cwd = payload.get("cwd", "")
            if cwd:
                self.project_name = os.path.basename(cwd)
            self.state = STATE_RUNNING
            self.last_event_time = now
            if self.turn_start_time == 0.0:
                self.turn_start_time = now

        elif ev_type == "event_msg":
            if sub_type in ("task_started", "user_message", "exec_command_start"):
                self.state = STATE_RUNNING
                self.last_event_time = now
                if self.turn_start_time == 0.0:
                    self.turn_start_time = now
            elif sub_type in ("task_complete", "item_completed"):
                self.state = STATE_COMPLETED
                self.last_event_time = now
            elif sub_type in ("error", "turn_aborted"):
                self.state = STATE_ERROR
                self.last_event_time = now

        elif ev_type == "token_usage_record":
            usage = payload.get("usage", {})
            tok = int(usage.get("total_tokens", 0))
            self.turn_tokens += tok
            self.today_tokens += tok
            self.last_event_time = now


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex Usage Analytics & Realtime Watcher")
    parser.add_argument("--scan", action="store_true", help="Perform full offline session scan and dump summary")
    parser.add_argument("--watch", action="store_true", help="Poll realtime status in console")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument("--export-json", help="Export summary analytics to JSON file")
    args = parser.parse_args()

    collector = UsageCollector()

    if args.scan or args.export_json:
        print("[*] Scanning Codex session logs...")
        summary = collector.scan(use_cache=False)
        print(f"[+] Processed {collector.processed_files} session files, {collector.processed_records} token records.")
        print(f"[+] Total Tokens: {summary['stats']['total_tokens']:,}")
        print(f"[+] Today: {summary['stats']['today_tokens']:,}, Week: {summary['stats']['week_tokens']:,}, Streak: {summary['stats']['streak_days']} days")
        print("\n[*] Footprint Topics:")
        for fp in summary["footprints"]:
            print(f"  - {fp['topic']} (Since {fp['first_date']}): {fp['total_tokens']:,} tokens")
        print("\n[*] Top Directions (30d):")
        for d in summary["directions"]:
            print(f"  - {d['name']}: {d['tokens']:,} tokens ({d['percent']}%)")

        if args.export_json:
            with open(args.export_json, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            print(f"[+] Exported summary to {args.export_json}")

    if args.watch:
        print("[*] Starting realtime Codex session monitor (Ctrl+C to stop)...")
        watcher = RealtimeWatcher()
        try:
            while True:
                status = watcher.poll()
                sys.stdout.write(
                    f"\r[{status['state_name']:<12}] Project: {status['project']:<16} "
                    f"Duration: {status['duration_sec']:<4}s Turn: {status['turn_tokens']:<8} "
                    f"Today: {status['today_tokens']:<10}"
                )
                sys.stdout.flush()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[*] Stopped.")

    if not args.scan and not args.watch and not args.export_json:
        parser.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
