"""ダウンロードページ(配信用リポジトリの docs/。GitHub Pages で公開)を、新しい版の情報で更新する。
ページ本体・ロゴ・画面写真(動作確認で撮ったもの)・latest.json・releases.json(更新履歴)を書き込んで push する。"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def enable_pages(repo, token):
    """GitHub Pages を「main ブランチの docs/」で公開する(すでに公開済みなら何もしない)。"""
    body = json.dumps({"source": {"branch": "main", "path": "/docs"}}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/pages", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        urllib.request.urlopen(req, timeout=20)
        print("GitHub Pages を有効にしました")
    except urllib.error.HTTPError as e:
        print(f"GitHub Pages: {e.code}（409 は公開済み。403/404 は設定画面で有効にしてください）")


def api(path, token):
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def from_release(repo, token):
    """いま公開している最新版の情報(ページだけを作り直すとき)。(版, 大きさ, SHA-256, 公開日, 更新内容)"""
    rel = api(f"repos/{repo}/releases/latest", token)
    assets = {a["name"]: a for a in rel["assets"]}
    with urllib.request.urlopen(assets["ZealousSetup.exe.sha256"]["browser_download_url"], timeout=30) as r:
        sha = r.read().decode().split()[0]
    notes = [line[2:].strip() for line in (rel.get("body") or "").splitlines() if line.startswith("- ")]
    when = datetime.datetime.fromisoformat(rel["published_at"].replace("Z", "+00:00")) + datetime.timedelta(hours=9)
    return rel["tag_name"].lstrip("v"), assets["ZealousSetup.exe"]["size"], sha, when, notes


def main(version, repo, token):
    setup = os.path.join(ROOT, "dist", "ZealousSetup.exe")
    if version == "latest" or not os.path.exists(setup):  # ページだけを作り直す: 公開中の最新版の情報を使う
        version, size, sha, today, notes = from_release(repo, token)
    else:
        data = open(setup, "rb").read()
        size, sha = len(data), hashlib.sha256(data).hexdigest()
        today = datetime.datetime.utcnow() + datetime.timedelta(hours=9)  # 日本時間
        notes = json.load(open(os.path.join(ROOT, "dist", "notes.json"), encoding="utf-8"))
    tmp = tempfile.mkdtemp()
    run("git", "clone", "--depth", "1", f"https://x-access-token:{token}@github.com/{repo}.git", tmp)
    docs = os.path.join(tmp, "docs")
    os.makedirs(docs, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "site", "index.html"), docs)
    for name in ("emblem.png", "wordmark.png"):
        shutil.copy(os.path.join(ROOT, "assets", name), docs)
    shots = {"2_panel.png": "panel.png", "1_start.png": "standby.png"}  # 動作確認で撮った、いまの画面
    for src, dst in shots.items():
        p = os.path.join(ROOT, "smoke", src)
        if os.path.exists(p):
            from PIL import Image
            with Image.open(p) as im:  # 撮った写真の周り(20px)は、窓の外のデスクトップなので切り落とす
                im.crop((20, 20, im.width - 20, im.height - 20)).save(os.path.join(docs, dst))
    latest = {"version": version, "date": f"{today.year}年{today.month}月{today.day}日", "size": size,
              "sha256": sha.upper(),
              "url": f"https://github.com/{repo}/releases/latest/download/ZealousSetup.exe"}
    json.dump(latest, open(os.path.join(docs, "latest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    hist_path = os.path.join(docs, "releases.json")
    try:
        history = json.load(open(hist_path, encoding="utf-8"))
    except (OSError, ValueError):
        history = []
    if not history:  # はじめて: これまでの版を、公開済みのリリースから並べる
        for rel in api(f"repos/{repo}/releases?per_page=30", token):
            when = datetime.datetime.fromisoformat(rel["published_at"].replace("Z", "+00:00")) + datetime.timedelta(hours=9)
            history.append({"version": rel["tag_name"].lstrip("v"), "date": f"{when.year}年{when.month}月{when.day}日",
                            "notes": [ln[2:].strip() for ln in (rel.get("body") or "").splitlines() if ln.startswith("- ")]})
    old = next((h for h in history if h.get("version") == version), None)
    history = [h for h in history if h.get("version") != version]
    history.insert(0, {"version": version, "date": old["date"] if old else latest["date"],
                       "notes": notes or (old or {}).get("notes", [])})
    json.dump(history[:50], open(hist_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    owner, name = repo.split("/")
    page = f"https://{owner.lower()}.github.io/{name}/"
    open(os.path.join(tmp, "README.md"), "w", encoding="utf-8").write(
        f"# Zealous（ゼラス）\n\nダウンロードはこちら → **{page}**\n\n"
        f"最新版（v{version}）を直接ダウンロード: https://github.com/{repo}/releases/latest/download/ZealousSetup.exe\n")
    run("git", "config", "user.name", "zealous-release", cwd=tmp)
    run("git", "config", "user.email", "release@users.noreply.github.com", cwd=tmp)
    run("git", "add", "-A", cwd=tmp)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=tmp).returncode:
        run("git", "commit", "-m", f"ダウンロードページを v{version} に更新", cwd=tmp)
        run("git", "push", "origin", "HEAD:main", cwd=tmp)
    enable_pages(repo, token)
    print(f"ダウンロードページ: {page}")


if __name__ == "__main__":
    main(sys.argv[1], os.environ["RELEASE_REPO"], os.environ["GH_TOKEN"])
