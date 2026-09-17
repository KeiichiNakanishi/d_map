#!/usr/bin/env python3
"""
Notion の2つのデータベース（ディズニーランド / ディズニーシー）を読み、
「決定済み」の項目をエリア別の模式図として index.html に書き出す。

環境変数:
  NOTION_TOKEN     Notion インテグレーションのシークレット
  NOTION_DB_LAND   ディズニーランドのデータベースID
  NOTION_DB_SEA    ディズニーシーのデータベースID

ローカル実行:
  export NOTION_TOKEN=ntn_xxxx
  export NOTION_DB_LAND=3dd7c67b3fde804492cccd0cfa6df812
  export NOTION_DB_SEA=3dd7c67b3fde804fa856e91b65a49e14
  python build.py
"""

import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

# 何票以上で「決定」とみなすか。ここだけ変えれば全体に反映される。
THRESHOLD = 3

# 公開ページに個人名を出すかどうか。False なら票数だけを表示する。
SHOW_VOTER_NAMES = False

NOTION_VERSION = "2022-06-28"
API = "https://api.notion.com/v1"

JST = timezone(timedelta(hours=9))

# エリアの並び順（実際のパークの位置関係にあわせた 3x3 の模式図）
LAND_GRID = [
    ["クリッターカントリー", "ファンタジーランド", "トゥーンタウン"],
    ["ウエスタンランド", None, "トゥモローランド"],
    ["アドベンチャーランド", "ワールドバザール", "パークワイド"],
]
LAND_CENTER = "シンデレラ城"

SEA_GRID = [
    ["アラビアンコースト", "ファンタジースプリングス", "ロストリバーデルタ"],
    ["マーメイドラグーン", None, "ポートディスカバリー"],
    ["パークエントランス", "メディテレーニアンハーバー", "アメリカンウォーターフロント"],
]
SEA_CENTER = "ミステリアスアイランド"

TYPE_ICON = {
    "アトラクション": "🎢",
    "ショー": "🎭",
    "パレード": "🎉",
    "ナイトタイムショー": "🎆",
    "グリーティング": "🤝",
    "レストラン": "🍽",
}

# ---------------------------------------------------------------------------
# Notion API
# ---------------------------------------------------------------------------


def notion_post(path, payload, token):
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"Notion API エラー {e.code}: {body}") from None


def query_database(db_id, token):
    """データベースの全ページを取得する（ページネーション対応）。"""
    rows, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_post(f"/databases/{db_id}/query", payload, token)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


# ---------------------------------------------------------------------------
# プロパティ抽出
# ---------------------------------------------------------------------------


def plain(rich):
    return "".join(part.get("plain_text", "") for part in rich or [])


def extract(page):
    props = page.get("properties", {})

    def prop(name):
        return props.get(name) or {}

    title = plain(prop("名称").get("title"))
    votes = [o["name"] for o in (prop("投票").get("multi_select") or [])]
    decided_flag = bool(prop("決定").get("checkbox"))

    return {
        "name": title,
        "area": ((prop("場所").get("select") or {}) or {}).get("name") or "その他",
        "kind": ((prop("種別").get("select") or {}) or {}).get("name") or "",
        "votes": votes,
        "count": len(votes),
        "manual": decided_flag,
        "minutes": prop("所要時間 (分)").get("number"),
        "note": plain(prop("備考").get("rich_text")),
        "url": prop("URL").get("url") or "",
    }


def is_decided(item):
    return item["manual"] or item["count"] >= THRESHOLD


def is_closed(item):
    """名称に 🚫 が付いているものは旅行日程中に休止。"""
    return item["name"].startswith("🚫")


# ---------------------------------------------------------------------------
# HTML 生成
# ---------------------------------------------------------------------------


def esc(s):
    return html.escape(str(s), quote=True)


def render_item(item):
    icon = TYPE_ICON.get(item["kind"], "•")
    name = esc(item["name"])
    if item["url"]:
        name = f'<a href="{esc(item["url"])}" target="_blank" rel="noopener">{name}</a>'

    meta = []
    if item["minutes"]:
        meta.append(f'{int(item["minutes"])}分')
    meta_html = (
        f'<span class="meta">{esc(" / ".join(meta))}</span>' if meta else ""
    )

    if item["manual"] and item["count"] == 0:
        badge = "確定"
    elif SHOW_VOTER_NAMES:
        badge = "・".join(item["votes"]) or "確定"
    else:
        badge = f'{item["count"]}票'
        if item["manual"]:
            badge += " ・確定"

    closed = ' closed' if is_closed(item) else ""

    return (
        f'<li class="item{closed}">'
        f'<span class="icon">{icon}</span>'
        f'<span class="name">{name}</span>'
        f'{meta_html}'
        f'<span class="badge">{esc(badge)}</span>'
        f"</li>"
    )


def render_area(area, items, is_center=False):
    cls = "area center" if is_center else "area"
    if is_center and not items:
        # 中央はパークのシンボル。空でも「決定なし」とは出さない。
        return f'<div class="{cls} landmark"><h3>{esc(area)}</h3></div>'
    if not items:
        return (
            f'<div class="{cls} empty"><h3>{esc(area)}</h3>'
            f'<p class="none">まだ決定なし</p></div>'
        )
    lis = "\n".join(render_item(i) for i in items)
    return (
        f'<div class="{cls}"><h3>{esc(area)} '
        f'<span class="count">{len(items)}</span></h3>'
        f"<ul>{lis}</ul></div>"
    )


def render_park(title, subtitle, grid, center_label, by_area):
    cells = []
    for row in grid:
        for area in row:
            if area is None:
                center_items = []
                for a in list(by_area):
                    if a == center_label:
                        center_items = by_area.pop(a)
                cells.append(
                    render_area(center_label, center_items, is_center=True)
                )
            else:
                cells.append(render_area(area, by_area.pop(area, [])))

    # グリッドに載らなかったエリア（想定外の値）は下に並べる
    leftovers = "".join(
        render_area(a, items) for a, items in by_area.items() if items
    )

    total = sum(len(v) for v in by_area.values())
    return f"""
    <section class="park">
      <header class="park-head">
        <h2>{esc(title)}</h2>
        <p>{esc(subtitle)}</p>
      </header>
      <div class="grid">{''.join(cells)}</div>
      {f'<div class="grid leftovers">{leftovers}</div>' if leftovers else ''}
    </section>"""


CSS = """
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#1a1d23; --muted:#6b7280;
  --line:#e3e6ea; --accent:#2f6fd0; --accent-soft:#e8f0fc;
  --center:#fff8e6; --center-line:#e8d9a8;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#14161a; --panel:#1c1f25; --ink:#e8eaed; --muted:#9aa3ad;
    --line:#2b2f36; --accent:#78a9f0; --accent-soft:#1f2c40;
    --center:#2a2417; --center-line:#4a4028;
  }
}
:root[data-theme="dark"]{
  --bg:#14161a; --panel:#1c1f25; --ink:#e8eaed; --muted:#9aa3ad;
  --line:#2b2f36; --accent:#78a9f0; --accent-soft:#1f2c40;
  --center:#2a2417; --center-line:#4a4028;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;
  line-height:1.6; -webkit-text-size-adjust:100%;
}
.wrap{max-width:1100px; margin:0 auto; padding:32px 16px 64px}
h1{font-size:1.5rem; margin:0 0 4px}
.lede{color:var(--muted); margin:0 0 4px; font-size:.9rem}
.stamp{color:var(--muted); font-size:.8rem; margin:0 0 32px}
.park{margin:0 0 48px}
.park-head h2{font-size:1.15rem; margin:0 0 2px}
.park-head p{margin:0 0 14px; color:var(--muted); font-size:.85rem}
.grid{
  display:grid; grid-template-columns:repeat(3,1fr); gap:10px;
}
.leftovers{margin-top:10px}
.area{
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:12px 13px; min-height:96px;
}
.area.center{background:var(--center); border-color:var(--center-line)}
.area.landmark{
  display:flex; align-items:center; justify-content:center;
  border-style:dashed;
}
.area.landmark h3{margin:0; opacity:.7}
.area h3{
  font-size:.8rem; margin:0 0 8px; color:var(--muted);
  font-weight:600; letter-spacing:.02em;
  display:flex; align-items:center; gap:6px;
}
.area .count{
  background:var(--accent-soft); color:var(--accent);
  border-radius:99px; padding:0 7px; font-size:.7rem; font-weight:700;
}
.area.empty .none{color:var(--muted); font-size:.78rem; margin:0; opacity:.65}
.area ul{list-style:none; margin:0; padding:0; display:grid; gap:6px}
.item{
  display:flex; align-items:baseline; gap:6px; flex-wrap:wrap;
  font-size:.85rem;
}
.item .icon{flex:none}
.item .name{font-weight:600}
.item .name a{color:inherit; text-decoration:none; border-bottom:1px solid var(--line)}
.item .name a:hover{border-bottom-color:var(--accent); color:var(--accent)}
.item .meta{color:var(--muted); font-size:.74rem}
.item .badge{
  margin-left:auto; flex:none;
  background:var(--accent-soft); color:var(--accent);
  border-radius:99px; padding:1px 8px; font-size:.72rem; font-weight:700;
}
.item.closed .name{text-decoration:line-through; opacity:.55}
footer{
  margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--muted); font-size:.78rem;
}
@media (max-width:720px){
  .wrap{padding:24px 16px 48px}
  .grid{grid-template-columns:1fr}
  .area{min-height:0}
}
"""


def build_html(land_rows, sea_rows):
    def group(rows):
        by_area = {}
        for page in rows:
            item = extract(page)
            if not item["name"] or not is_decided(item):
                continue
            by_area.setdefault(item["area"], []).append(item)
        for items in by_area.values():
            items.sort(key=lambda i: (-i["count"], i["name"]))
        return by_area

    land_by_area = group(land_rows)
    sea_by_area = group(sea_rows)
    n_land = sum(len(v) for v in land_by_area.values())
    n_sea = sum(len(v) for v in sea_by_area.values())

    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    rule = f"{THRESHOLD}票以上、または Notion で「決定」にチェックが入ったもの"

    parks = render_park(
        "🏰 ディズニーランド",
        f"9/21（月） ・ 決定 {n_land} 件",
        LAND_GRID,
        LAND_CENTER,
        land_by_area,
    ) + render_park(
        "🌊 ディズニーシー",
        f"9/22（火） ・ 決定 {n_sea} 件",
        SEA_GRID,
        SEA_CENTER,
        sea_by_area,
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>ディズニー2泊3日旅 ｜ 決定した行き先</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>ディズニー2泊3日旅</h1>
  <p class="lede">決定した行き先（{esc(rule)}）</p>
  <p class="stamp">最終更新 {esc(now)} JST ・ Notion の投票から自動生成</p>
  {parks}
  <footer>
    エリアの配置は位置関係をイメージした模式図です。正確な地図ではありません。<br>
    取り消し線は旅行日程中に休止予定の項目です。
  </footer>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------


def main():
    token = os.environ.get("NOTION_TOKEN")
    db_land = os.environ.get("NOTION_DB_LAND")
    db_sea = os.environ.get("NOTION_DB_SEA")

    missing = [
        n
        for n, v in (
            ("NOTION_TOKEN", token),
            ("NOTION_DB_LAND", db_land),
            ("NOTION_DB_SEA", db_sea),
        )
        if not v
    ]
    if missing:
        sys.exit("環境変数が設定されていません: " + ", ".join(missing))

    land = query_database(db_land, token)
    sea = query_database(db_sea, token)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(land, sea))

    print(f"ランド {len(land)} 件 / シー {len(sea)} 件 を読み込み、{out} を書き出しました。")


if __name__ == "__main__":
    main()
