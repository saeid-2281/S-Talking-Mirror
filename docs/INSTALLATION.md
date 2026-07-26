# Installation

## Development Install

1. Install Python 3.11 or newer.
2. Create a virtual environment: `py -3.11 -m venv .venv`
3. Install dependencies: `.\.venv\Scripts\python.exe -m pip install -e .[dev]`
4. Launch: `.\.venv\Scripts\python.exe -m app.gui.main`

## Portable Release Candidate

Run `.\scripts\build.ps1` to create an unsigned portable ZIP under `artifacts/package/`.

The portable package excludes reports, output audio, caches, databases, logs, settings, tests, and virtual environments.

## Provider Setup

Mock works without extra setup. ElevenLabs requires an API key. Piper requires the Piper executable and a local `.onnx` model.
