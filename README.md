# S Talking v0.3

## New features
- Dashboard for files, characters, completed, failed, and estimated time
- Professional queue table with status colors, duration, retry count, and provider
- Row preview panel
- Save/open `.stproj` project files
- Project menu with new/open/save/save-as/recent/close actions
- SQLite job history and resume at `data/s-talking.db`
- SQLite project metadata and recent-project tracking at `data/s_talking.db`
- Safer recovery after interrupted runs
- Improved dark user interface

## Install and run on Windows
```powershell
cd "D:\S Talking\S-Talking-v0.3"
py -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m app.gui.main
```

Test first with the `mock` provider.

## Project files
Existing `.stproj` files remain supported. See `docs/PROJECTS.md` for project
manager behavior and `docs/ARCHITECTURE.md` for module responsibilities.
