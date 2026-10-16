"""Instagram自動投稿: メモ -> 文章と画像を作る -> 投稿する

使い方:
  python scripts/post.py prepare   # メモを1つ選び、文章と画像を作る
  python scripts/post.py publish   # 作った画像と文章をInstagramに投稿する
"""
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
MEMOS = ROOT / "memos.txt"
POSTED = ROOT / "posted.txt"
PROFILE = ROOT / "profile.txt"
IMAGES = ROOT / "images"
BACKGROUNDS = ROOT / "backgrounds"
BACKGROUND_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
STATE = ROOT / "out" / "state.json"

IG_API = "https://graph.instagram.com/v23.0"
JST = datetime.timezone(datetime.timedelta(hours=9))
NO_LINE_START = "。、，．,.!?！？」』）)ー"


def now_jst():
    return datetime.datetime.now(JST)


def set_output(key, value):
    """GitHub Actionsの次のステップへ値を渡す。"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def fail(step, r):
    # 合言葉(トークン)が表示されないよう、URLではなく返事の中身だけを出す
    sys.exit(f"[エラー] {step} に失敗しました: {r.status_code} {r.text}")


# ---------- 1. メモを選ぶ ----------
def next_memo():
    for line in MEMOS.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            return text
    return None


# ---------- 2. 文章を作る(Claude) ----------
def ask_claude(memo):
    profile = PROFILE.read_text(encoding="utf-8")
    prompt = f"""あなたはInstagramの投稿を作る担当です。
次の「アカウント情報」と「お知らせのメモ」から、投稿を作ってください。

# アカウント情報
{profile}

# お知らせのメモ
{memo}

# 出力
次の3つの項目だけを持つJSONで答えてください。説明や```は付けないでください。
- headline: 画像に大きく載せる見出し。全角16文字くらいまで。長いときは \\n で改行する。
- subtext: 画像に小さく載せる補足。全角30文字くらいまで。不要なら空文字。
- caption: Instagramの本文。150〜300文字。読みやすく改行を使う。最後に関連するハッシュタグを3〜5個。
"""
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CONFIG["model"],
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    if r.status_code != 200:
        fail("文章づくり(Claude)", r)
    text = r.json()["content"][0]["text"]
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        sys.exit(f"[エラー] AIの返事を読み取れませんでした: {text}")
    # 本文の中の改行があっても読めるように strict=False にする
    data = json.loads(match.group(0), strict=False)
    for key in ("headline", "subtext", "caption"):
        data.setdefault(key, "")
    if not data["headline"].strip() or not data["caption"].strip():
        sys.exit(f"[エラー] 見出しか本文が空でした: {data}")
    return data


# ---------- 3. 画像を作る ----------
def hex_to_rgb(code):
    code = code.lstrip("#")
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


def find_font_path():
    candidates = []
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Sans CJK JP:bold"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if out:
            candidates.append(out)
    except (OSError, subprocess.SubprocessError):
        pass
    candidates += [
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/YuGothB.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    sys.exit("[エラー] 日本語フォントが見つかりません")


def wrap(text, font, max_width):
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for ch in paragraph:
            if current and ch not in NO_LINE_START and font.getlength(current + ch) > max_width:
                lines.append(current)
                current = ch
            else:
                current += ch
        lines.append(current)
    return lines


def pick_background():
    """backgrounds フォルダの写真から1枚選ぶ。なければ None。"""
    if not BACKGROUNDS.exists():
        return None
    files = sorted(p for p in BACKGROUNDS.iterdir() if p.suffix.lower() in BACKGROUND_EXTS)
    return random.choice(files) if files else None


def photo_background(path, width, height):
    """写真を画面いっぱいに敷き、文字が読めるよう暗い膜をかける。"""
    photo = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    photo = ImageOps.fit(photo, (width, height), method=Image.LANCZOS)
    # 文字を置く上側は暗く、人物のいる下側は明るく残す
    top = CONFIG.get("overlay_top", 0.65)
    bottom = CONFIG.get("overlay_bottom", 0.30)
    ramp = Image.linear_gradient("L").resize((width, height))
    mask = ramp.point(lambda v: int(255 * (top + (bottom - top) * v / 255)))
    dark = Image.new("RGB", (width, height), (0, 0, 0))
    return Image.composite(dark, photo, mask)


def gradient_background(width, height):
    top, bottom = (hex_to_rgb(c) for c in CONFIG["gradient"])
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / (height - 1)
        draw.line([(0, y), (width, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def make_image(headline, subtext, out_path):
    width, height = CONFIG["size"]
    margin = 90
    font_path = find_font_path()

    # 背景(写真があれば写真、なければ色のグラデーション)
    photo = pick_background()
    if photo:
        print(f"背景の写真: {photo.name}")
        img = photo_background(photo, width, height)
    else:
        img = gradient_background(width, height)
    draw = ImageDraw.Draw(img)

    # 補足
    sub_font = ImageFont.truetype(font_path, 44)
    sub_lines = wrap(subtext, sub_font, width - margin * 2) if subtext.strip() else []
    sub_gap = 66
    sub_total = 40 + len(sub_lines) * sub_gap if sub_lines else 0

    # 写真のときは文字を上の空いた所に置くので、高さの上限を決める
    max_block = int(height * 0.27) if photo else None

    # 見出し(長いときは文字を小さくして収める)
    size = 120
    while True:
        head_font = ImageFont.truetype(font_path, size)
        head_lines = wrap(headline, head_font, width - margin * 2)
        head_gap = int(size * 1.35)
        fits = len(head_lines) <= 5 and (max_block is None or len(head_lines) * head_gap + sub_total <= max_block)
        if fits or size <= 56:
            break
        size -= 6

    total = len(head_lines) * head_gap + sub_total
    if photo:
        y = int(height * 0.07) + 55  # 上の方から始める(飾り線の分を空ける)
    else:
        y = (height - total) // 2 - 20

    # 見出しの上の飾り線
    draw.rounded_rectangle([margin, y - 60, margin + 130, y - 48], radius=6, fill=hex_to_rgb(CONFIG["sub_color"]))

    for line in head_lines:
        draw.text((margin, y), line, font=head_font, fill=hex_to_rgb(CONFIG["text_color"]))
        y += head_gap
    if sub_lines:
        y += 40
        for line in sub_lines:
            draw.text((margin, y), line, font=sub_font, fill=hex_to_rgb(CONFIG["sub_color"]))
            y += sub_gap

    # 下のアカウント名
    foot_font = ImageFont.truetype(font_path, 38)
    foot = CONFIG.get("footer", "")
    if foot:
        w = foot_font.getlength(foot)
        draw.text(((width - w) / 2, height - 120), foot, font=foot_font, fill=hex_to_rgb(CONFIG["sub_color"]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92)


# ---------- prepare ----------
def prepare():
    memo = next_memo()
    if memo is None:
        print("投稿するメモがありません。memos.txt にお知らせを書き足してください。")
        set_output("has_post", "false")
        return
    print(f"メモ: {memo}")

    data = ask_claude(memo)
    name = now_jst().strftime("%Y%m%d-%H%M%S") + ".jpg"
    image_rel = f"images/{name}"
    make_image(data["headline"], data["subtext"], ROOT / image_rel)

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps({"memo": memo, "caption": data["caption"], "image": image_rel}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"見出し: {data['headline']}")
    print(f"補足: {data['subtext']}")
    print(f"本文:\n{data['caption']}")
    print(f"画像: {image_rel}")
    set_output("has_post", "true")
    set_output("image_path", image_rel)


# ---------- publish ----------
def wait_for_image(url):
    """GitHubに置いた画像が、公開URLで見えるようになるまで待つ。"""
    for _ in range(24):
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            return
        time.sleep(5)
    sys.exit(f"[エラー] 画像の公開URLが開けませんでした: {url}")


def publish():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    token = os.environ["IG_ACCESS_TOKEN"]
    user_id = os.environ["IG_USER_ID"]
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    image_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{state['image']}"

    wait_for_image(image_url)

    # (1) 投稿の下書き(コンテナ)を作る
    r = requests.post(
        f"{IG_API}/{user_id}/media",
        data={"image_url": image_url, "caption": state["caption"], "access_token": token},
        timeout=60,
    )
    if r.status_code != 200:
        fail("投稿の準備", r)
    creation_id = r.json()["id"]

    # (2) 準備が終わるまで待つ
    for _ in range(30):
        r = requests.get(
            f"{IG_API}/{creation_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        if r.status_code != 200:
            fail("準備状況の確認", r)
        status = r.json().get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            sys.exit(f"[エラー] Instagramが画像を受け付けませんでした: {r.text}")
        time.sleep(5)
    else:
        sys.exit("[エラー] 準備が終わりませんでした(時間切れ)")

    # (3) 公開する
    r = requests.post(
        f"{IG_API}/{user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=60,
    )
    if r.status_code != 200:
        fail("公開", r)
    print(f"投稿しました: {r.json()}")

    # 使ったメモを、memos.txt から posted.txt へ移す
    lines = MEMOS.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == state["memo"]:
            del lines[i]
            break
    MEMOS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with POSTED.open("a", encoding="utf-8") as f:
        f.write(f"{now_jst():%Y-%m-%d %H:%M} | {state['memo']}\n")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("prepare", "publish"):
        sys.exit(__doc__)
    {"prepare": prepare, "publish": publish}[sys.argv[1]]()
