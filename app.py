from flask import Flask, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter, Retry
import requests
import time

app = Flask(__name__)
CORS(app)

WP_BASE = "https://animohubpro.com/wp-json/wp/v2/"
WP_ROOT = "https://animohubpro.com/wp-json/"
MOVIE_TYPE_ID = 27
SERIES_TYPE_ID = 26
CACHE_TTL = 120
CANDIDATE_EPISODE_ROUTES = ["episode", "episodes", "ep", "anime-episode", "anime_episode"]
CANDIDATE_STREAM_FIELDS = [
    "video_url", "stream_url", "embed_url", "player_url", "source_url",
    "m3u8", "video", "url", "download_url",
]

_cache = {}
_session = requests.Session()
_session.headers.update({
    "Accept": "application/json",
    "User-Agent": "AnimoHubProxy/2.0 (+python-flask)",
})
_retry = Retry(total=3, backoff_factor=0.4, status_forcelist=[502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry, pool_maxsize=20))


def cache_get(key):
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    return None


def cache_set(key, value, ttl=CACHE_TTL):
    _cache[key] = (time.time() + ttl, value)


def wp_get(path, params=None, use_cache=True):
    params = dict(params or {})
    params["_embed"] = "true"
    cache_key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    if use_cache:
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

    url = WP_BASE + path.lstrip("/")
    try:
        resp = _session.get(url, params=params, timeout=15)
    except requests.RequestException as e:
        return None, 502, str(e), {}

    try:
        data = resp.json()
    except ValueError:
        return None, resp.status_code, "Non-JSON response from upstream", {}

    meta = {
        "total": resp.headers.get("X-WP-Total"),
        "total_pages": resp.headers.get("X-WP-TotalPages"),
    }

    result = (data, resp.status_code, None, meta)
    if use_cache and resp.status_code == 200:
        cache_set(cache_key, result)
    return result


def wp_root_routes(use_cache=True):
    cache_key = "__wp_root_routes__"
    if use_cache:
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

    try:
        resp = _session.get(WP_ROOT, timeout=15)
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        return None, 502, str(e)

    routes = list((data or {}).get("routes", {}).keys())
    result = (routes, resp.status_code, None)
    if use_cache and resp.status_code == 200:
        cache_set(cache_key, result, ttl=600)
    return result


def wp_get_any(path, params=None):
    """Like wp_get but for arbitrary/custom post type routes we're probing —
    doesn't assume the route exists, just reports what happened."""
    params = dict(params or {})
    params["_embed"] = "true"
    url = WP_BASE + path.lstrip("/")
    try:
        resp = _session.get(url, params=params, timeout=15)
    except requests.RequestException as e:
        return None, 502, str(e)
    try:
        data = resp.json()
    except ValueError:
        return None, resp.status_code, "Non-JSON response"
    return data, resp.status_code, None


def find_episode_route():
    """Look at the real WP route list and guess which one is episodes."""
    routes, code, err = wp_root_routes()
    if code != 200 or not routes:
        return None, CANDIDATE_EPISODE_ROUTES

    matches = [
        r for r in routes
        if "/wp/v2/" in r and any(kw in r.lower() for kw in ["episode", "/ep/", "-ep"])
    ]
    guesses = [m.split("/wp/v2/")[-1].strip("()").split("/")[0] for m in matches]
    ordered = list(dict.fromkeys(guesses + CANDIDATE_EPISODE_ROUTES))
    return matches, ordered


def find_stream_field(obj):
    """Search a post/meta dict for anything that looks like a playable link."""
    if not isinstance(obj, dict):
        return None
    for key in CANDIDATE_STREAM_FIELDS:
        if key in obj and isinstance(obj[key], str) and obj[key].startswith("http"):
            return {"field": key, "url": obj[key]}
    meta = obj.get("meta")
    if isinstance(meta, dict):
        for key in CANDIDATE_STREAM_FIELDS:
            if key in meta and isinstance(meta[key], str) and meta[key].startswith("http"):
                return {"field": f"meta.{key}", "url": meta[key]}
    return None


def clean_html(raw_html):
    if not raw_html:
        return ""
    return BeautifulSoup(raw_html, "html.parser").get_text().strip()


def extract_poster(post):
    embedded = post.get("_embedded", {}) or {}
    media_list = embedded.get("wp:featuredmedia") or []
    if media_list:
        media = media_list[0] or {}
        source_url = media.get("source_url")
        if source_url:
            return source_url
        sizes = (media.get("media_details") or {}).get("sizes", {})
        for key in ("full", "large", "medium_large", "medium"):
            if key in sizes and sizes[key].get("source_url"):
                return sizes[key]["source_url"]
    return None


def normalize_anime(post):
    return {
        "id": post.get("id"),
        "slug": post.get("slug"),
        "title": clean_html(post.get("title", {}).get("rendered", "")),
        "excerpt": clean_html(post.get("excerpt", {}).get("rendered", "")),
        "poster": extract_poster(post),
        "link": post.get("link"),
        "genre_ids": post.get("genre", []),
        "type_ids": post.get("anime_type", []),
        "sticky": post.get("sticky", False),
        "date": post.get("date"),
        "post_status": post.get("status"),
    }


def normalize_taxonomy(term):
    return {
        "id": term.get("id"),
        "name": clean_html(term.get("name", "")),
        "slug": term.get("slug"),
        "count": term.get("count", 0),
    }


def ok(data, **extra):
    payload = {"success": True, "data": data}
    payload.update(extra)
    return jsonify(payload)


def fail(message, code=500, detail=None):
    return jsonify({"success": False, "error": message, "detail": detail}), code


def fetch_anime_list(params):
    raw, code, err, meta = wp_get("anime", params)
    if code != 200 or not isinstance(raw, list):
        return [], code, err, meta
    return [normalize_anime(p) for p in raw], code, err, meta


@app.route("/")
def index():
    return ok({
        "name": "AnimoHub Proxy API v2",
        "endpoints": [
            "GET /home",
            "GET /list?type=latest|movie|series&page=1&per_page=20",
            "GET /genres",
            "GET /genre?id=17&page=1&per_page=20",
            "GET /types",
            "GET /detail?id=123",
            "GET /detail?slug=blue-box",
            "GET /search?q=naruto&per_page=20",
            "GET /discover",
            "GET /episodes?id=123",
            "GET /stream?episode_id=456",
            "GET /health",
        ],
        "note": (
            "Proxies + normalizes animohubpro.com wp-json REST API. "
            "/episodes and /stream auto-discover the real episode/video "
            "route via /discover instead of hardcoding a guess — call "
            "/discover first if they 404."
        ),
    })


@app.route("/health")
def health():
    raw, code, err, _ = wp_get("anime", {"per_page": 1}, use_cache=False)
    upstream_ok = code == 200 and isinstance(raw, list)
    return ok({"upstream_reachable": upstream_ok}, status="ok" if upstream_ok else "degraded")


@app.route("/home")
def home():
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_latest = pool.submit(fetch_anime_list, {"per_page": 12, "orderby": "date", "page": 1})
        f_movies = pool.submit(fetch_anime_list, {"per_page": 10, "anime_type": MOVIE_TYPE_ID, "page": 1})
        f_series = pool.submit(fetch_anime_list, {"per_page": 10, "anime_type": SERIES_TYPE_ID, "page": 1})
        f_sticky = pool.submit(fetch_anime_list, {"per_page": 8, "sticky": "true"})

    latest, c1, e1, _ = f_latest.result()
    movies, c2, e2, _ = f_movies.result()
    series, c3, e3, _ = f_series.result()
    sticky, c4, e4, _ = f_sticky.result()

    if c1 != 200:
        return fail("Failed to build dashboard (latest feed failed)", c1 or 502, e1)

    banners = sticky if sticky else latest[:5]

    return ok({
        "banners": banners,
        "latest": latest,
        "latest_movies": movies,
        "latest_series": series,
    }, note=(
        "'banners' uses WordPress sticky posts if any exist, else falls back "
        "to the newest items. True view-based trending (Now/Day/Week/Month) "
        "needs a page-view metric the public REST API doesn't expose — if "
        "the theme tracks views via a custom field, tell me its name and "
        "I'll wire real trending sort here."
    ))


@app.route("/list")
def list_anime():
    anime_type = request.args.get("type", "latest")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))

    params = {"page": page, "per_page": per_page, "orderby": "date"}
    if anime_type == "movie":
        params["anime_type"] = MOVIE_TYPE_ID
    elif anime_type == "series":
        params["anime_type"] = SERIES_TYPE_ID

    items, code, err, meta = fetch_anime_list(params)
    if code != 200:
        return fail("Failed to fetch anime list from animohubpro.com", code or 502, err)

    return ok(items, page=page, per_page=per_page, type=anime_type,
              total=meta.get("total"), total_pages=meta.get("total_pages"))


@app.route("/genres")
def genres():
    per_page = min(100, max(1, request.args.get("per_page", 50, type=int)))
    raw, code, err, _ = wp_get("genre", {"per_page": per_page})
    if code != 200 or not isinstance(raw, list):
        return fail("Failed to fetch genres from animohubpro.com", code or 502, err)
    return ok([normalize_taxonomy(t) for t in raw])


@app.route("/genre")
def genre_filter():
    genre_id = request.args.get("id", 0, type=int)
    if genre_id <= 0:
        return fail("Missing or invalid ?id= (genre id). Use /genres to list valid ids.", 400)

    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))

    items, code, err, meta = fetch_anime_list({"genre": genre_id, "page": page, "per_page": per_page})
    if code != 200:
        return fail("Failed to fetch anime for this genre", code or 502, err)

    return ok(items, genre_id=genre_id, page=page, per_page=per_page,
              total=meta.get("total"), total_pages=meta.get("total_pages"))


@app.route("/types")
def types():
    per_page = min(100, max(1, request.args.get("per_page", 50, type=int)))
    raw, code, err, _ = wp_get("anime_type", {"per_page": per_page})
    if code != 200 or not isinstance(raw, list):
        return fail("Failed to fetch anime types from animohubpro.com", code or 502, err)
    return ok([normalize_taxonomy(t) for t in raw])


@app.route("/detail")
def detail():
    anime_id = request.args.get("id", type=int)
    slug = request.args.get("slug")

    if not anime_id and not slug:
        return fail("Provide ?id= or ?slug=", 400)

    if slug and not anime_id:
        raw, code, err, _ = wp_get("anime", {"slug": slug})
        if code != 200 or not isinstance(raw, list) or not raw:
            return fail("Anime not found for this slug", 404, err)
        post = raw[0]
    else:
        raw, code, err, _ = wp_get(f"anime/{anime_id}")
        if code != 200 or not isinstance(raw, dict) or "code" in raw:
            return fail("Anime not found or failed to fetch", code or 404,
                        err or (raw.get("message") if isinstance(raw, dict) else None))
        post = raw

    item = normalize_anime(post)
    item["description"] = clean_html(post.get("content", {}).get("rendered", ""))
    item["episodes"] = []
    item["episodes_note"] = (
        "Episode/stream data isn't mapped yet — no watch-page network "
        "response has been provided. Send one (Chrome DevTools -> Network "
        "-> XHR, opened on a real watch page) and this will be wired for real."
    )

    return ok(item)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return fail("Missing ?q= search query", 400)

    per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))
    items, code, err, meta = fetch_anime_list({"search": q, "per_page": per_page})
    if code != 200:
        return fail("Search failed", code or 502, err)

    return ok(items, query=q, total=meta.get("total"), total_pages=meta.get("total_pages"))


@app.route("/discover")
def discover():
    routes, code, err = wp_root_routes(use_cache=False)
    if code != 200 or routes is None:
        return fail("Failed to fetch wp-json root index", code or 502, err)

    interesting = [
        r for r in routes
        if "/wp/v2/" in r and not any(
            skip in r for skip in ["/users", "/comments", "/settings", "/media", "/pages", "/posts",
                                    "/categories", "/tags", "/taxonomies", "/types", "/statuses",
                                    "/blocks", "/templates", "/menu", "/search", "/anime", "/genre"]
        )
    ]

    return ok({
        "all_routes": routes,
        "possibly_relevant": interesting,
    }, note=(
        "This is the real, live list of every REST route animohubpro.com "
        "exposes. 'possibly_relevant' filters out the routes we already "
        "know about (anime/genre/anime_type/core WP stuff) — if there's an "
        "episode/video/server custom post type, it'll show up here. Send me "
        "whatever shows up and I'll wire /episodes and /stream to the real "
        "route instead of guessing."
    ))


@app.route("/episodes")
def episodes():
    anime_id = request.args.get("id", type=int)
    if not anime_id:
        return fail("Missing ?id=", 400)

    matched_routes, guesses = find_episode_route()

    tried = []
    for route in guesses:
        for param_name in ["anime", "anime_id", "parent", "post"]:
            data, code, err = wp_get_any(route, {param_name: anime_id, "per_page": 100})
            tried.append({"route": route, "param": param_name, "status": code})
            if code == 200 and isinstance(data, list) and len(data) > 0:
                episodes_out = []
                for ep in data:
                    stream = find_stream_field(ep)
                    episodes_out.append({
                        "id": ep.get("id"),
                        "title": clean_html((ep.get("title") or {}).get("rendered", "")) or ep.get("slug"),
                        "number": (ep.get("meta") or {}).get("episode_number") or ep.get("menu_order"),
                        "stream": stream,
                    })
                return ok(episodes_out, matched_route=route, matched_param=param_name)

    return fail(
        "No episode data found automatically. animohubpro.com's watch pages "
        "render episodes/streams via client-side JS, and no matching public "
        "REST route was found among the guesses tried. Call /discover to "
        "see every real route the site exposes — if an episode/video post "
        "type is listed there, tell me its exact name and this endpoint "
        "will be wired to it precisely instead of guessing.",
        404,
        {"routes_found_in_wp_json": matched_routes, "guesses_tried": tried},
    )


@app.route("/stream")
def stream():
    episode_id = request.args.get("episode_id", type=int)
    route = request.args.get("route")

    if not episode_id:
        return fail("Missing ?episode_id= (get one from /episodes)", 400)

    routes_to_try = [route] if route else find_episode_route()[1]

    for r in routes_to_try:
        data, code, err = wp_get_any(f"{r}/{episode_id}")
        if code == 200 and isinstance(data, dict):
            stream_info = find_stream_field(data)
            if stream_info:
                return ok({
                    "episode_id": episode_id,
                    "route": r,
                    "stream": stream_info,
                    "raw_keys_available": list(data.keys()),
                })
            return fail(
                "Found the episode post but no obvious stream/video URL "
                "field on it. Check 'raw_keys_available' below and tell me "
                "which field actually holds the video link.",
                404,
                {"route": r, "raw_keys_available": list(data.keys())},
            )

    return fail(
        "Couldn't resolve a stream for this episode_id. Call /episodes?id= "
        "first to confirm the right route, or /discover to see all real "
        "routes on the site.",
        404,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
