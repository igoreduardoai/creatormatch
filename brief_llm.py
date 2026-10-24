"""Optional LLM-written outreach brief (OpenRouter, ':free' models only). The LLM never ranks.
Guard: the text must end with the human-review line and must not name any creator from the
marketer's list that Qloo did not shortlist; otherwise the template brief is kept."""
import json, os, urllib.request
MODELS = os.getenv("OPENROUTER_MODELS", "nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-31b-it:free").split(",")


def write(result):
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return result["brief"], "template"
    short = [c["name"] for c in result["qloo_shortlist"]]
    banned = [c["name"] for c in result.get("pool", []) if c.get("name") and c["name"] not in short]
    facts = {"brand": result["brand"]["name"], "audience_top_tastes": result["brand_taste_top"],
             "shortlist": [{"name": c["name"], "qloo_affinity": c["affinity"]} for c in result["qloo_shortlist"]],
             "non_obvious_pick": {k: result["explain"][k] for k in ("pick", "shared_taste")}}
    prompt = ("Write a 90-word creator-campaign brief DRAFT using only these facts (Qloo taste data): "
              f"{json.dumps(facts)}. Mention only the shortlisted creators. Do not invent numbers. "
              "End with exactly: 'Human review required before any outreach.'")
    for m in MODELS:
        if not m.endswith(":free"):
            continue
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                json.dumps({"model": m, "temperature": 0.3, "messages": [{"role": "user", "content": prompt}]}).encode(),
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}), timeout=45).read())
            txt = (r["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            continue
        if txt and "Human review required" in txt and not any(b in txt for b in banned):
            return txt, f"openrouter:{m}"
    return result["brief"], "template"
