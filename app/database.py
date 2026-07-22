from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from app.models import TTSJob

class JobDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_key TEXT NOT NULL,
          row_number INTEGER NOT NULL,
          filename TEXT NOT NULL,
          text TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          duration_seconds REAL,
          error TEXT,
          updated_at TEXT NOT NULL,
          UNIQUE(project_key,row_number,filename));
        CREATE INDEX IF NOT EXISTS idx_jobs_project_status ON jobs(project_key,status);
        ''')
        self.connection.commit()
    def _now(self): return datetime.now(timezone.utc).isoformat()
    def sync_jobs(self, key: str, jobs: list[TTSJob]) -> None:
        now=self._now()
        self.connection.executemany('''INSERT INTO jobs(project_key,row_number,filename,text,status,updated_at)
        VALUES(?,?,?,?,?,?) ON CONFLICT(project_key,row_number,filename)
        DO UPDATE SET text=excluded.text,updated_at=excluded.updated_at''',
        [(key,j.row_number,j.filename,j.text,'pending',now) for j in jobs])
        self.connection.commit()
    def status_for(self,key,job):
        row=self.connection.execute('SELECT status FROM jobs WHERE project_key=? AND row_number=? AND filename=?',(key,job.row_number,job.filename)).fetchone()
        return row['status'] if row else None
    def mark_running(self,key,job):
        self.connection.execute("UPDATE jobs SET status='running',attempts=attempts+1,error=NULL,updated_at=? WHERE project_key=? AND row_number=? AND filename=?",(self._now(),key,job.row_number,job.filename)); self.connection.commit()
    def mark_result(self,key,job,status,duration=0.0,error=None):
        self.connection.execute('UPDATE jobs SET status=?,duration_seconds=?,error=?,updated_at=? WHERE project_key=? AND row_number=? AND filename=?',(status,duration,error,self._now(),key,job.row_number,job.filename)); self.connection.commit()
    def reset_running(self,key):
        self.connection.execute("UPDATE jobs SET status='pending',updated_at=? WHERE project_key=? AND status='running'",(self._now(),key)); self.connection.commit()
    def close(self): self.connection.close()
