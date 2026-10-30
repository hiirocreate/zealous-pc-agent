"""ゼラス用のブラウザ(Chrome か Edge)を、ページの中から直接操作する(Chrome DevTools Protocol)。
あなたのマウスやキーボードは使わないので、操作の邪魔をしない。普段のブラウザとは別のプロフィールで動く。"""
import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.parse
import urllib.request

import config

PORT = 47392  # このPCの中(127.0.0.1)からだけ届く
PROFILE = os.path.join(config.APP_DIR, "browser")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------- 起動 ----------------
def exe():
    """操作できるブラウザ(Chrome / Edge)の場所。無ければ None(Firefox などはページの中を操作できない)。"""
    if os.environ.get("ZEALOUS_BROWSER_EXE"):
        return os.environ["ZEALOUS_BROWSER_EXE"]
    if os.name != "nt":
        return None
    import tools
    order = ["edge", "chrome"] if config.BROWSER == "edge" else ["chrome", "edge"]
    for name in order:
        path = tools.app_path(tools._BROWSER_EXE[name])
        if path and os.path.exists(path):
            return path
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        path = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
        if base and os.path.exists(path):
            return path
    return None


def enabled():
    return bool(getattr(config, "WEB_CONTROL_ENABLED", True)) and config.BROWSER != "firefox" and bool(exe())


def _get(path, method="GET", timeout=1.5):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8")
    try:
        return json.loads(text or "null")
    except ValueError:  # 「閉じました」などの文だけが返る問い合わせ
        return text


def running():
    try:
        return isinstance(_get("/json/version", timeout=0.4), dict)
    except OSError:
        return False


def launch(url=""):
    """ゼラス用のブラウザで開く(起動していれば新しいタブで開き、手前に出す)。"""
    if running() and os.name != "nt":
        _get("/json/new?" + urllib.parse.quote(url or "about:blank", safe=":/?&=%#"), method="PUT")
        return True
    args = [exe(), f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required"]
    if os.environ.get("ZEALOUS_BROWSER_ARGS"):
        args += os.environ["ZEALOUS_BROWSER_ARGS"].split()
    was = running()
    # 起動中なら、同じプロフィールで呼ぶと今のブラウザに新しいタブで開いて手前に出る
    subprocess.Popen(args + ([url] if url else []), creationflags=_NO_WINDOW if os.name == "nt" else 0)
    if was:
        return True
    for _ in range(60):  # 起動を待つ(最大15秒)
        if running():
            return True
        time.sleep(0.25)
    return False


def pages():
    """開いているタブ [{"id", "title", "url", "webSocketDebuggerUrl"}](最後に使ったものから)。"""
    try:
        found = _get("/json/list")
    except OSError:
        return []
    if not isinstance(found, list):
        return []
    return [p for p in found if p.get("type") == "page" and not p.get("url", "").startswith(("devtools:", "chrome-extension:"))]


def owns(hwnd, title):
    """そのウィンドウが、ゼラス用ブラウザのものか(題名がタブの題名で始まる)。"""
    import screen
    if not hwnd or not screen.class_name(hwnd).startswith("Chrome_WidgetWin"):
        return False
    return any(p.get("title") and title.startswith(p["title"]) for p in pages())


def active():
    """いま操作の対象にするのが、ゼラス用ブラウザか(起動していて、直前まで使っていた窓がそれ)。"""
    if not running():
        return False
    if os.name != "nt":
        return True
    import screen
    return owns(*screen.target_window())


# ---------------- 通信(WebSocket。外部ライブラリを使わない最小限のもの) ----------------
class _Socket:
    def __init__(self, url, timeout=10):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("ブラウザにつながりませんでした")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("ブラウザにつながりませんでした")
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("ブラウザとの接続が切れました")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text, opcode=1):
        data = text.encode() if isinstance(text, str) else text
        n = len(data)
        head = bytes([0x80 | opcode])
        head += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 \
            else bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        parts = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            op = b0 & 0x0F
            if op == 8:
                raise ConnectionError("ブラウザとの接続が切れました")
            if op == 9:
                self.send(data, 10)
                continue
            if op in (0, 1, 2):
                parts.append(data)
                if b0 & 0x80:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Page:
    """タブ1つへの接続。with Page() as p: p.call("Page.reload")"""

    def __init__(self, page=None):
        page = page or (pages() or [None])[0]
        if not page:
            raise RuntimeError("ブラウザのタブが見つかりません")
        self.info = page
        self.ws = _Socket(page["webSocketDebuggerUrl"])
        self._id = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.ws.close()

    def call(self, method, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "ブラウザの操作に失敗しました"))
                return msg.get("result") or {}

    def js(self, expr, gesture=False):
        """ページの中で JavaScript を実行して、結果(JSONにできる値)を返す。"""
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True,
                      userGesture=gesture)
        if r.get("exceptionDetails"):
            raise RuntimeError("ページの中の操作に失敗しました")
        return (r.get("result") or {}).get("value")

    def click_at(self, x, y, count=1):
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left" if kind != "mouseMoved" else "none",
                      clickCount=count)

    def key(self, name, modifiers=0):
        k = _KEYS.get(name)
        if k is None and len(name) == 1:
            k = (name, f"Key{name.upper()}" if name.isalpha() else "", ord(name.upper()))
        if k is None:
            raise ValueError(name)
        key, code, vk = k
        text = key if len(key) == 1 and not modifiers & 7 else ("\r" if key == "Enter" else "")
        down = dict(type="keyDown" if text else "rawKeyDown", key=key, code=code, windowsVirtualKeyCode=vk,
                    nativeVirtualKeyCode=vk, modifiers=modifiers)
        if text:
            down["text"] = down["unmodifiedText"] = text
        self.call("Input.dispatchKeyEvent", **down)
        self.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk,
                  nativeVirtualKeyCode=vk, modifiers=modifiers)


_KEYS = {"enter": ("Enter", "Enter", 13), "tab": ("Tab", "Tab", 9), "esc": ("Escape", "Escape", 27),
         "backspace": ("Backspace", "Backspace", 8), "delete": ("Delete", "Delete", 46), "space": (" ", "Space", 32),
         "up": ("ArrowUp", "ArrowUp", 38), "down": ("ArrowDown", "ArrowDown", 40), "left": ("ArrowLeft", "ArrowLeft", 37),
         "right": ("ArrowRight", "ArrowRight", 39), "pageup": ("PageUp", "PageUp", 33),
         "pagedown": ("PageDown", "PageDown", 34), "home": ("Home", "Home", 36), "end": ("End", "End", 35),
         **{f"f{i}": (f"F{i}", f"F{i}", 111 + i) for i in range(1, 13)}}
_MODS = {"alt": 1, "ctrl": 2, "meta": 4, "win": 4, "shift": 8}
KEY_ALIAS = {"control": "ctrl", "コントロール": "ctrl", "エンター": "enter", "改行": "enter", "return": "enter",
             "シフト": "shift", "オルト": "alt", "タブ": "tab", "エスケープ": "esc", "escape": "esc", "削除": "delete",
             "スペース": "space", "上": "up", "下": "down", "左": "left", "右": "right", "バックスペース": "backspace"}


# ---------------- ページの中の要素を探す ----------------
# 見えている要素のうち、名前(表示の文字・aria-label・placeholder・title・alt・ラベルなど)が言葉に合うものを選ぶ。
# 同じドメインの iframe と、開いた shadow DOM の中も探す。見つけた要素は window.__zealous に入れておく。
_FIND = r"""
(function(q, mode){
  const norm = s => (s || '').replace(/[\s　]+/g, ' ').trim().toLowerCase();
  const want = norm(q);
  const CLICK = 'a,button,input,select,textarea,summary,label,option,[role=button],[role=link],[role=tab],[role=menuitem],' +
    '[role=checkbox],[role=radio],[role=option],[role=switch],[role=treeitem],[onclick],[tabindex]';
  const FIELD = 'input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio])' +
    ':not([type=image]):not([type=reset]):not([type=file]),textarea,select,[contenteditable=""],[contenteditable=true],[role=textbox],[role=combobox],[role=searchbox]';
  const all = [];
  const walk = (root, dx, dy) => {
    for (const el of root.querySelectorAll('*')) {
      all.push([el, dx, dy]);
      if (el.shadowRoot) walk(el.shadowRoot, dx, dy);
      if (el.tagName === 'IFRAME') {
        try { const r = el.getBoundingClientRect(); walk(el.contentDocument, dx + r.left, dy + r.top); } catch (e) {}
      }
    }
  };
  walk(document, 0, 0);
  const shown = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && +st.opacity > 0.05;
  };
  const byId = (el, ids) => (ids || '').split(/\s+/).map(i => { const n = el.ownerDocument.getElementById(i); return n ? n.innerText : ''; }).join(' ');
  const name = el => {
    const parts = [el.getAttribute('aria-label'), byId(el, el.getAttribute('aria-labelledby')), el.getAttribute('title'),
      el.getAttribute('placeholder'), el.getAttribute('alt'), el.getAttribute('name'), el.getAttribute('data-tooltip')];
    if (el.labels) for (const l of el.labels) parts.push(l.innerText);
    if (el.tagName === 'INPUT' && /^(submit|button|reset)$/i.test(el.type)) parts.push(el.value);
    const img = el.querySelector && el.querySelector('img[alt]');
    if (img) parts.push(img.alt);
    const text = (el.innerText || el.textContent || '');
    if (text.length < 200) parts.push(text);
    return parts.filter(Boolean).map(norm);
  };
  const score = (el, interactive) => {
    let best = 0;
    for (const n of name(el)) {
      if (!n) continue;
      let s = n === want ? 100 : n.startsWith(want) ? 80 : n.includes(want) ? 60 - Math.min(20, (n.length - want.length) / 5)
        : (want.includes(n) && n.length >= 2) ? 35 : 0;
      best = Math.max(best, s);
    }
    if (!best) return 0;
    const r = el.getBoundingClientRect();
    if (r.bottom > 0 && r.top < innerHeight) best += 5;
    return best + (interactive ? 20 : 0);
  };
  let hit = null, top = 0;
  const editable = el => el.matches(FIELD) && !el.disabled && !el.readOnly;
  for (const [el, dx, dy] of all) {
    if (!shown(el)) continue;
    let s = 0;
    if (mode === 'field') {
      if (!editable(el)) continue;
      if (!want) { s = 10 + (el.type === 'search' || /search|query|^q$|検索/i.test(el.name + ' ' + el.id + ' ' + el.placeholder + ' ' + el.getAttribute('aria-label')) ? 10 : 0)
        + (el === el.ownerDocument.activeElement ? 30 : 0); }
      else s = score(el, true);
    } else {
      s = score(el, el.matches(CLICK));
    }
    if (s > top) { top = s; hit = [el, dx, dy]; }
  }
  if (!hit) return null;
  let [el, dx, dy] = hit;
  if (mode !== 'field' && !el.matches(CLICK)) el = el.closest(CLICK) || el;
  el.scrollIntoView({block: 'center', inline: 'center'});
  window.__zealous = el;
  const r = el.getBoundingClientRect();
  const x = dx + r.left + r.width / 2, y = dy + r.top + r.height / 2;
  const at = document.elementFromPoint(x, y);
  const free = !!at && (at === el || el.contains(at) || (at.shadowRoot && at.shadowRoot.contains(el)));
  const label = (name(el).find(Boolean) || el.tagName).slice(0, 40);
  const kind = (el.type || '').toLowerCase();
  return {x, y, free, label, tag: el.tagName, kind, password: kind === 'password',
          risky: /購入|注文|支払|決済|送金|振込|削除|退会|解約|確定|投稿|送信|申し込|申込|buy|order|checkout|pay|purchase|delete|submit|send|post/i.test(name(el).join(' '))};
})
"""

_ITEMS = r"""
(function(){
  const out = [], seen = new Set();
  for (const el of document.querySelectorAll('a,button,[role=button],[role=link],[role=tab],input[type=submit],summary')) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight) continue;
    const t = (el.getAttribute('aria-label') || el.innerText || el.value || el.title || '').replace(/\s+/g, ' ').trim().slice(0, 30);
    if (t && !seen.has(t)) { seen.add(t); out.push(t); }
    if (out.length >= 25) break;
  }
  return out;
})()
"""


def _find(p, q, mode="click"):
    return p.js(f"{_FIND}({json.dumps(q)}, {json.dumps(mode)})")


def items(p):
    """いま見えているリンクやボタンの名前(見つからなかったときの手がかり)。"""
    return p.js(_ITEMS) or []


# ---------------- 操作 ----------------
def click(label):
    """名前でリンクやボタンを押す。(結果の文, 見つけた要素の情報 または None)"""
    with Page() as p:
        for _ in range(3):  # 読み込み中なら少し待って探し直す
            hit = _find(p, label)
            if hit:
                break
            time.sleep(0.7)
        if not hit:
            near = items(p)
            return (f"ページの中に「{label}」が見つかりませんでした" +
                    (f"。いま見えている項目: {'、'.join(near[:15])}" if near else "")), None
        time.sleep(0.15)  # 画面の中へ動かしたあと、位置が落ち着くのを待つ
        hit = _find(p, label) or hit
        if hit["free"]:
            p.click_at(hit["x"], hit["y"])
        else:  # 上に何か重なっている: 要素そのものを押す
            p.js("window.__zealous && window.__zealous.click()", gesture=True)
        return f"「{hit['label']}」を押しました", hit


def peek(label, mode="click"):
    """押す前に、何が見つかるかだけ確かめる(危ない操作かどうかの判定用)。"""
    with Page() as p:
        return _find(p, label, mode)


def type_text(text, field="", submit=False, replace=True):
    with Page() as p:
        hit = _find(p, field, "field")
        if not hit:
            return f"「{field}」の入力欄が見つかりませんでした" if field else "文字を入れる欄が見つかりませんでした"
        if hit["password"]:
            return "パスワードの欄には入力しません。パスワードはご自身で入力してください"
        if hit["tag"] == "SELECT":
            return choose(text, field, p)
        if hit["free"]:
            p.click_at(hit["x"], hit["y"])
        p.js("(() => { const el = window.__zealous; el.focus();"
             + ("if ('value' in el && el.tagName !== 'SELECT') el.select && el.select();"
                "if (el.isContentEditable) document.execCommand('selectAll');" if replace else
                "if (el.setSelectionRange && el.value !== undefined) el.setSelectionRange(el.value.length, el.value.length);")
             + "})()", gesture=True)
        if replace:
            p.key("backspace")
        p.call("Input.insertText", text=str(text))
        if submit:
            time.sleep(0.15)
            p.key("enter")
        where = f"「{hit['label']}」" if hit["label"] and hit["label"] != hit["tag"] else "入力欄"
        return f"{where}に「{text}」と入力しました" + ("（決定しました）" if submit else "")


def choose(option, field="", page=None):
    """選択の一覧(プルダウン)から選ぶ。"""
    def run(p):
        hit = _find(p, field, "field") if field else None
        sel = "window.__zealous" if hit and hit["tag"] == "SELECT" else "document.querySelector('select')"
        got = p.js(f"""(() => {{ const s = {sel}; if (!s) return null;
          const want = {json.dumps(str(option))}.trim().toLowerCase();
          const o = [...s.options].find(o => o.text.trim().toLowerCase() === want) ||
                    [...s.options].find(o => o.text.trim().toLowerCase().includes(want));
          if (!o) return '';
          s.value = o.value; s.dispatchEvent(new Event('input', {{bubbles: true}}));
          s.dispatchEvent(new Event('change', {{bubbles: true}})); return o.text.trim(); }})()""")
        if got is None:
            return "選ぶ一覧が見つかりませんでした"
        return f"「{got}」を選びました" if got else f"一覧の中に「{option}」が見つかりませんでした"
    if page is not None:
        return run(page)
    with Page() as p:
        return run(p)


def keys(combo):
    names = [KEY_ALIAS.get(k.strip().lower(), k.strip().lower()) for k in str(combo).replace("＋", "+").split("+") if k.strip()]
    mods = sum(_MODS.get(k, 0) for k in names)
    main = [k for k in names if k not in _MODS]
    if len(main) != 1:
        return f"「{combo}」というキーは押せません"
    with Page() as p:
        try:
            p.key(main[0], mods)
        except ValueError:
            return f"「{combo}」というキーは押せません"
    return f"{'+'.join(names)} を押しました"


def scroll(down=True, amount=5):
    """ページの真ん中の位置でホイールを回したのと同じ動き(中の枠だけが動くページでも動く)。"""
    with Page() as p:
        w, h = p.js("[innerWidth, innerHeight]") or (800, 600)
        p.call("Input.dispatchMouseEvent", type="mouseWheel", x=w // 2, y=h // 2, deltaX=0,
               deltaY=(1 if down else -1) * 120 * amount)
    return "スクロールしました"


def navigate(action):
    with Page() as p:
        if action == "back":
            p.js("history.back()")
        elif action == "forward":
            p.js("history.forward()")
        elif action == "reload":
            p.call("Page.reload")
        elif action == "top":
            p.js("scrollTo({top: 0, behavior: 'instant'})")
        elif action == "bottom":
            p.js("scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})")
        else:
            return f"「{action}」はできません"
    return {"back": "前のページに戻りました", "forward": "次のページに進みました", "reload": "ページを読み込み直しました",
            "top": "ページのいちばん上に移動しました", "bottom": "ページのいちばん下に移動しました"}[action]


def read(limit=6000):
    """いま開いているページの (題名, アドレス, 本文)。"""
    with Page() as p:
        got = p.js("""(() => { const m = document.querySelector('main, article, [role=main]') || document.body;
            return [document.title, location.href, (m.innerText || '').replace(/\\n{3,}/g, '\\n\\n')]; })()""")
    title, url, text = got or ("", "", "")
    return title, url, text[:limit]


_MEDIA = {
    "play": "v.play()", "pause": "v.pause()", "toggle": "v.paused ? v.play() : v.pause()",
    "mute": "v.muted = true", "unmute": "v.muted = false",
    "fullscreen": "(v.closest('.html5-video-player') || v).requestFullscreen()",
    "exit_fullscreen": "document.exitFullscreen()",
    "forward": "v.currentTime += S", "rewind": "v.currentTime = Math.max(0, v.currentTime - S)",
    "restart": "v.currentTime = 0",
    "next": "(document.querySelector('.ytp-next-button') || {click(){ throw 0; }}).click()",
    "faster": "v.playbackRate = Math.min(4, v.playbackRate + 0.25)", "slower": "v.playbackRate = Math.max(0.25, v.playbackRate - 0.25)",
    "normal": "v.playbackRate = 1",
}


def media(action, seconds=10):
    if action not in _MEDIA:
        return f"「{action}」はできません"
    with Page() as p:
        ok = p.js("(() => { const v = [...document.querySelectorAll('video, audio')]"
                  ".sort((a, b) => (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight))[0];"
                  f"if (!v) return false; const S = {float(seconds or 10)}; try {{ const r = ({_MEDIA[action]}); if (r && r.catch) r.catch(() => 0); }} catch (e) {{}} return true; }})()",
                  gesture=True)
    if not ok:
        return "このページに動画が見つかりませんでした"
    return {"play": "再生しました", "pause": "一時停止しました", "toggle": "再生／一時停止を切り替えました",
            "mute": "消音にしました", "unmute": "音を出しました", "fullscreen": "全画面にしました",
            "exit_fullscreen": "全画面を終えました", "forward": f"{int(float(seconds or 10))}秒進めました",
            "rewind": f"{int(float(seconds or 10))}秒戻しました", "restart": "最初から再生します",
            "next": "次の動画にしました", "faster": "速くしました", "slower": "遅くしました",
            "normal": "ふつうの速さにしました"}[action]


def tab(action, name=""):
    found = pages()
    if action == "new":
        launch(name if str(name).startswith("http") else "about:blank")
        return "新しいタブを開きました"
    if not found:
        return "開いているタブがありません"
    if action == "close":
        target = next((p for p in found if name and name.lower() in p.get("title", "").lower()), found[0])
        _get(f"/json/close/{target['id']}")
        return f"「{target.get('title', '')[:30]}」のタブを閉じました"
    if action in ("next", "previous"):
        target = found[1] if len(found) > 1 else found[0]  # 一覧は最後に使った順: 2番目が「ひとつ前に使ったタブ」
    else:
        target = next((p for p in found if name and name.lower() in (p.get("title", "") + p.get("url", "")).lower()), None)
        if not target:
            return f"「{name}」のタブは見つかりませんでした。開いているタブ: " + "、".join(p.get("title", "")[:20] for p in found[:8])
    _get(f"/json/activate/{target['id']}")
    return f"「{target.get('title', '')[:30]}」のタブに切り替えました"
