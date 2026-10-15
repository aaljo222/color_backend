"""Durable, fail-closed generation budget for a single-volume Railway pilot."""
import json
from contextlib import contextmanager
import sqlite3
import time
from pathlib import Path
from uuid import uuid4


class ArtLimitError(Exception):
    pass


class ArtStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, image_key TEXT NOT NULL,
                    started REAL NOT NULL, active_until REAL NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS attempt_time ON attempts(started);
                CREATE TABLE IF NOT EXISTS images (
                    image_key TEXT PRIMARY KEY, expires REAL NOT NULL, payload TEXT NOT NULL
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('PRAGMA secure_delete=ON')
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, owner, image_key, daily_limit=20, total_limit=20):
        """Commit the charge BEFORE provider I/O; failures/timeouts still consume it."""
        now = time.time()
        day_start = int(now // 86400) * 86400  # Explicit UTC day.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM images WHERE expires <= ?', (now,))
            cached = db.execute('SELECT payload FROM images WHERE image_key=?', (image_key,)).fetchone()
            if cached:
                return None, {**json.loads(cached[0]), 'cached': True}
            if db.execute('SELECT 1 FROM attempts WHERE active_until>? LIMIT 1', (now,)).fetchone():
                raise ArtLimitError('다른 작품을 생성 중입니다. 잠시 후 다시 눌러 주세요.')
            total = db.execute('SELECT count(*) FROM attempts').fetchone()[0]
            today = db.execute('SELECT count(*) FROM attempts WHERE started>=?', (day_start,)).fetchone()[0]
            personal = db.execute('SELECT count(*) FROM attempts WHERE owner=? AND started>=?', (owner, day_start)).fetchone()[0]
            retries = db.execute('SELECT count(*) FROM attempts WHERE image_key=?', (image_key,)).fetchone()[0]
            if total >= total_limit or today >= daily_limit:
                raise ArtLimitError('서비스의 전통화 생성 한도에 도달했습니다. 운영자에게 문의해 주세요.')
            if personal >= 3 or retries >= 3:
                raise ArtLimitError('오늘 이용 가능한 전통화 생성 횟수에 도달했습니다.')
            reservation = uuid4().hex
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?)', (reservation, owner, image_key, now, now + 300))
            return reservation, None

    def cleanup(self):
        with self.connect() as db:
            db.execute('DELETE FROM images WHERE expires<=?', (time.time(),))

    def finish(self, reservation, image_key, payload=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if payload is not None:
                db.execute('DELETE FROM images WHERE expires<=?', (time.time(),))
                db.execute('INSERT OR REPLACE INTO images VALUES (?,?,?)',
                           (image_key, time.time()+3600, json.dumps(payload, ensure_ascii=False)))
                db.execute('''DELETE FROM images WHERE image_key NOT IN
                              (SELECT image_key FROM images ORDER BY expires DESC LIMIT 4)''')
            db.execute('UPDATE attempts SET active_until=0 WHERE id=?', (reservation,))
