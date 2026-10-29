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


def parse_yahoo_web(page):
    """Yahoo! JAPAN のウェブ検索結果(ページに埋め込まれたデータ)を読む。"""
    import json
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return []
    data = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("initialProps", {})
    return [{"title": _text(a.get("title", "")), "url": a.get("url", ""), "snippet": _text(a.get("description", ""))}
            for a in data.get("pageData", {}).get("algos", []) if a.get("url")]


_ENGINES = [
    ("https://search.yahoo.co.jp/search?p={q}", parse_yahoo_web),     # 日本語に強い
    ("https://www.bing.com/search?q={q}&setlang=ja&cc=JP", parse_bing),
    ("https://html.duckduckgo.com/html/?q={q}", parse_ddg),
]


def _norm(text):
    return re.sub(r"[\s　・]", "", text).lower()


def _words(query):
    return [w for w in re.split(r"[\s　]+", query.lower()) if w]


def relevance(query, result):
    """検索した言葉がどれだけ含まれているか(言葉全体がそのまま含まれていれば高い)。"""
    body = _norm(result["title"] + result["snippet"] + result["url"])
    return (3 if _norm(query) in body else 0) + sum(1 for w in _words(query) if _norm(w) in body)


def is_relevant(query, result):
    """検索した言葉(空白で区切った語)がすべて含まれているか。"""
    body = _norm(result["title"] + result["snippet"] + result["url"])
    return all(_norm(w) in body for w in _words(query))


# ---------------- 危険なサイトの確認 ----------------
# Cloudflare の「マルウェア・フィッシングを止める DNS」(無料・登録不要)に問い合わせ、
# 危険と判定されたサイト(0.0.0.0 が返る)は表示・案内しない。
_SAFE_DNS = "https://security.cloudflare-dns.com/dns-query?name={}&type=A"
_verdicts = {}  # サイト名 → True(安全) / False(危険)


def _host(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _looks_bad(url, host):
    """問い合わせなくても怪しいと分かるもの(数字だけのアドレス、http(s) 以外、ID付きのアドレスなど)。"""
    if not host or not url.lower().startswith(("http://", "https://")):
        return True
    if re.fullmatch(r"[\d.]+|\[[0-9a-f:]+\]", host) or "@" in url.split("/")[2]:
        return True
    return False


def host_is_safe(host):
    if host in _verdicts:
        return _verdicts[host]
    import json
    try:
        req = urllib.request.Request(_SAFE_DNS.format(urllib.parse.quote(host)),
                                     headers={"accept": "application/dns-json", "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        safe = not any(a.get("data") in ("0.0.0.0", "::") for a in data.get("Answer", []))
    except Exception:
        return True  # 確かめられないとき(通信の問題)は止めない。記録もしない(次に確かめ直す)
    _verdicts[host] = safe
    return safe


def safe_only(items, *keys):
    """items のうち、keys に入っている URL がすべて安全なものだけを返す(同時に確かめるので速い)。"""
    import config
    if not getattr(config, "SAFE_SITES_ONLY", True):
        return list(items)
    hosts = {_host(it[k]) for it in items for k in keys if it.get(k)}
    with ThreadPoolExecutor(8) as ex:
        verdict = dict(zip(hosts, ex.map(host_is_safe, hosts)))
    out = []
    for it in items:
        urls = [it[k] for k in keys if it.get(k)]
        if all(not _looks_bad(u, _host(u)) and verdict.get(_host(u), True) for u in urls):
            out.append(it)
    return out


def search(query, limit=5):
    """複数の検索サイトから集め、検索した言葉を含む結果を上位にする(言葉が一般的な語に分解されて、
    関係ない結果が混ざるのを防ぐ)。十分に関係する結果がそろったら、残りの検索サイトは使わない。"""
    q = urllib.parse.quote_plus(query)
    found, seen = [], set()
    for url, parse in _ENGINES:
        try:
            results = [r for r in parse(_get(url.format(q=q), timeout=5)) if r["url"].startswith("http")]
        except Exception:
            continue
        for r in results:
            key = r["url"].split("#")[0].rstrip("/")
            if key not in seen:
                seen.add(key)
                found.append(r)
        if sum(1 for r in found if is_relevant(query, r)) >= limit:
            break
    found.sort(key=lambda r: -relevance(query, r))  # 同じ点数なら検索サイトの順のまま
    return safe_only(found, "url")[:limit]  # 危険なサイトは案内しない


def page_text(page, limit=1500):
    """HTMLから本文らしい文章だけを取り出す。"""
    page = re.sub(r"(?is)<(script|style|noscript|header|footer|nav|aside|svg|form)[^>]*>.*?</\1>", " ", page)
    paras = [_text(p) for p in re.findall(r"(?is)<(?:p|h1|h2|h3|li)[^>]*>(.*?)</(?:p|h1|h2|h3|li)>", page)]
    text = " ".join(p for p in paras if len(p) >= 20) or _text(page)
    return text[:limit]


def read_pages(results, count=3, limit=1500):
    """上位のページを同時に読み込む(読めなかったページは検索結果の要約文で代用)。"""
    def one(r):
        try:
            return page_text(_get(r["url"], timeout=4), limit) or r["snippet"]
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


# 画像の見た目を表す言葉(「きれいなりんご」→ りんご + きれい に分けて検索する)
_LOOKS = ("きれい|綺麗|キレイ|美しい|うつくしい|かわいい|可愛い|カワイイ|かっこいい|カッコいい|格好いい|おしゃれ|"
          "オシャレ|お洒落|おいしそう|美味しそう|リアル|素敵|すてき|ステキ|幻想的|高画質|高解像度|鮮やか|"
          "大きい|小さい|赤い|青い|白い|黒い|黄色い|緑の|ピンクの|新鮮|面白い|おもしろい|シンプル|"
          "レトロ|夜の|朝の|夕方の|冬の|夏の|春の|秋の")
_LOOKS_RE = re.compile(rf"({_LOOKS})(?:な|の)?")
_QUALITY = ("高画質", "高解像度")


def image_queries(query):
    """話し言葉の画像の頼み方を、検索しやすい言葉の組み合わせにする。
    「きれいなりんご」→ ["りんご きれい", "りんご 高画質"]"""
    looks = [m.group(1).removesuffix("の") for m in _LOOKS_RE.finditer(query)]
    rest = _LOOKS_RE.sub(" ", query)
    nouns = [w.strip("のなをはがと、, ") for w in re.split(r"[\s　の、,]+", rest)]
    nouns = [w for w in nouns if w and w not in ("画像", "写真", "イラスト", "絵")]
    subject = " ".join(nouns) or query.strip()
    first = " ".join([subject, *looks])
    out = [first]
    if not any(q in looks for q in _QUALITY):
        out.append(f"{subject} 高画質")
    return out


def _images_one(query, limit):
    q = urllib.parse.quote_plus(query)
    for url, parse in ((f"https://search.yahoo.co.jp/image/search?p={q}", parse_yahoo_images),
                       (f"https://www.bing.com/images/search?q={q}&form=HDRSC2&first=1", parse_bing_images)):
        try:
            found = parse(_get(url))
        except Exception:
            continue
        if found:
            return found[:limit]
    return []


def images(query, limit=None):
    """画像を検索して [{"thumb", "mid", "full", "title", "page"}] を返す。Yahoo!画像検索、だめなら Bing。
    頼み方を検索しやすい言葉に組み直し、複数の言い方で同時に探して4枚ずつ交互に並べる。
    危険なサイトの画像は除く。limit を省くと設定の枚数。"""
    import config
    limit = limit or config.IMAGE_COUNT
    queries = image_queries(query)
    with ThreadPoolExecutor(len(queries)) as ex:
        lists = list(ex.map(lambda q: _images_one(q, limit + 10), queries))  # 除く分を見込んで多めに
    out, seen = [], set()
    for start in range(0, max(map(len, lists), default=0), CHUNK):
        for lst in lists:
            for item in lst[start:start + CHUNK]:
                if item["full"] not in seen:
                    seen.add(item["full"])
                    out.append(item)
    return safe_only(out, "page", "full")[:limit]


CHUNK = 4  # 言い方ごとに何枚ずつ交互に並べるか


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
