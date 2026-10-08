# A daily limit per visitor: 5 analyses per IP address per day, resetting at midnight India time.
#
# Stored in a tiny SQLite table:  usage(ip, day, count)
# Each request adds 1 to today's count for that IP. Old days are simply ignored.

import sqlite3
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

INDIA_TIME = ZoneInfo("Asia/Kolkata")


class DailyQuota:
    # Opens (or creates) the quota database
    def __init__(self, database_path, daily_limit=5):
        self.daily_limit = daily_limit
        self.lock = threading.Lock()  # one update at a time
        self.connection = sqlite3.connect(database_path, check_same_thread=False, timeout=30)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS usage (ip TEXT, day TEXT, count INTEGER, PRIMARY KEY (ip, day))"
        )
        self.connection.commit()

    # Today's date in India, like "2026-10-08"
    def today(self):
        return datetime.now(INDIA_TIME).strftime("%Y-%m-%d")

    # Seconds until the limit resets (next midnight in India)
    def seconds_until_reset(self):
        now = datetime.now(INDIA_TIME)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int((tomorrow - now).total_seconds()) + 1

    # How many analyses this IP has used today
    def used_today(self, ip_address):
        row = self.connection.execute(
            "SELECT count FROM usage WHERE ip = ? AND day = ?", (ip_address, self.today())
        ).fetchone()
        if row is None:
            return 0
        return row[0]

    # Uses one analysis. Returns (allowed, remaining).
    def take_one(self, ip_address):
        with self.lock:
            used = self.used_today(ip_address)
            if used >= self.daily_limit:
                return False, 0
            self.connection.execute(
                """INSERT INTO usage (ip, day, count) VALUES (?, ?, 1)
                   ON CONFLICT (ip, day) DO UPDATE SET count = count + 1""",
                (ip_address, self.today()),
            )
            self.connection.commit()
            return True, self.daily_limit - used - 1

    # Gives one back (used when the analysis failed, so a broken file doesn't cost a turn)
    def give_back(self, ip_address):
        with self.lock:
            self.connection.execute(
                "UPDATE usage SET count = MAX(count - 1, 0) WHERE ip = ? AND day = ?",
                (ip_address, self.today()),
            )
            self.connection.commit()
