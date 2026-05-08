"""Shared pytest fixtures for update-helm-chart tests."""
import sys
from pathlib import Path

# Make the action directory importable so `import settings_sync` and
# `import update_helm_chart` resolve when running pytest from anywhere.
ACTION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACTION_DIR))
