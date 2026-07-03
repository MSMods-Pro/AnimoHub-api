# AnimoHub Proxy API (Python / Flask)

Sirf 2 files: `app.py` aur `requirements.txt` — jaisa tumne manga.

## Kyun scraper nahi, proxy hai
Tumhari 7 HTML files check ki thi — unme anime cards ka koi data nahi hai
(koi `/anime/...` link static markup me exist nahi karta), kyunki site JS se
cards runtime pe render karti hai. Raw HTML scraping (BeautifulSoup se bhi)
isliye khaali result dega. Jo kaam karta hai: site ka WordPress REST API
public hai (`wp-json/wp/v2/anime`, `/genre`, `/anime_type`) — confirmed
working (Android app me real titles aaye the: Blue Box, David, Oshi No Ko).
`app.py` usi REST API ko server-side call karke poster URLs resolve karta
hai (`_embed`), BeautifulSoup se HTML tags/entities clean karta hai, aur
stable JSON deta hai.

## Run locally
```bash
pip install -r requirements.txt
python app.py
# server chalu ho jayega http://localhost:5000 pe
curl "http://localhost:5000/list?type=latest"
```

## Endpoints

| Endpoint | Description |
|---|---|
| `GET /list?type=latest` | Home feed |
| `GET /list?type=movie&page=1` | Movie tab (anime_type=27) |
| `GET /list?type=series&page=1` | Series tab (anime_type=26) |
| `GET /genres` | All genres |
| `GET /genre?id=17&page=1` | Anime filtered by genre |
| `GET /types` | All anime_type terms |
| `GET /detail?id=123` | Full anime detail + description |
| `GET /search?q=naruto` | Search |

Sample response (`/list`, `/genre`, `/search`):
```json
{
  "success": true,
  "data": [
    {
      "id": 123,
      "slug": "blue-box",
      "title": "Blue Box",
      "excerpt": "...",
      "poster": "https://animohubpro.com/wp-content/uploads/.../poster.jpg",
      "link": "https://animohubpro.com/blue-box/",
      "genre_ids": [3, 8],
      "type_ids": [26],
      "post_status": "publish"
    }
  ],
  "page": 1,
  "per_page": 20
}
```

## Deploy
`app.py` module-level pe `app` (Flask instance) expose karta hai, isliye
kisi bhi Python/WSGI host pe chalega:
- **Render / Railway**: repo connect karo, start command `gunicorn app:app`
  (gunicorn ko `requirements.txt` me add kar dena agar yeh use karna hai).
- **Vercel (Python runtime)**: is repo ko import karo, Vercel `app.py` me
  `app` object khud detect kar leta hai.
- **VPS**: `pip install -r requirements.txt && gunicorn -w 4 -b 0.0.0.0:5000 app:app`

## Abhi bhi missing (tumhara input chahiye)
1. **Real "airing status" field** (Ongoing/Completed) — WordPress ka apna
   `status` field sirf publish/draft hai.
2. **Episode list + direct stream URL** — koi uploaded HTML watch page nahi
   thi, isliye `/detail` sirf placeholder `episodes: []` deta hai.

Fix karne ka tarika: Chrome DevTools -> Network -> XHR tab, ek watch page
kholo, episode list/stream ke liye jo JSON request jaati hai uska response
copy karke bhejo — `app.py` ke `detail()` function me wire kar dunga.
