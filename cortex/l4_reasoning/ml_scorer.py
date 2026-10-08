"""ml_scorer: calibrated probability of success for the probability_of_success factor (FR-03, I6).

* Training data = ``outcome`` rows only (``label_source='realised'`` is asserted row by row; the column's
  CHECK also enforces it). Won = 1, lost = 0; withdrawn is excluded. Predictions never become labels.
* Features = the opportunity's other factor values (with explicit missing indicators, so a gap is never
  imputed as a value), its capital class, completeness and log amount. probability_of_success itself is
  excluded (no leakage).
* Candidates (logistic regression, histogram gradient boosting) are Platt-calibrated and compared by
  cross-validated Brier score. The winner is shadow-evaluated on a temporal holdout (the newest 20 % of
  outcomes) against the active model (or, for the first model, the class-prior baseline) and promoted to
  ``active`` only if it is better on AUC or Brier; without enough holdout, cross-validation decides.
* Real and demo data never mix: a model trained on synthetic seed outcomes (``trained_on_demo``) is used
  only for demo opportunities.
Features are the factor values at decision time: the latest ``factor_history`` row before the outcome's
close date (D-071), falling back to today's values when no history exists (the share is reported).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import pickle
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_settings

CLASSES = [
    "venture_equity", "private_equity", "strategic_corporate", "grant", "government_program", "university_program",
    "foundation_esg", "debt_facility", "convertible", "equipment_finance", "revenue_based_financing",
]  # fmt: skip


@lru_cache
def ml_config() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "ml.yaml").read_text(encoding="utf-8")) or {}


class InsufficientOutcomes(Exception):
    permanent = True


def feature_names(cfg: dict[str, Any] | None = None) -> list[str]:
    cfg = cfg or ml_config()
    f = cfg["features"]
    names: list[str] = []
    for n in f["factors"]:
        names += [n, f"{n}__missing"]
    if f.get("include_class"):
        names += [f"class__{c}" for c in CLASSES]
    if f.get("include_completeness"):
        names.append("completeness")
    if f.get("include_amount"):
        names += ["log10_amount", "log10_amount__missing"]
    return names


def featurize(
    factor_values: dict[str, float | None],
    cls: str | None,
    completeness: float | None,
    amount: float | None,
    cfg: dict[str, Any] | None = None,
) -> list[float]:
    cfg = cfg or ml_config()
    f = cfg["features"]
    x: list[float] = []
    for n in f["factors"]:
        v = factor_values.get(n)
        x += [float(v), 0.0] if v is not None else [0.0, 1.0]
    if f.get("include_class"):
        x += [1.0 if cls == c else 0.0 for c in CLASSES]
    if f.get("include_completeness"):
        x.append(float(completeness or 0.0))
    if f.get("include_amount"):
        x += [math.log10(amount), 0.0] if amount and amount > 0 else [0.0, 1.0]
    return x


def _factor_values(factors_doc: dict[str, Any] | None) -> dict[str, float | None]:
    fs = (factors_doc or {}).get("factors") or {}
    return {k: (v.get("value") if v.get("available") else None) for k, v in fs.items()}


# ----------------------------------------------------------------------------- training data
async def training_rows(s: AsyncSession, demo: bool) -> list[dict[str, Any]]:
    cfg = ml_config()
    rows = (
        (
            await s.execute(
                text(
                    "SELECT DISTINCT ON (o.id) oc.id AS outcome_id, oc.result, oc.label_source, oc.closed_at, o.id AS opportunity_id, o.class::text AS class, "
                    "COALESCE(fh.factors, o.factors) AS factors, (fh.factors IS NOT NULL) AS decision_time, o.completeness, "
                    "COALESCE(o.amount_max, o.amount_min) AS amount FROM outcome oc JOIN opportunity o ON o.id = oc.opportunity_id "
                    "LEFT JOIN LATERAL (SELECT h.factors FROM factor_history h WHERE h.opportunity_id = o.id AND h.scored_at <= oc.closed_at "
                    "ORDER BY h.scored_at DESC LIMIT 1) fh ON true WHERE oc.org_id = :org AND oc.is_demo = :demo "
                    "AND oc.result = ANY(:res) AND o.factors IS NOT NULL ORDER BY o.id, oc.closed_at DESC"
                ),
                {
                    "org": get_settings().org_id,
                    "demo": demo,
                    "res": cfg["labels"]["positive"] + cfg["labels"]["negative"],
                },
            )
        )
        .mappings()
        .all()
    )
    for r in rows:  # I6: training uses realised outcomes only
        if r["label_source"] != "realised":
            raise AssertionError(f"outcome {r['outcome_id']} is not a realised label")
    # oldest first: the temporal holdout takes the newest outcomes (DISTINCT ON above orders by opportunity)
    return sorted((dict(r) for r in rows), key=lambda r: r["closed_at"])


def matrix(rows: list[dict[str, Any]]) -> tuple[list[list[float]], list[int]]:
    pos = set(ml_config()["labels"]["positive"])
    X = [
        featurize(
            _factor_values(r["factors"]),
            r["class"],
            float(r["completeness"] or 0),
            float(r["amount"]) if r["amount"] is not None else None,
        )
        for r in rows
    ]
    y = [1 if r["result"] in pos else 0 for r in rows]
    return X, y


# ----------------------------------------------------------------------------- metrics
def calibration_bins(y: list[int], p: list[float], n_bins: int) -> list[dict[str, Any]]:
    bins = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        idx = [k for k, v in enumerate(p) if (lo <= v < hi) or (i == n_bins - 1 and v == 1.0)]
        if idx:
            bins.append(
                {
                    "lo": lo,
                    "hi": hi,
                    "n": len(idx),
                    "mean_predicted": round(sum(p[k] for k in idx) / len(idx), 4),
                    "observed_rate": round(sum(y[k] for k in idx) / len(idx), 4),
                }
            )
    return bins


def _metrics(y: list[int], p: list[float]) -> dict[str, Any]:
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    return {
        "auc": round(float(roc_auc_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "log_loss": round(float(log_loss(y, [min(max(v, 1e-6), 1 - 1e-6) for v in p])), 4),
    }


def _baseline(rows: list[dict[str, Any]], y: list[int]) -> dict[str, Any]:
    """Class-prior baseline (the cold-start method) on the same outcomes."""
    from cortex.l4_reasoning.score_service import reference

    priors = reference()["class_priors"]
    p = [float(priors.get(r["class"] or "", 0.1)) for r in rows]
    return _metrics(y, p) if len(set(y)) > 1 else {"auc": 0.5, "brier": None, "log_loss": None}


def _candidates(name: str) -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if name == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            max_depth=3, max_iter=150, learning_rate=0.05, min_samples_leaf=8, random_state=7
        )
    raise ValueError(f"unknown algorithm {name}")


async def _holdout(s: AsyncSession, rows: list[dict[str, Any]], X: list[list[float]], y: list[int], algo: str,
                   cfg: dict[str, Any], demo: bool) -> dict[str, Any]:  # fmt: skip
    """Train on the older 80 %, evaluate candidate and reference on the newest 20 % (≥ 8, both classes present)."""
    from sklearn.calibration import CalibratedClassifierCV

    n = max(8, len(y) // 5)
    tr_y, ho_y = y[:-n], y[-n:]
    if len(y) - n < int(cfg["min_samples"]) // 2 or len(set(ho_y)) < 2 or min(sum(tr_y), len(tr_y) - sum(tr_y)) < 3:
        return {"n": n, "skipped": "not enough outcomes for a temporal holdout; cross-validation decides"}
    est = CalibratedClassifierCV(_candidates(algo), method=cfg.get("calibration", "sigmoid"), cv=3).fit(X[:-n], tr_y)
    cand = [float(v) for v in est.predict_proba(X[-n:])[:, 1]]
    models = await active_models(s)
    active = models.get(demo)
    if active is not None:
        ref_p = [float(v) for v in active.estimator.predict_proba(X[-n:])[:, 1]]
        label = f"active model v{active.version}"
    else:
        from cortex.l4_reasoning.score_service import reference

        priors = reference()["class_priors"]
        ref_p = [float(priors.get(r["class"] or "", 0.1)) for r in rows[-n:]]
        label = "the class-prior baseline"
    return {"n": n, "candidate": _metrics(ho_y, cand), "reference": _metrics(ho_y, ref_p), "reference_label": label}


@dataclass
class TrainResult:
    model_id: str
    version: int
    status: str
    algorithm: str
    metrics: dict[str, Any]
    reason: str


async def train(s: AsyncSession, trained_by: str, demo: bool) -> TrainResult:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    cfg = ml_config()
    rows = await training_rows(s, demo)
    X, y = matrix(rows)
    npos, nneg = sum(y), len(y) - sum(y)
    if len(y) < int(cfg["min_samples"]) or min(npos, nneg) < int(cfg["min_per_class"]):
        raise InsufficientOutcomes(
            f"{len(y)} realised won/lost outcomes ({npos} won, {nneg} lost); need ≥ {cfg['min_samples']} with "
            f"≥ {cfg['min_per_class']} of each"
        )
    folds = min(int(cfg["cv_folds"]), npos, nneg)
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=7)
    inner = max(2, min(3, folds))
    scored = []
    for algo in cfg["algorithms"]:
        est = CalibratedClassifierCV(_candidates(algo), method=cfg.get("calibration", "sigmoid"), cv=inner)
        p = [float(v) for v in cross_val_predict(est, X, y, cv=cv, method="predict_proba")[:, 1]]
        scored.append((algo, _metrics(y, p), p))
    if cfg.get("select_by", "brier") == "brier":
        algo, metrics, p = min(scored, key=lambda t: t[1]["brier"])
    else:
        algo, metrics, p = max(scored, key=lambda t: t[1]["auc"])
    final = CalibratedClassifierCV(_candidates(algo), method=cfg.get("calibration", "sigmoid"), cv=inner).fit(X, y)
    buf = io.BytesIO()
    pickle.dump(final, buf)
    blob = buf.getvalue()
    baseline = _baseline(rows, y)
    metrics = {
        **metrics,
        "n": len(y),
        "positives": npos,
        "cv_folds": folds,
        "calibration": calibration_bins(y, p, int(cfg.get("calibration_bins", 10))),
        "baseline_prior": baseline,
        "candidates": {a: m for a, m, _ in scored},
    }
    org = get_settings().org_id
    name = cfg["model_name"]
    active = (
        (
            await s.execute(
                text(
                    "SELECT id, version, metrics FROM ml_model WHERE org_id = :org AND name = :n AND trained_on_demo = :d "
                    "AND status = 'active' FOR UPDATE"
                ),
                {"org": org, "n": name, "d": demo},
            )
        )
        .mappings()
        .first()
    )
    holdout = await _holdout(s, rows, X, y, algo, cfg, demo)
    metrics["holdout"] = holdout
    metrics["decision_time_share"] = round(sum(1 for r in rows if r.get("decision_time")) / len(rows), 4)
    if holdout.get("candidate"):
        # shadow evaluation: both models predict outcomes the candidate never saw
        metrics_cmp, ref = holdout["candidate"], holdout["reference"]
        ref_label = f"{holdout['reference_label']} on the latest {holdout['n']} outcomes (holdout)"
    else:
        metrics_cmp = metrics
        ref = active["metrics"] if active else baseline
        ref_label = f"active model v{active['version']}" if active else "the class-prior baseline"
    margin = cfg.get("promotion") or {}
    better_auc = ref.get("auc") is None or metrics_cmp["auc"] > float(ref["auc"]) + float(margin.get("auc_margin", 0))
    better_brier = ref.get("brier") is None or metrics_cmp["brier"] < float(ref["brier"]) - float(
        margin.get("brier_margin", 0)
    )
    promote = better_auc or better_brier
    reason = (
        f"AUC {metrics_cmp['auc']} vs {ref.get('auc')}, Brier {metrics_cmp['brier']} vs {ref.get('brier')} ({ref_label}): "
        + ("promoted" if promote else "not better, kept as rejected")
    )
    version = int(
        (
            await s.execute(
                text("SELECT COALESCE(max(version), 0) + 1 FROM ml_model WHERE org_id = :org AND name = :n"),
                {"org": org, "n": name},
            )
        ).scalar_one()
    )
    if promote and active:
        await s.execute(text("UPDATE ml_model SET status = 'retired' WHERE id = :id"), {"id": active["id"]})
    mid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO ml_model (org_id, name, version, status, algorithm, features, metrics, trained_on_demo, n_samples, "
                    "training_refs, artifact, artifact_sha256, trained_by, promoted_at, decision_reason, is_demo, label_source) VALUES "
                    "(:org, :n, :v, :st, :algo, CAST(:f AS jsonb), CAST(:m AS jsonb), :d, :ns, CAST(:refs AS jsonb), :blob, :sha, "
                    ":by, CASE WHEN :st = 'active' THEN now() END, :why, :d, 'realised') RETURNING id"
                ),
                {
                    "org": org,
                    "n": name,
                    "v": version,
                    "st": "active" if promote else "rejected",
                    "algo": algo,
                    "f": json.dumps(feature_names(cfg)),
                    "m": json.dumps(metrics),
                    "d": demo,
                    "ns": len(y),
                    "refs": json.dumps([f"outcome:{r['outcome_id']}" for r in rows]),
                    "blob": blob,
                    "sha": hashlib.sha256(blob).hexdigest(),
                    "by": trained_by,
                    "why": reason,
                },
            )
        ).scalar_one()
    )
    _model_cache.clear()
    return TrainResult(mid, version, "active" if promote else "rejected", algo, metrics, reason)


# ----------------------------------------------------------------------------- inference
_model_cache: dict[str, Any] = {}


@dataclass
class ActiveModel:
    id: str
    version: int
    algorithm: str
    metrics: dict[str, Any]
    trained_on_demo: bool
    estimator: Any

    def predict(
        self, factor_values: dict[str, float | None], cls: str | None, completeness: float | None, amount: float | None
    ) -> float:
        x = featurize(factor_values, cls, completeness, amount)
        return float(self.estimator.predict_proba([x])[0][1])


async def active_models(s: AsyncSession) -> dict[bool, ActiveModel]:
    """Active models keyed by trained_on_demo. Artifacts are unpickled once per model id."""
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, version, algorithm, metrics, trained_on_demo, artifact_sha256 FROM ml_model "
                    "WHERE org_id = :org AND name = :n AND status = 'active'"
                ),
                {"org": get_settings().org_id, "n": ml_config()["model_name"]},
            )
        )
        .mappings()
        .all()
    )
    out: dict[bool, ActiveModel] = {}
    for r in rows:
        key = str(r["id"])
        if key not in _model_cache:
            blob = (await s.execute(text("SELECT artifact FROM ml_model WHERE id = :id"), {"id": r["id"]})).scalar_one()
            blob = bytes(blob)
            if hashlib.sha256(blob).hexdigest() != r["artifact_sha256"]:
                raise RuntimeError(f"ml_model {key} artifact checksum mismatch")
            _model_cache[key] = pickle.loads(blob)  # noqa: S301 - checksum-verified artifact written by train()
        out[bool(r["trained_on_demo"])] = ActiveModel(
            key, int(r["version"]), r["algorithm"], r["metrics"], bool(r["trained_on_demo"]), _model_cache[key]
        )
    return out
