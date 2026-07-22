from __future__ import annotations
import threading,time
from pathlib import Path
from PySide6.QtCore import QObject,Signal,Slot
from app.database import JobDatabase
from app.models import AppSettings,TTSJob
from app.provider_factory import create_provider

class GenerationWorker(QObject):
    progress=Signal(int,int,str,str,float,int,str); log=Signal(str); finished=Signal(dict); failed=Signal(str)
    def __init__(self,jobs:list[TTSJob],settings:AppSettings,output_dir:Path,database_path:Path,project_key:str):
        super().__init__(); self.jobs=jobs; self.settings=settings; self.output_dir=output_dir; self.database_path=database_path; self.project_key=project_key; self._paused=threading.Event(); self._paused.set(); self._stop=False
    def pause(self): self._paused.clear(); self.log.emit('Paused after current request.')
    def resume(self): self._paused.set(); self.log.emit('Resumed.')
    def stop(self): self._stop=True; self._paused.set(); self.log.emit('Stop requested.')
    @Slot()
    def run(self):
        summary={'total':len(self.jobs),'completed':0,'skipped':0,'failed':0,'stopped':False}; self.output_dir.mkdir(parents=True,exist_ok=True)
        db=JobDatabase(self.database_path); db.sync_jobs(self.project_key,self.jobs); db.reset_running(self.project_key); provider=None
        try:
            provider=create_provider(self.settings)
            for i,job in enumerate(self.jobs,1):
                self._paused.wait()
                if self._stop: summary['stopped']=True; break
                ext='.wav' if self.settings.provider in {'mock','piper'} else self.settings.file_extension
                path=job.output_path(self.output_dir,ext)
                if db.status_for(self.project_key,job)=='completed' and path.exists(): summary['skipped']+=1; self.progress.emit(i,len(self.jobs),path.name,'skipped',0,0,''); continue
                if path.exists() and self.settings.skip_existing: db.mark_result(self.project_key,job,'skipped'); summary['skipped']+=1; self.progress.emit(i,len(self.jobs),path.name,'skipped',0,0,''); continue
                started=time.perf_counter()
                try:
                    db.mark_running(self.project_key,job); self.progress.emit(i,len(self.jobs),job.filename,'running',0,1,'')
                    path.write_bytes(provider.synthesize(job.text,self.settings)); duration=time.perf_counter()-started
                    db.mark_result(self.project_key,job,'completed',duration); summary['completed']+=1; self.progress.emit(i,len(self.jobs),path.name,'completed',duration,1,'')
                except Exception as exc:
                    duration=time.perf_counter()-started; err=str(exc); db.mark_result(self.project_key,job,'failed',duration,err); summary['failed']+=1; self.progress.emit(i,len(self.jobs),job.filename,'failed',duration,1,err); self.log.emit(f'ERROR {job.filename}: {err}')
                if self.settings.delay_seconds and i<len(self.jobs): time.sleep(self.settings.delay_seconds)
            self.finished.emit(summary)
        except Exception as exc: self.failed.emit(str(exc))
        finally:
            close=getattr(provider,'close',None)
            if callable(close): close()
            db.close()
