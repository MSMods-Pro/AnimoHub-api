# AnimoHub Proxy API v2 (Python / Flask)

`app.py` + `requirements.txt` — sirf animohubpro.com ke liye, pichle version
se yeh improvements:

## Naya kya hai
- **`/home` dashboard** — banners (WordPress sticky posts, ya fallback
  newest), latest, latest movies, latest series — sab **parallel** (4
  threads ek saath) fetch hoti hain, isliye request fast hai.
- **In-memory caching** (120 sec TTL) — same query baar-baar upstream
  WordPress ko hit nahi karti, response fast + upstream-friendly.
- **Automatic retries** — upstream 502/503/504 pe khud 3 baar retry karta
  hai (network blips handle ho jaate hain).
- **Real pagination metadata** — WordPress REST response headers
  (`X-WP-Total`, `X-WP-TotalPages`) se `total` / `total_pages` ab response
  me aate hain, isliye tum "load more" / page count sahi se dikha sakte ho.
- **`/detail?slug=`** — ab id ke alawa slug se bhi anime dhoond sakte ho.
- **`/health`** — upstream reachable hai ya nahi, quick check ke liye.
- **`/episodes` honest 501** — fake data ya crash dene ke bajaye clean error
  deta hai batake ki yeh abhi implement nahi hua aur kyun.

## Jo add NAHI kiya (jaan-bujh kar)
Tumne "stream resolver / intro-outro / enc-dec bridge" bhi manga tha —
woh is version me nahi hai, kyunki:
- animohubpro.com ke watch/episode page ka koi data ab tak nahi mila
  (koi HTML upload nahi hui thi jisme player/m3u8/iframe ho)
- Koi evidence nahi hai ki yeh site `enc-dec.app` jaisa koi bridge use
  karti hai — HiAnime wale request me jo pattern tha (megacloud + enc-dec)
  woh ek doosri site ka architecture tha, animohubpro ka nahi

Fake decrypt logic likhna sirf non-functional code dega. Jaise hi tum ek
watch-page ka Network -> XHR response bhejoge, `/episodes` aur ek naya
`/stream` endpoint isi file me properly wire kar dunga.

## Run
```bash
pip install -r requirements.txt
python app.py
curl "http://localhost:5000/home"
```

## Endpoints
| Endpoint | Description |
|---|---|
| `GET /home` | Dashboard: banners + latest + latest movies + latest series |
| `GET /list?type=latest\|movie\|series&page=1` | Paginated listing |
| `GET /genres` / `GET /genre?id=17` | Genre list / filter |
| `GET /types` | anime_type taxonomy list |
| `GET /detail?id=123` or `?slug=blue-box` | Full detail + description |
| `GET /search?q=naruto` | Search |
| `GET /health` | Upstream reachability check |
| `GET /episodes?id=` | Honest 501 — not implemented yet, explains why |

## Deploy
`app` object module-level pe hai — Render/Railway (`gunicorn app:app`),
Vercel Python runtime, ya kisi bhi VPS pe chalega.
