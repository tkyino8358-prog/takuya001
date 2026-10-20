"""型(テンプレート)から投稿画像を描く。daily.best.items(best)用。

型は3つ:
  list    ... 見出し + 番号つきカード(2〜5個)
  compare ... 見出し + 左右2つのパネル(✕→○ のマーク付き、またはラベル付き)
  table   ... 見出し + 表

使い方(post.py から):  cards.render(spec, 出力パス)
spec は次の形の辞書(AIが作る)。足りない項目は validate_spec が知らせる。
  共通: template, color, title, note(省略可)
  list:    items = ["...", "..."]
  compare: left = {"label","text"}, right = {"label","text"}, mark = true/false
  table:   columns = ["列1","列2"], rows = [["..","..."], ...]
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
FONT_BOLD = FONT_DIR / "ZenMaruGothic-Bold.ttf"
FONT_BLACK = FONT_DIR / "ZenMaruGothic-Black.ttf"

S = 2  # きれいに見せるため2倍の大きさで描いて、最後に縮める
WIDTH = 1080
SIZES = {"list": (1080, 1080), "compare": (1080, 1080), "table": (1080, 1350)}
NO_LINE_START = "。、，．,.!?！？」』）)ー"
FOOTER = "塾長のおすすめ"


def _rgb(code):
    code = code.lstrip("#")
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


# 色の組み合わせ(背景の上・下、見出し、本文、うすい色、カード、線)
PALETTES = {
    "orange": dict(bg="#FFF6EC", bg2="#FFFFFF", accent="#F07C2A", strong="#7A4120", soft="#FBD9BC", card="#FFFFFF", line="#F3A56B"),
    "purple": dict(bg="#F6F0FC", bg2="#E2D5F4", accent="#50307F", strong="#3F2766", soft="#D6C6EE", card="#FFFFFF", line="#CDBBE8"),
    "green": dict(bg="#F6FBF8", bg2="#E3F1E8", accent="#1E5B45", strong="#1E5B45", soft="#CBE6D5", card="#FFFFFF", line="#BFDCCB"),
    "pink": dict(bg="#FEF1F3", bg2="#FADDE3", accent="#E0506E", strong="#4A2B2B", soft="#F9D0D8", card="#FFFFFF", line="#F3B8C4"),
    "blue": dict(bg="#F4F8FD", bg2="#E2EDF9", accent="#3B5578", strong="#34495E", soft="#D9E6F4", card="#FFFFFF", line="#BCD0E6"),
    "yellow": dict(bg="#FFFCEC", bg2="#FFF1BF", accent="#7A5230", strong="#6B4526", soft="#FBE9A6", card="#FFFDF3", line="#F5E199"),
}


def validate_spec(spec):
    """AIの作った内容が、描ける形かを調べる。問題があれば ValueError。"""
    if not isinstance(spec, dict):
        raise ValueError("画像の指定が辞書ではありません")
    kind = spec.get("template")
    if kind not in SIZES:
        raise ValueError(f"template が正しくありません: {kind}")
    if spec.get("color") not in PALETTES:
        spec["color"] = "orange"
    if not str(spec.get("title", "")).strip():
        raise ValueError("title が空です")
    if kind == "list":
        items = [str(t).strip() for t in spec.get("items", []) if str(t).strip()]
        if not 2 <= len(items) <= 5:
            raise ValueError(f"items は2〜5個にしてください: {len(items)}個")
        spec["items"] = items
    elif kind == "compare":
        for side in ("left", "right"):
            part = spec.get(side)
            if not isinstance(part, dict) or not str(part.get("text", "")).strip():
                raise ValueError(f"{side}.text が空です")
    else:
        columns, rows = spec.get("columns"), spec.get("rows")
        if not columns or not rows or len(rows) > 9:
            raise ValueError("columns と rows(9行まで)が必要です")
        if any(len(row) != len(columns) for row in rows):
            raise ValueError("rows の列の数が columns と合っていません")


def _wrap(text, font, max_width):
    lines = []
    for paragraph in str(text).split("\n"):
        current = ""
        for ch in paragraph:
            if current and ch not in NO_LINE_START and font.getlength(current + ch) > max_width:
                lines.append(current)
                current = ch
            else:
                current += ch
        lines.append(current)
    return lines


def _fit(text, font_file, max_w, max_h, size_max, size_min, ratio=1.3, keep=False):
    """枠に収まる、いちばん大きい文字の大きさを探す。(フォント, 行のリスト, 1行の高さ) を返す。

    keep=True のときは、文の途中で折り返さない大きさを優先する(入れた改行だけで行を分ける)。
    それでも収まらなければ、keep なしと同じ折り返しにもどす。
    """
    if keep:
        paragraphs = str(text).count("\n") + 1
        size = size_max
        while size >= size_min:
            font = ImageFont.truetype(str(font_file), size * S)
            lines = _wrap(text, font, max_w * S)
            if len(lines) == paragraphs and len(lines) * size * ratio <= max_h:
                return font, lines, size * ratio
            size -= 2
    size = size_max
    while True:
        font = ImageFont.truetype(str(font_file), size * S)
        lines = _wrap(text, font, max_w * S)
        widest = max(font.getlength(line) for line in lines)
        if (len(lines) * size * ratio <= max_h and widest <= max_w * S) or size <= size_min:
            return font, lines, size * ratio
        size -= 2


class Canvas:
    def __init__(self, width, height, pal):
        self.w, self.h, self.pal = width, height, pal
        top, bottom = _rgb(pal["bg"]), _rgb(pal["bg2"])
        size = (width * S, height * S)
        mask = Image.linear_gradient("L").resize(size)
        self.img = Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), mask).convert("RGBA")
        self.draw = ImageDraw.Draw(self.img)

    def color(self, key):
        return _rgb(self.pal[key])

    def _paste_layer(self, layer, x, y):
        self.img.paste(layer, (x, y), layer)

    def blob(self, cx, cy, r, alpha=110):
        """すみに置く、うすい丸い飾り。"""
        layer = Image.new("RGBA", (r * 2 * S, r * 2 * S), (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([0, 0, r * 2 * S - 1, r * 2 * S - 1], fill=self.color("soft") + (alpha,))
        self._paste_layer(layer, (cx - r) * S, (cy - r) * S)

    def decorate(self):
        self.blob(0, 0, 190)
        self.blob(self.w, self.h, 250)
        self.draw = ImageDraw.Draw(self.img)

    def card(self, box, radius=36, fill="card", outline=None, outline_w=3, shadow=True):
        x0, y0, x1, y1 = (int(v * S) for v in box)
        r = radius * S
        if shadow:
            pad = 40 * S
            layer = Image.new("RGBA", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), (0, 0, 0, 0))
            ImageDraw.Draw(layer).rounded_rectangle(
                [pad, pad + 6 * S, pad + x1 - x0, pad + 6 * S + y1 - y0], r, fill=(60, 40, 20, 34))
            self._paste_layer(layer.filter(ImageFilter.GaussianBlur(11 * S)), x0 - pad, y0 - pad)
            self.draw = ImageDraw.Draw(self.img)
        self.draw.rounded_rectangle(
            [x0, y0, x1, y1], r, fill=self.color(fill),
            outline=self.color(outline) if outline else None, width=outline_w * S if outline else 0)

    def lines(self, lines, font, top, line_h, fill, cx=None, left=None):
        """cx があれば中央そろえ、left があれば左そろえ。top は文字のかたまりの上端。"""
        for i, line in enumerate(lines):
            y = (top + (i + 0.5) * line_h) * S
            if cx is not None:
                self.draw.text((cx * S, y), line, font=font, fill=self.color(fill), anchor="mm")
            else:
                self.draw.text((left * S, y), line, font=font, fill=self.color(fill), anchor="lm")

    def text_in_box(self, text, box, font_file, size_max, size_min, fill, align="center", pad=0, keep=False):
        """枠(box)の真ん中に、収まる大きさで文字を置く。"""
        x0, y0, x1, y1 = box
        font, lines, line_h = _fit(text, font_file, x1 - x0 - pad * 2, y1 - y0, size_max, size_min, keep=keep)
        top = y0 + ((y1 - y0) - len(lines) * line_h) / 2
        if align == "center":
            self.lines(lines, font, top, line_h, fill, cx=(x0 + x1) / 2)
        else:
            self.lines(lines, font, top, line_h, fill, left=x0 + pad)

    def footer(self):
        font = ImageFont.truetype(str(FONT_BOLD), 30 * S)
        self.draw.text(((self.w - 48) * S, (self.h - 52) * S), FOOTER, font=font, fill=self.color("accent"), anchor="rm")

    def save(self, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        final = self.img.convert("RGB").resize((self.w, self.h), Image.LANCZOS)
        final.save(out_path, "JPEG", quality=93)


# ---------- 型1: 番号つきカード ----------
def draw_list(c, spec):
    c.decorate()
    c.text_in_box(spec["title"], (60, 70, 1020, 340), FONT_BLACK, 88, 52, "accent", keep=True)
    items, note = spec["items"], str(spec.get("note", "")).strip()
    y0, y1 = 380, (890 if note else 940)
    gap = 26
    card_h = min(160, (y1 - y0 - gap * (len(items) - 1)) / len(items))
    for i, text in enumerate(items):
        top = y0 + i * (card_h + gap)
        c.card((50, top, 1030, top + card_h), radius=card_h / 2.4)
        d = min(96, card_h - 36)
        cx, cy = 50 + 30 + d / 2, top + card_h / 2
        c.draw.ellipse([(cx - d / 2) * S, (cy - d / 2) * S, (cx + d / 2) * S, (cy + d / 2) * S], fill=c.color("soft"))
        num_font = ImageFont.truetype(str(FONT_BLACK), int(d * 0.55) * S)
        c.draw.text((cx * S, cy * S), str(i + 1), font=num_font, fill=c.color("accent"), anchor="mm")
        c.text_in_box(text, (cx + d / 2 + 24, top + 10, 1030 - 36, top + card_h - 10),
                      FONT_BOLD, 58, 34, "strong", align="left")
    if note:
        c.text_in_box(note, (60, 905, 1020, 990), FONT_BOLD, 46, 30, "strong", keep=True)


# ---------- 型2: 左右の比較 ----------
def _draw_mark(c, kind, cx, cy, size):
    """kind が x なら✕、o なら○。"""
    color = c.color("accent")
    s = size * S
    if kind == "x":
        half, w = s * 0.36, int(s * 0.17)
        for (ax, ay, bx, by) in ((-1, -1, 1, 1), (-1, 1, 1, -1)):
            p0 = (cx * S + ax * half, cy * S + ay * half)
            p1 = (cx * S + bx * half, cy * S + by * half)
            c.draw.line([p0, p1], fill=color, width=w)
            for p in (p0, p1):
                c.draw.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=color)
    else:
        r = s * 0.42
        c.draw.ellipse([cx * S - r, cy * S - r, cx * S + r, cy * S + r], outline=color, width=int(s * 0.14))


def draw_compare(c, spec):
    c.decorate()
    c.text_in_box(spec["title"], (60, 60, 1020, 250), FONT_BLACK, 92, 54, "accent", keep=True)
    mark = bool(spec.get("mark"))
    top, bottom = 290, 750
    boxes = {"left": (40, top, 520, bottom), "right": (560, top, 1040, bottom)}
    for side, box in boxes.items():
        part = spec[side]
        tinted = mark and side == "left"
        c.card(box, radius=44, fill="soft" if tinted else "card", outline=None if tinted else "line", shadow=not tinted)
        x0, y0, x1, y1 = box
        cx = (x0 + x1) / 2
        if mark:
            _draw_mark(c, "x" if side == "left" else "o", cx, y0 + 150, 210)
            text_box = (x0 + 20, y0 + 285, x1 - 20, y1 - 25)
        else:
            label = str(part.get("label", "")).strip()
            pill = (x0 + 28, y0 + 28, x1 - 28, y0 + 108)
            if label:
                c.draw.rounded_rectangle([v * S for v in pill], 40 * S, fill=c.color("accent"))
                c.text_in_box(label, (pill[0], pill[1], pill[2], pill[3]), FONT_BOLD, 40, 26, "card", pad=14)
            text_box = (x0 + 24, y0 + 130, x1 - 24, y1 - 24)
        c.text_in_box(part["text"], text_box, FONT_BLACK, 84, 40, "strong" if mark else "accent", keep=True)
    if mark:
        cx, cy, r = 540, 440, 42
        c.draw.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=c.color("accent"))
        c.draw.line([(cx - 17) * S, cy * S, (cx + 15) * S, cy * S], fill=(255, 255, 255), width=7 * S)
        for sign in (-1, 1):
            c.draw.line([(cx + 16) * S, cy * S, (cx + 2) * S, (cy + sign * 14) * S], fill=(255, 255, 255), width=7 * S)
    else:
        for y in range(top + 20, bottom - 10, 22):
            c.draw.ellipse([(540 - 3) * S, (y - 3) * S, (540 + 3) * S, (y + 3) * S], fill=c.color("line"))
    note = str(spec.get("note", "")).strip()
    if note:
        c.card((70, 800, 1010, 940), radius=34, fill="card", outline="line", shadow=False)
        c.text_in_box(note, (90, 805, 990, 935), FONT_BOLD, 50, 30, "strong", keep=True)


# ---------- 型3: 表 ----------
def draw_table(c, spec):
    c.card((22, 22, c.w - 22, c.h - 22), radius=46, fill="card", outline="line", shadow=False)
    c.text_in_box(spec["title"], (70, 50, 1010, 290), FONT_BLACK, 84, 50, "accent", keep=True)
    columns, rows = spec["columns"], spec["rows"]
    x0, x1, y0 = 52, 1028, 315
    note = str(spec.get("note", "")).strip()
    y1 = 1190 if note else 1240
    row_h = min(92, (y1 - y0) / (len(rows) + 1))
    col_w = (x1 - x0) / len(columns)
    table_bottom = y0 + row_h * (len(rows) + 1)
    c.draw.rounded_rectangle([x0 * S, y0 * S, x1 * S, table_bottom * S], 18 * S, outline=c.color("line"), width=3 * S)
    c.draw.rounded_rectangle([x0 * S, y0 * S, x1 * S, (y0 + row_h) * S], 18 * S, fill=c.color("soft"))
    for r_index in range(len(rows) + 1):
        y = y0 + row_h * r_index
        if r_index:
            c.draw.line([x0 * S, y * S, x1 * S, y * S], fill=c.color("line"), width=2 * S)
        cells = columns if r_index == 0 else rows[r_index - 1]
        for k, cell in enumerate(cells):
            box = (x0 + col_w * k + 10, y + 4, x0 + col_w * (k + 1) - 10, y + row_h - 4)
            c.text_in_box(str(cell), box, FONT_BOLD, 40 if r_index else 32, 22, "accent" if r_index == 0 else "strong")
    for k in range(1, len(columns)):
        x = x0 + col_w * k
        c.draw.line([x * S, y0 * S, x * S, table_bottom * S], fill=c.color("line"), width=2 * S)
    if note:
        c.text_in_box(note, (50, 1205, 1030, 1265), FONT_BOLD, 36, 22, "strong", keep=True)


DRAWERS = {"list": draw_list, "compare": draw_compare, "table": draw_table}


def render(spec, out_path):
    validate_spec(spec)
    width, height = SIZES[spec["template"]]
    canvas = Canvas(width, height, PALETTES[spec["color"]])
    DRAWERS[spec["template"]](canvas, spec)
    canvas.footer()
    canvas.save(Path(out_path))
