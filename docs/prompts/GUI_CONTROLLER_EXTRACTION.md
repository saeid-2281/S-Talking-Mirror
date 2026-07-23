Implement the approved specification:

docs/specifications/GUI_CONTROLLER_EXTRACTION.md

Rules:

1. Inspect the current Project Manager implementation before editing.
2. Preserve user-visible behavior exactly.
3. Refactor incrementally; do not rewrite the GUI.
4. Introduce application bootstrap and dependency injection.
5. Extract ProjectController, GenerationController, and SettingsController.
6. Add a notification abstraction around QMessageBox.
7. Ensure programmatic widget loading does not falsely mark projects dirty.
8. Keep QTimer in the Qt layer, but delegate autosave decisions.
9. Keep CLI behavior unchanged.
10. Add all tests required by the specification.
11. Update docs/ARCHITECTURE.md.
12. Do not change the database schema.
13. Do not implement unrelated product features.
14. Do not commit automatically.

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
