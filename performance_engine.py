import threading
import time

from result_engine import calibration_key, market_family

_CACHE_TTL = 300
_cache_lock = threading.Lock()
_cache_at = 0.0
_cache = {"keys": {}, "families": {}}


def _clamp(v, lo=0.01, hi=0.99):
    return max(lo, min(hi, float(v)))


def _load_feedback():
    global _cache_at, _cache
    now = time.time()
    with _cache_lock:
        if now - _cache_at < _CACHE_TTL:
            return _cache
        try:
            from database import get_performance_calibration_map
            _cache = get_performance_calibration_map()
            _cache_at = now
        except Exception as error:
            print("⚠️ Performance feedback unavailable:", repr(error))
            _cache = {"keys": {}, "families": {}}
            _cache_at = now
        return _cache


def invalidate_feedback_cache():
    global _cache_at
    with _cache_lock:
        _cache_at = 0.0


def apply_performance_feedback(candidates):
    """Apply small, sample-gated calibration feedback from verified settled tips.

    This is deliberately bounded. It never turns historical hit rate into a
    guarantee and it does nothing until enough unique settled predictions exist.
    """
    feedback = _load_feedback()
    out = []
    for original in list(candidates or []):
        c = dict(original)
        key = calibration_key(c.get("market_name"), c.get("selection"))
        fam = market_family(c.get("market_name"))
        # Do not auto-calibrate exact-score longshots from small outcome samples.
        if fam == "correct_score":
            c["performance_adjustment"] = 0.0
            c["performance_sample"] = 0
            out.append(c)
            continue
        stat = feedback.get("keys", {}).get(key) or feedback.get("families", {}).get(fam)
        if not stat:
            c["performance_adjustment"] = 0.0
            c["performance_sample"] = 0
            out.append(c)
            continue

        adjustment = max(-0.04, min(0.04, float(stat.get("adjustment") or 0.0)))
        old_p = _clamp(c.get("model_probability") or 0.5)
        new_p = _clamp(old_p + adjustment)
        c["pre_feedback_probability"] = old_p
        c["model_probability"] = new_p
        c["performance_adjustment"] = adjustment
        c["performance_sample"] = int(stat.get("sample") or 0)

        market_p = c.get("market_probability")
        if market_p is not None:
            c["edge"] = new_p - float(market_p)
        if not c.get("odds_estimated") and c.get("odds"):
            c["expected_value"] = new_p * float(c["odds"]) - 1.0

        # The original ranking already includes probability. Apply only the
        # incremental calibration change so historical data cannot dominate.
        c["ranking_score"] = float(c.get("ranking_score") or 0.0) + (new_p - old_p) * 0.50
        out.append(c)

    return sorted(out, key=lambda x: float(x.get("ranking_score") or 0.0), reverse=True)
