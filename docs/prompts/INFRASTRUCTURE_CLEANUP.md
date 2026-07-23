Implement the approved specification:

docs/specifications/INFRASTRUCTURE_CLEANUP.md

Rules:

1. Inspect the current GUI controller extraction implementation before editing.
2. Preserve user-visible behavior exactly.
3. Refactor incrementally; do not rewrite the GUI.
4. Introduce a ServiceContainer.
5. Centralize runtime configuration and application paths.
6. Remove hardcoded database and settings paths from controllers and MainWindow.
7. Move generation jobs and paused state out of MainWindow.
8. Move AppSettings composition out of MainWindow as far as practical.
9. Remove ProjectFile construction from MainWindow.
10. Keep QTimer in the Qt layer, but delegate autosave decisions.
11. Keep CLI behavior unchanged.
12. Add all tests required by the specification.
13. Update docs/ARCHITECTURE.md.
14. Do not change the database schema.
15. Do not implement unrelated product features.
16. Do not commit automatically.

Run:

.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests

Stop and report:

- architecture summary
- files created
- files modified
- test results
- lint results
- MainWindow responsibilities before and after
- compatibility notes
- unresolved risks
- manual test checklist
