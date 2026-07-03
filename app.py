"""
app.py — AnimoHub Proxy API (Flask)

WHY A PROXY, NOT A SCRAPER:
The 7 HTML pages you originally gave me have no anime-card data in their raw
markup (no /anime/... links anywhere in the static HTML) — animohubpro.com
renders its cards client-side with JavaScript after the page loads. So
scraping the raw HTML (with BeautifulSoup or anything else) returns nothing
useful for listings.

What DOES work: the site's WordPress REST API is public
(wp-json/wp/v2/anime, /genre, /anime_type) and returns real data — this was
confirmed live from an Android build (real titles like "Blue Box", "David",
"Oshi No Ko" came back). So this Flask app is a server-side proxy +
normalizer around that REST API: it resolves featured images (_embed),
strips WordPress noise/HTML tags (via BeautifulSoup), and returns a clean,
stable JSON shape.

STILL UNKNOWN / NEEDS YOUR INPUT:
- The real "airing status" field (Ongoing/Completed). WordPress's own
  "status" field is just publish/draft, not that.
- The episode list + direct stream URL shape. None of the uploaded HTML
  pages were a watch/episode page, so there's nothing to reverse engineer
  from yet. Once you send a sample episode API response (Chrome DevTools ->
  Network -> XHR, opened on the actual watch page) I'll wire real episodes
  into /detail.

RUN LOCALLY:
    pip install -r requirements.txt
    python app.py
    curl "http://localhost:5000/list?type=latest"

DEPLOY:
Works on any host that runs a WSGI Flask app (Render, Railway, PythonAnywhere,
a VPS with gunicorn, etc). For Vercel specifically, Vercel's Python runtime
expects the WSGI app object to be importable — this file exposes `app` at
module level, which is exactly what's needed; just point Vercel's Python
builder at app.py.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests

app = Flask(__name__)
CORS(app)

WP_BASE = "https://animohubpro.com/wp-json/wp/v2/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wp_get(path, params=None):
    """GET a WordPress REST endpoint. Returns (data, status_code, error)."""
    params = dict(params or {})
    params["_embed"] = "true"
    url = WP_BASE + path.lstrip("/")

    try:
        resp = requests.get(
            url,
            params=params,
            timeout=15,
            headers={
                "Accept": "application/json",
                "User-Agent": "AnimoHubProxy/1.0 (+python-flask)",
            },
        )
    except requests.RequestException as e:
        return None, 502, str(e)

    try:
        data = resp.json()
    except ValueError:
        return None, resp.status_code, "Non-JSON response from upstream"

    return data, resp.status_code, None


def clean_html(raw_html):
    """Strip HTML tags + decode entities using BeautifulSoup."""
    if not raw_html:
        return ""
    return BeautifulSoup(raw_html, "html.parser").get_text().strip()


def extract_poster(post):
    """Pull the resolved poster URL out of a WP _embedded block."""
    embedded = post.get("_embedded", {})
    media_list = embedded.get("wp:featuredmedia") or []
    if media_list:
        media = media_list[0]
        source_url = media.get("source_url")
        if source_url:
            return source_url
        sizes = media.get("media_details", {}).get("sizes", {})
        for key in ("full", "large", "medium_large", "medium"):
            if key in sizes and sizes[key].get("source_url"):
                return sizes[key]["source_url"]
    return None


def normalize_anime(post):
    """Normalize one raw WP 'anime' post into a clean, stable shape."""
    return {
        "id": post.get("id"),
        "slug": post.get("slug"),
        "title": clean_html(post.get("title", {}).get("rendered", "")),
        "excerpt": clean_html(post.get("excerpt", {}).get("rendered", "")),
        "poster": extract_poster(post),
        "link": post.get("link"),
        "genre_ids": post.get("genre", []),
        "type_ids": post.get("anime_type", []),
        # NOTE: this is WordPress's post_status (publish/draft), not the
        # anime's airing status. Kept for completeness, not for display.
        "post_status": post.get("status"),
    }


def normalize_taxonomy(term):
    """Normalize one raw WP taxonomy term (genre / anime_type)."""
    return {
        "id": term.get("id"),
        "name": clean_html(term.get("name", "")),
        "slug": term.get("slug"),
        "count": term.get("count", 0),
    }


def api_error(message, code=500, detail=None):
    return jsonify({"success": False, "error": message, "detail": detail}), code


def api_success(data, **extra):
    payload = {"success": True, "data": data}
    payload.update(extra)
    return jsonify(payload)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return api_success(
        {
            "name": "AnimoHub Proxy API",
            "endpoints": [
                "GET /list?type=latest|movie|series&page=1&per_page=20",
                "GET /genres",
                "GET /genre?id=17&page=1&per_page=20",
                "GET /types",
                "GET /detail?id=123",
                "GET /search?q=naruto&per_page=20",
            ],
            "note": (
                "Proxies + normalizes animohubpro.com wp-json REST API. "
                "Episode/stream endpoints not yet available — see app.py "
                "header comment."
            ),
        }
    )


@app.route("/list")
def list_anime():
    # type: latest (home) | movie | series
    # movie -> anime_type=27, series -> anime_type=26 (from movie.html / series.html)
    anime_type = request.args.get("type", "latest")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))

    params = {"page": page, "per_page": per_page, "orderby": "date"}
    if anime_type == "movie":
        params["anime_type"] = 27
    elif anime_type == "series":
        params["anime_type"] = 26
    # 'latest' -> no anime_type filter, just newest posts (Home)

    raw, code, err = wp_get("anime", params)
    if code != 200 or not isinstance(raw, list):
        detail = err or (raw.get("message") if isinstance(raw, dict) else "Unexpected response")
        return api_error("Failed to fetch anime list from animohubpro.com", code or 502, detail)

    items = [normalize_anime(post) for post in raw]
    return api_success(items, page=page, per_page=per_page, type=anime_type)


@app.route("/genres")
def genres():
    per_page = min(100, max(1, request.args.get("per_page", 50, type=int)))
    raw, code, err = wp_get("genre", {"per_page": per_page})
    if code != 200 or not isinstance(raw, list):
        return api_error("Failed to fetch genres from animohubpro.com", code or 502, err)

    items = [normalize_taxonomy(term) for term in raw]
    return api_success(items)


@app.route("/genre")
def genre_filter():
    genre_id = request.args.get("id", 0, type=int)
    if genre_id <= 0:
        return api_error("Missing or invalid ?id= (genre id). Use /genres to list valid ids.", 400)

    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))

    raw, code, err = wp_get("anime", {"genre": genre_id, "page": page, "per_page": per_page})
    if code != 200 or not isinstance(raw, list):
        return api_error("Failed to fetch anime for this genre", code or 502, err)

    items = [normalize_anime(post) for post in raw]
    return api_success(items, genre_id=genre_id, page=page, per_page=per_page)


@app.route("/types")
def types():
    per_page = min(100, max(1, request.args.get("per_page", 50, type=int)))
    raw, code, err = wp_get("anime_type", {"per_page": per_page})
    if code != 200 or not isinstance(raw, list):
        return api_error("Failed to fetch anime types from animohubpro.com", code or 502, err)

    items = [normalize_taxonomy(term) for term in raw]
    return api_success(items)


@app.route("/detail")
def detail():
    anime_id = request.args.get("id", 0, type=int)
    if anime_id <= 0:
        return api_error("Missing or invalid ?id=", 400)

    raw, code, err = wp_get(f"anime/{anime_id}")
    if code != 200 or not isinstance(raw, dict) or "code" in raw:
        detail_msg = err or (raw.get("message") if isinstance(raw, dict) else None)
        return api_error("Anime not found or failed to fetch", code or 404, detail_msg)

    item = normalize_anime(raw)
    # Full content (description) is only available on the single-item endpoint.
    item["description"] = clean_html(raw.get("content", {}).get("rendered", ""))

    # PLACEHOLDER: episode list / stream URLs are not yet known — see
    # app.py header comment for how to unblock this.
    item["episodes"] = []
    item["episodes_note"] = (
        "Episode/stream API not yet mapped — send a sample watch-page "
        "network response to wire this up."
    )

    return api_success(item)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return api_error("Missing ?q= search query", 400)

    per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))

    raw, code, err = wp_get("anime", {"search": q, "per_page": per_page})
    if code != 200 or not isinstance(raw, list):
        return api_error("Search failed", code or 502, err)

    items = [normalize_anime(post) for post in raw]
    return api_success(items, query=q)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
