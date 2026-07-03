# AnimoHub Proxy API v2 (Python / Flask)

`app.py` + `requirements.txt` — sirf animohubpro.com ke liye, pichle version
se yeh improvements:

## Naya kya hai (v2)
- **`/discover`** — animohubpro.com ka real `/wp-json/` root index fetch
  karta hai jo **har** available REST route list karta hai. Har WordPress
  site publicly yeh expose karti hai. Agar site me episode/video ka koi
  custom post type hai, yeh yahan dikh jayega — bina blind guess kiye.
- **`/episodes?id=`** — `/discover` se mile clues + common naming patterns
  (`episode`, `episodes`, `ep`, etc.) try karta hai, jo bhi real data
  deta hai wahi use karta hai. Kuch na mile toh clean 404 with exactly
  kya-kya try kiya gaya woh detail me deta hai (guess nahi banata).
- **`/stream?episode_id=&route=`** — episode post ke andar common
  field-names (`video_url`, `stream_url`, `m3u8`, `embed_url`, etc., top
  level aur `meta` dono me) dhoondta hai. Mil jaye toh URL deta hai, na
  mile toh us post ke saare real field-names deta hai taaki tum bata sako
  asli field kaunsa hai.
- **`/home` dashboard**, **caching**, **retries**, **real pagination**,
  **`/detail?slug=`**, **`/health`** — pichle version se already the.

## Yeh abhi bhi "fake resolver" nahi hai
`/episodes` aur `/stream` **guess-and-verify** karte hain against live data
— agar wahan kuch nahi milta, saaf 404 + exactly kya try kiya gaya woh
batate hain, kabhi bhi placeholder/fake JSON nahi dete. Agar `/discover`
output me episode-jaisa koi route dikhe, mujhe bhejo — main usko seedha
hardcode kar dunga taaki guessing bhi na karni pade.


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
| `GET /discover` | Real, live list of every REST route the site exposes |
| `GET /episodes?id=` | Auto-discovers + returns episodes for an anime |
| `GET /stream?episode_id=&route=` | Auto-discovers a playable stream URL for an episode |
| `GET /health` | Upstream reachability check |

## Deploy
`app` object module-level pe hai — Render/Railway (`gunicorn app:app`),
Vercel Python runtime, ya kisi bhi VPS pe chalega.
