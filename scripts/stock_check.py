"""投稿のネタ(メモ・テーマ)の残りを数えて、ネタ切れが近いアカウントを知らせる。

使い方:
  python scripts/stock_check.py            ... 結果を表示する
  python scripts/stock_check.py --issue    ... 注意・要補充があれば、GitHubのIssue(=メール通知)を作る/更新する
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 名前、フォルダ、1週間の投稿回数(.github/workflows の曜日に合わせる)
ACCOUNTS = [
    ("グリーンエイジ(学習塾)", ROOT, 3),
    ("ピコ(そろばん)", ROOT / "accounts" / "pico", 3),
    ("マンマチャオ(コインランドリー)", ROOT / "accounts" / "mamma", 3),
]

WARN_WEEKS = 4   # メモがこの週数を切ったら「注意」
URGENT_WEEKS = 2  # メモがこの週数を切ったら「要補充」
ISSUE_TITLE = "【秘書】投稿ネタの補充のお知らせ"


def count_lines(path):
    if not path.exists():
        return 0
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def check(name, folder, per_week):
    config_path = folder / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    alternate = config.get("alternate", True)
    use_themes = config.get("use_themes", True)

    memos = count_lines(folder / "memos.txt")
    themes = count_lines(folder / "themes.txt") if use_themes else 0

    # メモを使う回数は、交互投稿なら2回に1回、そうでなければ毎回
    memo_per_week = per_week / 2 if alternate and use_themes else per_week
    weeks = memos / memo_per_week

    if memos == 0 and themes == 0:
        level, note = "停止", "メモもテーマもなく、投稿が止まります"
    elif memos == 0:
        level, note = "要補充", "メモが空です。今はテーマ(一般的な話題)だけで投稿しています"
    elif weeks <= URGENT_WEEKS:
        level, note = "要補充", f"あと約{weeks:.1f}週間分です"
    elif weeks <= WARN_WEEKS:
        level, note = "注意", f"あと約{weeks:.1f}週間分です"
    else:
        level, note = "OK", f"あと約{weeks:.1f}週間分です"

    theme_repeat = None
    if use_themes and themes:
        theme_per_week = per_week / 2 if alternate else 0
        if memos == 0:
            theme_per_week = per_week
        if theme_per_week:
            theme_repeat = themes / theme_per_week

    return {
        "name": name, "level": level, "note": note,
        "memos": memos, "themes": themes, "weeks": weeks,
        "theme_repeat": theme_repeat,
    }


def render(results):
    lines = ["| アカウント | 状態 | メモ残り | 目安 | テーマ数(一巡で繰り返し) |", "|---|---|---|---|---|"]
    for r in results:
        repeat = f"{r['themes']}件({r['theme_repeat']:.1f}週で一巡)" if r["theme_repeat"] else f"{r['themes']}件"
        lines.append(f"| {r['name']} | {r['level']} | {r['memos']}件 | {r['note']} | {repeat} |")
    return "\n".join(lines)


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def update_issue(results, body):
    """注意・要補充があればIssueを作る/更新。全部OKなら開いているIssueを閉じる。"""
    found = gh("issue", "list", "--state", "open", "--search", ISSUE_TITLE + " in:title",
               "--json", "number", "--jq", ".[0].number")
    number = found.stdout.strip()
    need = [r for r in results if r["level"] != "OK"]
    if need:
        if number:
            gh("issue", "edit", number, "--body", body)
        else:
            gh("issue", "create", "--title", ISSUE_TITLE, "--body", body)
    elif number:
        gh("issue", "close", number, "--comment", "すべてのアカウントでネタが十分になったので閉じます。")


def main():
    results = [check(*a) for a in ACCOUNTS]
    table = render(results)
    need = [r for r in results if r["level"] != "OK"]

    body = "投稿ネタ(メモ)の残りの確認結果です。\n\n" + table + "\n\n"
    if need:
        body += "**補充が必要なアカウント**\n"
        for r in need:
            body += f"- {r['name']}: {r['note']}(`memos.txt` にお知らせを1行1つ書き足してください)\n"
    else:
        body += "どのアカウントも、しばらく安心です。\n"

    print(body)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(body, encoding="utf-8")
    if "--issue" in sys.argv:
        update_issue(results, body)


if __name__ == "__main__":
    main()
