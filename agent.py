"""CreatorMatch agent: brand brief -> Qloo taste graph -> creator shortlist ranked by audience
affinity to the brand, compared against the popularity sort a marketer would do by default.

Steps (each one is a Qloo tool call, logged in the trace):
 1. resolve_brand      /search urn:entity:brand, with a name check
 2. resolve_creators   /search urn:entity:podcast per creator; ambiguous matches are flagged, not scored
 3. score_pool         /v2/insights filter.type=podcast, signal=brand, filter.results.entities=pool
 4. baseline           same pool sorted by Qloo popularity (the "reach" sort)
 5. explain_pick       the Qloo pick with the biggest jump over the popularity sort: shared TV/music
                       between the brand's audience and that creator's audience (two Insights calls each)
 6. discover           /v2/insights podcasts for the brand with filter.popularity.max (outside the list)
 7. brief              DRAFT brief from the structured result; a human approves any outreach.
Ranking is deterministic: Qloo affinity only. Follower count/popularity is shown, never scored."""
import difflib, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import qloo

CREATOR = "urn:entity:podcast"
PROFILE_TYPES = ["urn:entity:movie", "urn:entity:tv_show", "urn:entity:artist", "urn:entity:brand"]


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower().replace("&", "and")).strip()


def resolve(name, etype):
    """Pick the Qloo entity for a typed name. Exact (normalized) match in the top 3 wins; a close
    spelling (ratio >= 0.85) is accepted; anything else is returned as needs_review."""
    cands = qloo.search(name, etype)
    if not cands:
        return {"query": name, "status": "not_found"}
    for c in cands:
        if _norm(c["name"]) == _norm(name):
            return {"query": name, "status": "resolved", **c}
    best = max(cands, key=lambda c: difflib.SequenceMatcher(None, _norm(c["name"]), _norm(name)).ratio())
    ratio = difflib.SequenceMatcher(None, _norm(best["name"]), _norm(name)).ratio()
    status = "resolved" if ratio >= 0.85 else "needs_review"
    return {"query": name, "status": status, "match_ratio": round(ratio, 2), **best}


POOL = ThreadPoolExecutor(8)


def taste(entity_id, take=50):
    out = {}
    for t, rows in zip(PROFILE_TYPES, POOL.map(lambda t: qloo.insights(t, [entity_id], take=take), PROFILE_TYPES)):
        for e in rows:
            out[e["name"]] = {"affinity": e["affinity"], "type": t.split(":")[-1]}
    return out


def shared_taste(brand_prof, creator_prof, k=6):
    both = [(n, brand_prof[n]["affinity"], creator_prof[n]["affinity"], brand_prof[n]["type"])
            for n in brand_prof if n in creator_prof]
    both.sort(key=lambda x: -(x[1] + x[2]))
    return [{"name": n, "type": t, "brand_audience_affinity": a, "creator_audience_affinity": b}
            for n, a, b, t in both[:k]]


def run(brand_name, creator_names, k=3, popularity_max=0.9, use_llm=False):
    t0, trace = time.time(), []
    qloo.LOG.clear()
    def step(name, detail):
        trace.append({"step": name, "detail": detail, "t_ms": round((time.time() - t0) * 1000)})

    brand = resolve(brand_name, "urn:entity:brand")
    step("resolve_brand", f"{brand_name} -> {brand.get('name')} ({brand['status']})")
    res = {"brand_query": brand_name, "brand": brand, "live_qloo": qloo.live(),
           "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if brand["status"] != "resolved":
        res.update(error="Brand not resolved in Qloo; nothing ranked (no guessing).", trace=trace)
        return res

    names = list(dict.fromkeys(x.strip() for x in creator_names if x.strip()))[:25]
    pool = list(POOL.map(lambda n: resolve(n, CREATOR), names))
    ok = [c for c in pool if c["status"] == "resolved"]
    flagged = [c for c in pool if c["status"] != "resolved"]
    step("resolve_creators", f"{len(ok)} resolved, {len(flagged)} flagged for review")
    if not ok:
        res.update(error="No creator resolved.", pool=pool, trace=trace)
        return res

    scored = {e["entity_id"]: e for e in qloo.insights(CREATOR, [brand["entity_id"]], take=len(ok),
                                                       results_ids=[c["entity_id"] for c in ok])}
    for c in ok:
        c["affinity"] = scored.get(c["entity_id"], {}).get("affinity")
        c["popularity"] = scored.get(c["entity_id"], {}).get("popularity", c.get("popularity", 0))
    rankable = [c for c in ok if c["affinity"] is not None]
    by_aff = sorted(rankable, key=lambda c: -c["affinity"])
    by_pop = sorted(rankable, key=lambda c: -c["popularity"])
    for i, c in enumerate(by_aff): c["affinity_rank"] = i + 1
    for i, c in enumerate(by_pop): c["popularity_rank"] = i + 1
    step("score_pool", f"Qloo affinity for {len(rankable)} creators against {brand['name']}")
    step("baseline", "same list sorted by Qloo popularity (reach proxy)")

    qloo_top, pop_top = by_aff[:k], by_pop[:k]
    pick = max(qloo_top, key=lambda c: c["popularity_rank"] - c["affinity_rank"])
    dropped = [c for c in pop_top if c not in qloo_top]
    dropped = dropped[:1]
    ids = [brand["entity_id"], pick["entity_id"]] + [d["entity_id"] for d in dropped]
    profs = list(map(lambda f: f.result(), [POOL.submit(taste, i) for i in ids]))
    brand_prof, pick_prof = profs[0], profs[1]
    explain = {"pick": pick["name"], "affinity": pick["affinity"], "affinity_rank": pick["affinity_rank"],
               "popularity": pick["popularity"], "popularity_rank": pick["popularity_rank"],
               "shared_taste": shared_taste(brand_prof, pick_prof),
               "shared_count": len(set(brand_prof) & set(pick_prof)), "profile_size": len(brand_prof)}
    if dropped:
        d = dropped[0]
        explain["dropped"] = {"name": d["name"], "affinity": d["affinity"], "affinity_rank": d["affinity_rank"],
                              "popularity_rank": d["popularity_rank"],
                              "shared_taste": shared_taste(brand_prof, profs[2]),
                              "shared_count": len(set(brand_prof) & set(profs[2]))}
    step("explain_pick", f"{pick['name']}: popularity rank {pick['popularity_rank']} -> affinity rank {pick['affinity_rank']}")

    known = {c["entity_id"] for c in ok}
    disc = [e for e in qloo.insights(CREATOR, [brand["entity_id"]], take=10, popularity_max=popularity_max)
            if e["entity_id"] not in known][:5]
    step("discover", f"{len(disc)} creators outside the list (popularity <= {popularity_max})")

    top_taste = sorted(brand_prof.items(), key=lambda x: -x[1]["affinity"])[:5]
    res.update(pool=pool, flagged=flagged, qloo_shortlist=qloo_top, popularity_shortlist=pop_top,
               overlap=len({c["entity_id"] for c in qloo_top} & {c["entity_id"] for c in pop_top}),
               explain=explain, discovery=disc,
               brand_taste_top=[{"name": n, **v} for n, v in top_taste])
    res["brief"] = (f"Campaign brief DRAFT for {brand['name']}. Lead with what this audience already loves: "
                    f"{', '.join(n for n, _ in top_taste[:3])}. Shortlist (Qloo affinity): "
                    f"{', '.join(c['name'] for c in qloo_top)}. Angle for {pick['name']}: shared love of "
                    f"{', '.join(s['name'] for s in explain['shared_taste'][:2]) or 'n/a'}. "
                    "Human review required before any outreach.")
    res["brief_backend"] = "template"
    if use_llm:
        from brief_llm import write
        res["brief"], res["brief_backend"] = write(res)
    step("brief", f"DRAFT ({res['brief_backend']}); nothing is sent")
    calls = [x for x in qloo.LOG if not x["cached"]]
    res["metrics"] = {"qloo_calls": len(qloo.LOG), "qloo_calls_uncached": len(calls),
                      "qloo_ms_total": sum(x["ms"] for x in calls), "wall_ms": round((time.time() - t0) * 1000)}
    res["trace"] = trace
    return res


if __name__ == "__main__":
    brand = sys.argv[1] if len(sys.argv) > 1 else "Liquid Death"
    names = sys.argv[2].split("|") if len(sys.argv) > 2 else json.load(open("creators.json"))["default_pool"]
    print(json.dumps(run(brand, names), indent=1))
