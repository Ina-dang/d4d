"""Module locations must not change prompt, font or workspace paths."""

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parent
PROMPTS = APP_ROOT / 'prompts'
STATIC = APP_ROOT / 'static'
