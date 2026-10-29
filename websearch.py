"""Web検索と本文の取り出し(APIキー不要)。検索結果は Bing、だめなら DuckDuckGo の HTML から読む。"""
import base64
import html
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read(2_000_000).decode(charset, errors="replace")


def _text(fragment):
    # 文字参照で書かれたタグ(&lt;a&gt; など)も消すため、戻した後にもう一度タグを除く
    def strip(t):  # 段落の区切りは空白に、強調などの文中タグは詰める
        return re.sub(r"<[^>]+>", "", re.sub(r"(?i)<(br|/p|/div|/li|/h\d|/td)[^>]*>", " ", t))
    text = strip(html.unescape(strip(fragment)))
    return re.sub(r"\s+", " ", text).strip()


def _bing_url(href):
    """Bing の中継リンク(ck/a?...&u=a1<base64>)から本来のURLを取り出す。"""
    href = html.unescape(href)
    u = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        b = u[2:] + "=" * (-len(u[2:]) % 4)
        try:
            return base64.urlsafe_b64decode(b).decode()
        except ValueError:
            pass
    return href


def parse_bing(page):
    results = []
    for item in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
        a = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', item, re.S)
        if not a:
            continue
        snip = re.search(r"<p[^>]*>(.*?)</p>", item, re.S)
        results.append({"title": _text(a.group(2)), "url": _bing_url(a.group(1)),
                        "snippet": _text(snip.group(1)) if snip else ""})
    return results


def parse_ddg(page):
    results = []
    for href, title in re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href = html.unescape(href)
        uddg = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
        results.append({"title": _text(title), "url": uddg[0] if uddg else href, "snippet": ""})
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    for r, s in zip(results, snippets):
        r["snippet"] = _text(s)
    return results


def search(query, limit=5):
    q = urllib.parse.quote_plus(query)
    for url, parse in ((f"https://www.bing.com/search?q={q}&setlang=ja&cc=JP", parse_bing),
                       (f"https://html.duckduckgo.com/html/?q={q}", parse_ddg)):
        try:
            results = [r for r in parse(_get(url)) if r["url"].startswith("http")]
        except OSError:
            continue
        if results:
            return results[:limit]
    return []


def page_text(page, limit=1500):
    """HTMLから本文らしい文章だけを取り出す。"""
    page = re.sub(r"(?is)<(script|style|noscript|header|footer|nav|aside|svg|form)[^>]*>.*?</\1>", " ", page)
    paras = [_text(p) for p in re.findall(r"(?is)<(?:p|h1|h2|h3|li)[^>]*>(.*?)</(?:p|h1|h2|h3|li)>", page)]
    text = " ".join(p for p in paras if len(p) >= 20) or _text(page)
    return text[:limit]


def read_pages(results, count=3):
    """上位のページを同時に読み込む(読めなかったページは検索結果の要約文で代用)。"""
    def one(r):
        try:
            return page_text(_get(r["url"], timeout=6)) or r["snippet"]
        except Exception:
            return r["snippet"]
    with ThreadPoolExecutor(count) as ex:
        return list(ex.map(one, results[:count]))


def parse_yahoo_images(page):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return []
    import json
    algos = json.loads(m.group(1)).get("props", {}).get("initialProps", {}).get("pageProps", {}).get("algos", [])
    out = []
    for a in algos:
        thumb = (a.get("thumbnail") or a.get("main") or {}).get("url")
        mid = (a.get("main") or {}).get("url") or thumb  # 検索サイト側で縮小した画像(元画像が開けないときの代わり)
        full = (a.get("original") or {}).get("url") or mid
        if thumb:
            out.append({"thumb": thumb, "mid": mid, "full": full, "title": a.get("title", ""),
                        "page": a.get("refererUrl", "")})
    return out


def parse_bing_images(page):
    import json
    out = []
    for m in re.findall(r'\bm="(\{&quot;[^"]+\})"', page):
        try:
            d = json.loads(html.unescape(m))
        except ValueError:
            continue
        if d.get("turl"):
            out.append({"thumb": d["turl"], "mid": d["turl"], "full": d.get("murl") or d["turl"], "title": d.get("t", ""),
                        "page": d.get("purl", "")})
    return out


def images(query, limit=30):
    """画像を検索して [{"thumb", "mid", "full", "title", "page"}] を返す。Yahoo!画像検索、だめなら Bing。"""
    q = urllib.parse.quote_plus(query)
    for url, parse in ((f"https://search.yahoo.co.jp/image/search?p={q}", parse_yahoo_images),
                       (f"https://www.bing.com/images/search?q={q}&form=HDRSC2&first=1", parse_bing_images)):
        try:
            found = parse(_get(url))
        except OSError:
            continue
        if found:
            return found[:limit]
    return []


def fetch_image(url, timeout=10):
    """画像のデータを取得する(表示用)。url は1つ、または候補のリスト(先頭から順に試す)。"""
    if isinstance(url, (list, tuple)):
        for u in url:
            try:
                return fetch_image(u, timeout)
            except Exception:
                continue
        raise OSError("画像を取得できませんでした")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Referer": "https://search.yahoo.co.jp/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(15_000_000)
