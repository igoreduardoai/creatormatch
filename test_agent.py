"""Offline tests on SYNTHETIC fixtures (run without QLOO_API_KEY)."""
import os
os.environ.pop("QLOO_API_KEY", None)
from agent import run
names = ["Show Alpha", "Show Bravo", "Show Charlie", "Show Delta", "Show Echo", "Show Foxtrot"]
r = run("Demo Brand", names)
T = {
 "ranks by Qloo affinity, not popularity": [c["name"] for c in r["qloo_shortlist"]] == ["Show Delta", "Show Echo", "Show Charlie"],
 "baseline is the popularity sort": [c["name"] for c in r["popularity_shortlist"]] == ["Show Alpha", "Show Bravo", "Show Charlie"],
 "ambiguous name is flagged, not scored": [c["query"] for c in r["flagged"]] == ["Show Foxtrot"],
 "non-obvious pick has shared-taste evidence": r["explain"]["pick"] == "Show Delta" and r["explain"]["shared_taste"][0]["name"] == "Film One",
 "discovery excludes the marketer's own list": [d["name"] for d in r["discovery"]] == ["Niche Show"],
 "brief is a draft needing human review": "Human review required" in r["brief"],
 "unknown brand ranks nothing": "error" in run("Unknown Brand", names),
}
for k, v in T.items(): print("PASS" if v else "FAIL", k)
print(f"{sum(T.values())}/{len(T)} passed")
raise SystemExit(0 if all(T.values()) else 1)
