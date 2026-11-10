from flask import Flask, jsonify, request, render_template
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import core_scores as scores

app = Flask(__name__)

def local_today():
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/results")
def results():
    raw_date = request.args.get("date", local_today().isoformat())
    try:
        day = datetime.strptime(raw_date, "%Y-%m-%d").date()
        items, errors = scores.football_scores(day)
        return jsonify({"items": items, "errors": errors, "date": day.isoformat()})
    except Exception as exc:
        return jsonify({"items": [], "error": str(exc)}), 502

@app.get("/api/live")
def live():
    try:
        items, errors = scores.football_scores(local_today(), live_only=True)
        return jsonify({"items": items, "errors": errors})
    except Exception as exc:
        return jsonify({"items": [], "error": str(exc)}), 502

@app.get("/api/standings")
def standings():
    try:
        items, errors = scores.league_standings()
        leagues = {}
        for item in items:
            leagues.setdefault(item.get("display") or "Liga", []).append(item)
        # Una numeración continua y orden consistente por liga.
        for name, rows in leagues.items():
            rows.sort(key=lambda r: (int(r.get("position") or 9999), str(r.get("team") or "")))
            for pos, row in enumerate(rows, 1):
                row["position"] = pos
        return jsonify({"leagues": [{"name": n, "rows": r} for n, r in leagues.items()], "errors": errors})
    except Exception as exc:
        return jsonify({"leagues": [], "error": str(exc)}), 502

@app.get("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"items": [], "error": "Escribí al menos 2 caracteres."})
    try:
        items, errors = scores.search_365scores(q, local_today())
        return jsonify({"items": items[:100], "errors": errors})
    except Exception as exc:
        return jsonify({"items": [], "error": str(exc)}), 502

@app.get("/health")
def health():
    return jsonify({"ok": True, "app": "Futbol Champain Scores"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
