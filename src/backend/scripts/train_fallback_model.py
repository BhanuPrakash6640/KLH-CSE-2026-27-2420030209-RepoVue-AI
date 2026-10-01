#!/usr/bin/env python3
"""CLI utility to train and save the XGBoost Code Defect Backup Model for RepoVue."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.logging_config import configure_logging, get_logger
from app.services.ml_backup.trainer import train_and_save_model

log = get_logger(__name__)


def main() -> int:
    configure_logging()
    print("=" * 60)
    print(" RepoVue Silent ML Backup Model Training (XGBoost)")
    print("=" * 60)
    try:
        model_path = train_and_save_model()
        print(f"\n[SUCCESS] Model successfully trained and saved:")
        print(f" -> {model_path}")
        print("\nThe backend will automatically use this model if cloud API keys fail or expire.")
        return 0
    except Exception as exc:
        print(f"\n[ERROR] Model training failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
