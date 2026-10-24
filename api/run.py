"""Serverless JSON endpoint (Vercel Python runtime style; also wrapped for AWS Lambda below).
POST {"brand": "...", "creators": ["...", ...]} -> CreatorMatch result. QLOO_API_KEY is an env secret.
Caps: <= 25 creators per run, per-IP runs per 10 min, and qloo.DAILY_CAP uncached calls per day."""
import json, os, sys, time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent, qloo

ORIGIN = os.getenv("ALLOWED_ORIGIN", "https://igoreduardoai.github.io")
HITS, PER_IP, WINDOW = defaultdict(deque), int(os.getenv("RUNS_PER_IP", "8")), 600
KEEP = ("brand_query", "live_qloo", "run_at", "error", "overlap", "explain", "discovery", "brand_taste_top",
        "brief", "brief_backend", "metrics", "trace")


def slim(c):
    return {k: c.get(k) for k in ("query", "name", "status", "affinity", "popularity", "affinity_rank", "popularity_rank")}


def handle(body, ip):
    q = HITS[ip]
    while q and time.time() - q[0] > WINDOW:
        q.popleft()
    if len(q) >= PER_IP:
        return 429, {"error": "Rate limit for this demo: please wait a few minutes."}
    q.append(time.time())
    try:
        req = json.loads(body or "{}")
        brand = str(req.get("brand", ""))[:80]
        names = [str(x)[:80] for x in req.get("creators", [])][:25]
        r = agent.run(brand, names)
    except qloo.CapReached as e:
        return 429, {"error": str(e)}
    except Exception as e:
        return 502, {"error": f"Qloo request failed: {e}"}
    out = {k: r.get(k) for k in KEEP if k in r}
    out["brand"] = {"name": r.get("brand", {}).get("name"), "status": r.get("brand", {}).get("status")}
    for k in ("pool", "flagged", "qloo_shortlist", "popularity_shortlist"):
        out[k] = [slim(c) for c in r.get(k, [])]
    return 200, out


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_POST(self):
        n = min(int(self.headers.get("Content-Length", 0)), 8000)
        code, out = handle(self.rfile.read(n).decode(), self.headers.get("x-forwarded-for", self.client_address[0]).split(",")[0])
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(out).encode())


def lambda_handler(event, context):
    """AWS Lambda function-URL entry point (same logic)."""
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 204}
    ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "?")
    code, out = handle(event.get("body"), ip)
    return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(out)}
