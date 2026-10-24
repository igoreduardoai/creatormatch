"""Minimal Qloo client for the hackathon API (https://hackathon.api.qloo.com, X-Api-Key header).
Endpoints used: GET /search (entity resolution) and GET /v2/insights (affinity + popularity).
No key -> offline mode with SYNTHETIC fixtures (fixtures.json), used only by the tests.
Responses are cached privately in memory (Qloo allows private server-side caching; never commit
Qloo response data to a public repo)."""
import json, os, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

BASE = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com")
FIX = json.loads((Path(__file__).parent / "fixtures.json").read_text())
_CACHE, _LOCK = {}, threading.Lock()
_SEM = threading.Semaphore(int(os.getenv("QLOO_CONCURRENCY", "3")))  # stay under the rate limit
LOG = []  # per-process call log: path, ms, cached
DAILY_CAP = int(os.getenv("QLOO_DAILY_CAP", "1500"))  # hard cap on uncached Qloo calls per UTC day
STATS = {"day": "", "calls": 0}


class CapReached(RuntimeError):
    pass


def live():
    return bool(os.getenv("QLOO_API_KEY"))


def _get(path, params):
    key = os.getenv("QLOO_API_KEY")
    if not key:
        return None
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    with _LOCK:
        if url in _CACHE:
            LOG.append({"path": path, "ms": 0, "cached": True})
            return _CACHE[url]
    with _LOCK:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if STATS["day"] != day:
            STATS.update(day=day, calls=0)
        if STATS["calls"] >= DAILY_CAP:
            raise CapReached("Daily Qloo call cap reached for this demo; cached examples still work.")
        STATS["calls"] += 1
    t = time.time()
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "Accept": "application/json"})
    for attempt in range(5):
        try:
            with _SEM:
                data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:  # rate limited: back off and retry
                time.sleep(0.6 * 2 ** attempt)
                continue
            raise RuntimeError(f"Qloo {path} HTTP {e.code}") from None
    LOG.append({"path": path, "ms": round((time.time() - t) * 1000), "cached": False})
    with _LOCK:
        _CACHE[url] = data
    return data


def search(name, etype):
    """Return the top candidates for a name: [{entity_id, name, popularity}]."""
    r = _get("/search", {"query": name, "types": etype, "take": 3})
    if r is None:
        return FIX["search"].get(f"{etype}|{name}", [])
    return [{"entity_id": x.get("entity_id"), "name": x.get("name"), "popularity": x.get("popularity") or 0}
            for x in r.get("results", []) if x.get("entity_id")]


def insights(target_type, signal_ids, take=10, results_ids=None, popularity_max=None):
    """Entities of target_type that over-index for an audience that likes signal_ids."""
    p = {"filter.type": target_type, "signal.interests.entities": ",".join(signal_ids), "take": take}
    if results_ids:
        p["filter.results.entities"] = ",".join(results_ids)
    if popularity_max is not None:
        p["filter.popularity.max"] = popularity_max
    r = _get("/v2/insights", p)
    if r is None:
        key = f"{target_type}|{','.join(signal_ids)}"
        rows = FIX["insights"].get(key, [])
        if results_ids:
            rows = [x for x in rows if x["entity_id"] in results_ids]
        if popularity_max is not None:
            rows = [x for x in rows if x["popularity"] <= popularity_max]
        return rows[:take]
    return [{"entity_id": e.get("entity_id"), "name": e.get("name"),
             "affinity": round(e.get("query", {}).get("affinity") or 0, 4),
             "popularity": round(e.get("popularity") or 0, 4)}
            for e in r.get("results", {}).get("entities", [])]
