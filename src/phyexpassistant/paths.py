from __future__ import annotations

from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def project_path(*parts: str | Path) -> Path:
    path = PROJECT_ROOT
    for part in parts:
        path = path / Path(part)
    return path


def app_home() -> Path:
    configured = os.environ.get("PHYEXPASSISTANT_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_path(".phyexpassistant")


def output_root() -> Path:
    configured = os.environ.get("PHYEXPASSISTANT_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_path("data", "outputs")


def resolve_input_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.exists():
        return path.resolve()

    if not path.is_absolute():
        project_candidate = project_path(path)
        if project_candidate.exists():
            return project_candidate.resolve()

        cwd_candidate = Path.cwd() / path
        if cwd_candidate.exists():
            return cwd_candidate.resolve()

        return cwd_candidate.resolve(strict=False)

    return path
