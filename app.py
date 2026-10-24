"""CreatorMatch web demo (Gradio). The Qloo key lives only in the server environment (HF Space
secret QLOO_API_KEY); the browser never sees it. Usage is capped per visitor and per day."""
import html, json, os, time
from collections import defaultdict, deque
import gradio as gr
import agent, qloo

POOL = json.load(open(os.path.join(os.path.dirname(__file__), "creators.json")))["default_pool"]
HITS = defaultdict(deque)  # ip -> timestamps
PER_IP, WINDOW = int(os.getenv("RUNS_PER_IP", "8")), 600
USE_LLM = bool(os.getenv("OPENROUTER_API_KEY"))
e = html.escape


def bar(v, color):
    w = max(0, min(100, round(v * 100)))
    return f'<div class="bar"><span style="width:{w}%;background:{color}"></span></div>'


def table(rows, title, key, color, note):
    tr = "".join(
        f"<tr><td>{i+1}. {e(c['name'])}</td><td>{c['popularity']:.3f}<small> #{c['popularity_rank']}</small></td>"
        f"<td>{bar(c['affinity'], color)}{c['affinity']:.3f}<small> #{c['affinity_rank']}</small></td></tr>"
        for i, c in enumerate(rows))
    return (f'<div class="card"><h3>{title}</h3><p class="note">{note}</p><table><tr><th>Creator</th>'
            f'<th>Qloo popularity</th><th>Qloo affinity to brand</th></tr>{tr}</table></div>')


def render(r):
    if r.get("error"):
        return f'<div class="card warn"><b>{e(r["error"])}</b><br>{e(str(r.get("brand", {}).get("name") or ""))}</div>'
    x, b = r["explain"], r["brand"]["name"]
    n = len([c for c in r["pool"] if c.get("affinity") is not None])
    head = (f'<div class="hero"><div class="big">{r["overlap"]} of {len(r["qloo_shortlist"])}</div>'
            f'<div>creators are the same when you sort <b>{e(b)}</b>\'s list by popularity vs. by what its audience loves (Qloo).'
            f'<br><b>{e(x["pick"])}</b> is #{x["popularity_rank"]} of {n} by popularity and #{x["affinity_rank"]} by audience affinity.</div></div>')
    shared = "".join(f'<li><b>{e(s["name"])}</b> <small>({s["type"]})</small> · {e(b)} audience {s["brand_audience_affinity"]:.3f}'
                     f' · {e(x["pick"])} audience {s["creator_audience_affinity"]:.3f}</li>' for s in x["shared_taste"])
    why = (f'<div class="card pick"><h3>Why {e(x["pick"])}? (the non-obvious pick)</h3>'
           f'<p>Of the top {x["profile_size"]} movies, TV shows, artists and brands that {e(b)}\'s audience over-indexes on, '
           f'<b>{x["shared_count"]}</b> also show up for {e(x["pick"])}\'s audience. The strongest shared tastes:</p><ul>{shared or "<li>none</li>"}</ul>')
    if x.get("dropped"):
        d = x["dropped"]
        why += (f'<p class="note">For contrast, <b>{e(d["name"])}</b> is #{d["popularity_rank"]} by popularity but #{d["affinity_rank"]} by affinity '
                f'(affinity {d["affinity"]:.3f}); its audience shares <b>{d["shared_count"]}</b> of those tastes.</p>')
    why += "</div>"
    flag = "".join(f'<li>“{e(c["query"])}” → Qloo matched <b>{e(c.get("name") or "nothing")}</b> ({c["status"]}). Not scored; fix the name and rerun.</li>' for c in r["flagged"])
    flag = f'<div class="card warn"><h3>Needs your review</h3><ul>{flag}</ul></div>' if flag else ""
    disc = "".join(f'<li>{e(d["name"])} · affinity {d["affinity"]:.3f} · popularity {d["popularity"]:.3f}</li>' for d in r["discovery"])
    disc = f'<div class="card"><h3>Smaller creators outside your list (Qloo discovery)</h3><ul>{disc}</ul></div>'
    taste = "".join(f'<li>{e(t["name"])} <small>({t["type"]})</small> {bar(t["affinity"], "#7c3aed")}</li>' for t in r["brand_taste_top"])
    taste = f'<div class="card"><h3>{e(b)} audience: top tastes (Qloo)</h3><ul class="t">{taste}</ul></div>'
    brief = (f'<div class="card"><h3>Brief DRAFT <small>({e(r["brief_backend"])})</small></h3><p>{e(r["brief"])}</p>'
             '<p class="note">Nothing is sent. A human approves any outreach.</p></div>')
    m = r["metrics"]
    trace = "".join(f'<li><code>{t["step"]}</code> {e(t["detail"])} <small>{t["t_ms"]} ms</small></li>' for t in r["trace"])
    trace = (f'<details class="card"><summary>Agent trace · {m["qloo_calls"]} Qloo calls ({m["qloo_calls_uncached"]} live) · '
             f'{m["wall_ms"]} ms · run {e(r["run_at"])} UTC</summary><ol>{trace}</ol>'
             '<p class="note">Score = Qloo affinity of the creator to the brand (/v2/insights, filter.type=urn:entity:podcast, '
             'signal.interests.entities=brand, filter.results.entities=your list). Popularity is shown, never scored.</p></details>')
    cols = (f'<div class="cols">{table(r["popularity_shortlist"], "Generic pick: sort by popularity", "popularity", "#94a3b8", "What a reach-first shortlist looks like.")}'
            f'{table(r["qloo_shortlist"], "CreatorMatch: sort by audience affinity", "affinity", "#16a34a", "Qloo: how much this creator\'s audience over-indexes on the brand.")}</div>')
    return head + cols + why + flag + taste + disc + brief + trace


def go(brand, creators, request: gr.Request):
    ip = (request.client.host if request and request.client else "?")
    q = HITS[ip]
    while q and time.time() - q[0] > WINDOW: q.popleft()
    if len(q) >= PER_IP:
        return '<div class="card warn">Rate limit for this demo: please wait a few minutes.</div>'
    q.append(time.time())
    if not qloo.live():
        return '<div class="card warn">Server has no Qloo key configured.</div>'
    try:
        return render(agent.run(brand.strip()[:80], creators.splitlines()[:25], use_llm=USE_LLM))
    except qloo.CapReached as ex:
        return f'<div class="card warn">{e(str(ex))}</div>'
    except Exception as ex:
        return f'<div class="card warn">Qloo request failed: {e(str(ex))}. Try again in a minute.</div>'


CSS = """.hero{display:flex;gap:18px;align-items:center;background:#0f172a;color:#fff;padding:18px;border-radius:14px;margin-bottom:12px}
.hero .big{font-size:44px;font-weight:800;color:#4ade80;white-space:nowrap}.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:800px){.cols{grid-template-columns:1fr}}.card{border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin:10px 0}
.card table{width:100%;border-collapse:collapse}.card td,.card th{padding:5px;border-bottom:1px solid #f1f5f9;text-align:left;font-size:14px}
.bar{height:7px;background:#f1f5f9;border-radius:4px;width:100%;margin:2px 0}.bar span{display:block;height:7px;border-radius:4px}
.note{color:#64748b;font-size:13px}.pick{border-color:#16a34a;background:#f0fdf4}.warn{border-color:#f59e0b;background:#fffbeb}"""

with gr.Blocks(title="CreatorMatch · Popularity isn't affinity") as demo:
    gr.Markdown("# CreatorMatch\n**Popularity isn't affinity with your brand.** Paste the creators you are considering "
                "(podcast names), name the brand, and compare a popularity sort with a sort by what the brand's audience "
                "actually loves, from the live Qloo taste graph. Every pick comes with its evidence.")
    with gr.Row():
        brand = gr.Textbox(label="Brand", value="Liquid Death", scale=1)
        creators = gr.Textbox(label="Creators you are considering (one per line)", value="\n".join(POOL), lines=6, scale=2)
    btn = gr.Button("Compare", variant="primary")
    gr.Examples([["Liquid Death", "\n".join(POOL)], ["Patagonia", "\n".join(POOL)]], [brand, creators])
    out = gr.HTML()
    btn.click(go, [brand, creators], out, concurrency_limit=1)
    gr.Markdown("<small>Live Qloo Insights API (hackathon environment). Show names are typed by the user; nothing is stored. "
                "Open source (MIT): github.com/igoreduardoai/creatormatch</small>")

if __name__ == "__main__":
    demo.queue(max_size=20).launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), css=CSS)
