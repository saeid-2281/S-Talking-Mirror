# Automated Project Workflow Specification

Status: Implemented
Branch: feature/automated-project-workflow
Target version: 0.4.x

## Summary

This workflow reduces routine project setup clicks while preserving project
files, repositories, providers, generation controls, and legacy compatibility.

## Behavior

- Save As suggests a Windows-safe `.stproj` filename from the project name while
  preserving allowed Unicode.
- CSV files selected during New Project, Open Project, or Browse CSV are loaded
  automatically.
- The CSV button is now Reload CSV for manual refreshes.
- Numeric controls use predictable steps, suffixes, tooltips, and focus-gated
  mouse wheel behavior.
- Generation completion uses a non-modal summary.
- Project files store project-specific provider settings but not API secrets.
- Global defaults are saved only through the explicit Save as global defaults
  action.
