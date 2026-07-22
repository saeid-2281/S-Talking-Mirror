from __future__ import annotations
import hashlib
from pathlib import Path
from pydantic import BaseModel, Field
from app.models import AppSettings

class ProjectFile(BaseModel):
    version: int = 1
    name: str = 'Untitled project'
    csv_path: str = ''
    output_path: str = ''
    settings: AppSettings = Field(default_factory=AppSettings)
    @property
    def project_key(self):
        payload=f'{Path(self.csv_path).resolve()}|{Path(self.output_path).resolve()}|{self.name}'
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

def save_project(project: ProjectFile,path: Path):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(project.model_dump_json(indent=2),encoding='utf-8')
def load_project(path: Path): return ProjectFile.model_validate_json(path.read_text(encoding='utf-8'))
