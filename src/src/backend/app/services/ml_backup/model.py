"""XGBoost models for defect classification, severity regression, and confidence estimation."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import joblib
import numpy as np
import xgboost as xgb

from app.logging_config import get_logger
from app.services.ml_backup.features import CodeFeatureExtractor

log = get_logger(__name__)

CATEGORY_MAP = {
    0: "clean",
    1: "security",
    2: "logical_bug",
    3: "performance",
    4: "architecture",
}
REV_CATEGORY_MAP = {v: k for k, v in CATEGORY_MAP.items()}

SEVERITY_LEVELS = ["info", "low", "medium", "high", "critical"]


def score_to_severity(score: float) -> str:
    if score >= 3.4:
        return "critical"
    if score >= 2.4:
        return "high"
    if score >= 1.4:
        return "medium"
    return "low"


class FallbackMLBundle:
    """Encapsulates the feature extractor, XGBoost Classifier, and XGBoost Regressors."""

    def __init__(
        self,
        extractor: CodeFeatureExtractor | None = None,
        classifier: xgb.XGBClassifier | None = None,
        severity_regressor: xgb.XGBRegressor | None = None,
        confidence_regressor: xgb.XGBRegressor | None = None,
    ) -> None:
        self.extractor = extractor or CodeFeatureExtractor()
        self.classifier = classifier or xgb.XGBClassifier(
            n_estimators=60,
            max_depth=5,
            learning_rate=0.1,
            objective="multi:softprob",
            num_class=5,
            eval_metric="mlogloss",
            random_state=42,
        )
        self.severity_regressor = severity_regressor or xgb.XGBRegressor(
            n_estimators=45,
            max_depth=4,
            learning_rate=0.1,
            objective="reg:squarederror",
            random_state=42,
        )
        self.confidence_regressor = confidence_regressor or xgb.XGBRegressor(
            n_estimators=45,
            max_depth=4,
            learning_rate=0.1,
            objective="reg:squarederror",
            random_state=42,
        )
        self.is_ready = False

    def fit(
        self,
        code_samples: list[str],
        categories: list[int],
        severities: list[float],
        confidences: list[float],
    ) -> FallbackMLBundle:
        X = self.extractor.fit_transform(code_samples)
        y_cat = np.array(categories, dtype=np.int32)
        y_sev = np.array(severities, dtype=np.float32)
        y_conf = np.array(confidences, dtype=np.float32)

        self.classifier.fit(X, y_cat)
        self.severity_regressor.fit(X, y_sev)
        self.confidence_regressor.fit(X, y_conf)
        self.is_ready = True
        return self

    def predict(self, code_samples: list[str]) -> list[dict[str, Any]]:
        if not self.is_ready:
            raise RuntimeError("FallbackMLBundle is not trained or loaded.")
        X = self.extractor.transform(code_samples)
        pred_classes = self.classifier.predict(X)
        pred_probs = self.classifier.predict_proba(X)
        pred_severities = self.severity_regressor.predict(X)
        pred_confidences = self.confidence_regressor.predict(X)

        results = []
        for i in range(len(code_samples)):
            cls_idx = int(pred_classes[i])
            category = CATEGORY_MAP.get(cls_idx, "clean")
            class_prob = float(pred_probs[i][cls_idx])
            sev_score = float(pred_severities[i])
            conf_score = float(np.clip(pred_confidences[i], 0.50, 0.98))

            results.append({
                "category": category,
                "category_id": cls_idx,
                "probability": class_prob,
                "severity_score": sev_score,
                "severity": score_to_severity(sev_score),
                "confidence": conf_score,
            })
        return results

    def save(self, filepath: str | Path) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "extractor": self.extractor,
                "classifier": self.classifier,
                "severity_regressor": self.severity_regressor,
                "confidence_regressor": self.confidence_regressor,
                "is_ready": self.is_ready,
            },
            path,
        )
        log.info("ml_bundle_saved", path=str(path))

    @classmethod
    def load(cls, filepath: str | Path) -> FallbackMLBundle:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found at {path}")
        data = joblib.load(path)
        bundle = cls(
            extractor=data["extractor"],
            classifier=data["classifier"],
            severity_regressor=data["severity_regressor"],
            confidence_regressor=data["confidence_regressor"],
        )
        bundle.is_ready = data.get("is_ready", True)
        log.info("ml_bundle_loaded", path=str(path))
        return bundle
