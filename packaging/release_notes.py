"""リリースの説明文(更新内容)を、前の版からのコミットの題名で作る。
出力: dist/notes.md(リリースのページ用) / dist/notes.json(ダウンロードページの更新履歴用)"""
import json
import os
import subprocess
import sys
import urllib.request


def previous_release_date(repo, token):
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("published_at")
    except Exception:
        return None


def changes(since):
    args = ["git", "log", "--no-merges", "--pretty=format:%s"] + ([f"--since={since}"] if since else ["-n", "15"])
    lines = subprocess.run(args, capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    out = []
    for s in lines:
        s = s.strip()
        if not s or s.startswith(("動作確認", "Merge", "テスト")):  # 使う人に関係の薄い変更は載せない
            continue
        out.append(s if len(s) <= 180 else s[:178] + "…")
    return out[:20]


def main(version, repo, token, outdir="dist"):
    items = changes(previous_release_date(repo, token) if repo and token else None)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "notes.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    body = ["## ダウンロード",
            "**`ZealousSetup.exe`** をダウンロードして開いてください（`.sha256` はファイルの確認用なので不要です）。",
            "",
            "すでに使っている場合は、Zealous の中の「更新」ボタンから更新できます。",
            "",
            f"## v{version} の変更点"]
    body += [f"- {s}" for s in items] or ["- 細かな改善"]
    with open(os.path.join(outdir, "notes.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")
    print("\n".join(body))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows の既定(cp1252)では日本語を表示できない
    main(sys.argv[1], os.environ.get("RELEASE_REPO", ""), os.environ.get("GH_TOKEN", ""))
