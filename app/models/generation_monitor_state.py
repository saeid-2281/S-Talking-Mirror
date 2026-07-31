from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationMonitorState:
    current_filename: str = "None"
    current_row_number: int | None = None
    current_provider: str = "Not selected"
    current_status: str = "Ready"
    current_attempt: int = 0
    current_job_elapsed_seconds: float = 0.0
    current_job_characters: int = 0
    next_filename: str = "None"
    processed: int = 0
    total: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    average_seconds_per_completed_job: float = 0.0
    files_per_minute: float = 0.0
    characters_per_minute: float = 0.0
    remaining_eta_seconds: float = 0.0
    generation_start_time: str = "Not started"
    total_elapsed_seconds: float = 0.0
    active_elapsed_seconds: float = 0.0
    paused_seconds: float = 0.0
    last_provider_error: str = ""
    current_output_path: str = ""
    provider_request_seconds: float = 0.0
    total_job_seconds: float = 0.0
    inter_file_delay_seconds: float = 0.0
    retry_countdown_seconds: float = 0.0
    stopped_by_user: bool = False
    peak_concurrent_jobs: int = 1
    resource_usage: str = "Not available"
    retries: int = 0
    jobs_per_minute: float = 0.0
    characters_per_second: float = 0.0
    processed_characters: int = 0
    total_characters: int = 0
    remaining_characters: int = 0
    progress_percent: float = 0.0
    last_progress_age_seconds: float = 0.0
    stalled: bool = False
    worker_state: str = "Idle"
