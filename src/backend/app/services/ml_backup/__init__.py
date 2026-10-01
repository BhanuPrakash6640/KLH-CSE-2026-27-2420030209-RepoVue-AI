"""RepoVue Silent ML Backup System.

Trained XGBoost models (Classifier + Regressor) providing offline fault tolerance
when cloud LLM API keys fail, expire, or hit rate limits.
"""
from app.services.ml_backup.features import CodeFeatureExtractor, extract_structural_features
from app.services.ml_backup.inference import SilentMLBackupEngine, get_backup_engine
from app.services.ml_backup.model import FallbackMLBundle

__all__ = [
    "CodeFeatureExtractor",
    "extract_structural_features",
    "FallbackMLBundle",
    "SilentMLBackupEngine",
    "get_backup_engine",
]
