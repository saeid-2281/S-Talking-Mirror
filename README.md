# S Talking v0.3

## New features
- Dashboard for files, characters, completed, failed, and estimated time
- Professional queue table with status colors, duration, retry count, and provider
- Row preview panel
- Save/open `.stproj` project files
- SQLite job history and resume at `data/s-talking.db`
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
