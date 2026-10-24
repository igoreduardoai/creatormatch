---
title: CreatorMatch
emoji: 🎯
colorFrom: green
colorTo: purple
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
pinned: false
license: mit
short_description: Popularity isn't affinity with your brand (Qloo taste graph)
---

# CreatorMatch: popularity isn't affinity with your brand

**Live demo:** https://huggingface.co/spaces/igor-eduardo-research/creatormatch · Qloo Agentic Hackathon · MIT

Brand marketers shortlist creators by reach. CreatorMatch takes the creators you are already considering, asks the
**Qloo taste graph** how strongly each creator's audience over-indexes on your brand, and puts that next to the
popularity sort you would do by default. It then explains the least obvious pick with the tastes the two audiences share,
flags names it could not resolve instead of guessing, and drafts a brief that a human must approve.

## How the agent works (each step is a Qloo call, shown in the app's trace)
1. `resolve_brand`: `GET /search?types=urn:entity:brand`, with a name check.
2. `resolve_creators`: `GET /search?types=urn:entity:podcast` per name. If Qloo's top match is a different show
   (e.g. "Hot Ones" resolved to another podcast), it is flagged for review and **not scored**.
3. `score_pool`: `GET /v2/insights?filter.type=urn:entity:podcast&signal.interests.entities=<brand>&filter.results.entities=<your list>`
   returns each creator's **affinity** to the brand's audience, plus its popularity.
4. `baseline`: the same list sorted by Qloo popularity (a reach proxy; we have no follower counts).
5. `explain_pick`: for the Qloo pick that jumped furthest over the popularity sort, fetch the top movies, TV shows,
   artists and brands for the brand's audience and for the creator's audience (`/v2/insights`, 4 types each) and show the overlap.
6. `discover`: `/v2/insights` podcasts for the brand with `filter.popularity.max=0.9`, i.e. smaller creators outside your list.
7. `brief`: a DRAFT built only from those fields. Nothing is sent; a human approves outreach.

The ranking is deterministic: Qloo affinity only. Popularity is displayed, never scored. About 27 Qloo calls per run.

## Run it
```bash
pip install -r requirements.txt
export QLOO_API_KEY=...            # hackathon key; base URL https://hackathon.api.qloo.com
python app.py                      # web UI on :7860
python agent.py "Liquid Death"     # JSON result in the terminal
python test_agent.py               # 7 offline tests on synthetic fixtures (no key needed)
```
Optional: `OPENROUTER_API_KEY` lets a free LLM rewrite the brief (guarded: it can't add creators Qloo didn't shortlist).

## Notes
- The Qloo key is a server-side secret. The demo caps usage per visitor and per day and caches responses in memory only.
- No Qloo response data is stored in this repo. `fixtures.json` is synthetic (invented names and numbers) and only feeds the tests.
- Creator names are typed by the user. Creators are represented by their podcast entities in Qloo.
