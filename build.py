#!/usr/bin/env python3
"""
Notion の2つのデータベース（ディズニーランド / ディズニーシー）を読み、
「決定済み」の項目を簡易マップ上にピンで表示する index.html を書き出す。

  maps/tdl_map.png, maps/tds_map.png … 背景の簡易マップ
  data/tdl_spots.json, data/tds_spots.json … 各スポットの正規化座標（0〜1）

環境変数:
  NOTION_TOKEN     Notion コネクトのアクセストークン
  NOTION_DB_LAND   ディズニーランドのデータベースID
  NOTION_DB_SEA    ディズニーシーのデータベースID

ローカル実行:
  export NOTION_TOKEN=ntn_xxxx
  export NOTION_DB_LAND=3dd7c67b3fde804492cccd0cfa6df812
  export NOTION_DB_SEA=3dd7c67b3fde804fa856e91b65a49e14
  python build.py
"""

import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
import unicodedata
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

# 「いますぐ取得」リンクの飛び先（GitHub Actions の手動実行ページ）。
# リポジトリの権限がある人だけが実行できる。空文字にするとリンクを出さない。
ACTIONS_URL = (
    "https://github.com/KeiichiNakanishi/d_map/actions/workflows/update.yml"
)

# 座標データに無い場所の手動指定（正規化座標 0〜1）。
# 例: "エレクトリカルパレード": (0.50, 0.62)
MANUAL_COORDS = {}

# 座標データにエリアごと存在しない場所の代表点。
AREA_FALLBACK = {
    "パークエントランス": (0.500, 0.930),
}

# 座標を持たない場所（パーク全体で行われるものなど）はマップに出さず一覧だけに置く
NO_PIN_AREAS = {"パークワイド"}

NOTION_VERSION = "2022-06-28"
API = "https://api.notion.com/v1"
JST = timezone(timedelta(hours=9))

HERE = os.path.dirname(os.path.abspath(__file__))

TYPE_ICON = {
    "アトラクション": "🎢",
    "ショー": "🎭",
    "パレード": "🎉",
    "ナイトタイムショー": "🎆",
    "グリーティング": "🤝",
    "レストラン": "🍽",
}

PARKS = [
    {
        "key": "L",
        "id": "land",
        "title": "🏰 ディズニーランド",
        "day": "9/21（月）",
        "spots": "data/tdl_spots.json",
        "image": "tdl_map.png",
        "src": "maps/tdl_map.png",
        "env": "NOTION_DB_LAND",
    },
    {
        "key": "S",
        "id": "sea",
        "title": "🌊 ディズニーシー",
        "day": "9/22（火）",
        "spots": "data/tds_spots.json",
        "image": "tds_map.png",
        "src": "maps/tds_map.png",
        "env": "NOTION_DB_SEA",
    },
]


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

    return {
        "name": plain(prop("名称").get("title")),
        "area": ((prop("場所").get("select") or {}) or {}).get("name") or "その他",
        "kind": ((prop("種別").get("select") or {}) or {}).get("name") or "",
        "votes": [o["name"] for o in (prop("投票").get("multi_select") or [])],
        "manual": bool(prop("決定").get("checkbox")),
        "minutes": prop("所要時間 (分)").get("number"),
        "note": plain(prop("備考").get("rich_text")),
        "url": prop("URL").get("url") or "",
    }


def is_decided(item):
    return item["manual"] or len(item["votes"]) >= THRESHOLD


def is_closed(item):
    return item["name"].startswith("🚫")


# ---------------------------------------------------------------------------
# 名寄せ（Notion の名称 ↔ 座標データの名称）
# ---------------------------------------------------------------------------

_STRIP = re.compile(r"[\s　\"'’“”・:：!！?？~〜～\-—–ー()（）]")


def norm(s):
    s = unicodedata.normalize("NFKC", s).replace("🚫", "")
    return _STRIP.sub("", s).lower()


class SpotIndex:
    """座標データを引くための索引。"""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.spots = data["spots"]
        self.by_name = {norm(s["name"]): s for s in self.spots}

        # エリアごとの重心（座標が無い項目の代表点に使う）
        self.area_center = {}
        groups = {}
        id2name = {a["id"]: a["name"] for a in data.get("areas", [])}
        for s in self.spots:
            groups.setdefault(s["area"], []).append(s)
        for aid, ss in groups.items():
            cx = sum(s["x"] for s in ss) / len(ss)
            cy = sum(s["y"] for s in ss) / len(ss)
            self.area_center[id2name.get(aid, aid)] = (cx, cy)
        for name, xy in AREA_FALLBACK.items():
            self.area_center.setdefault(name, xy)

    def lookup(self, item):
        """(x, y, exact) を返す。見つからなければ None。"""
        if item["name"] in MANUAL_COORDS:
            return (*MANUAL_COORDS[item["name"]], True)

        key = norm(item["name"])
        s = self.by_name.get(key)
        if s:
            return (s["x"], s["y"], True)

        # 前方一致・部分一致（「〜"ザ・レオナルドチャレンジ"」のような派生名）
        best = None
        for k, s in self.by_name.items():
            if k.startswith(key) or key.startswith(k):
                if best is None or len(k) > len(best[0]):
                    best = (k, s)
        if best:
            return (best[1]["x"], best[1]["y"], True)

        if item["area"] in NO_PIN_AREAS:
            return None
        c = self.area_center.get(item["area"])
        if c:
            return (c[0], c[1], False)
        return None


def spread(items):
    """同じ座標に重なったピンを小さく円状にずらす。"""
    buckets = {}
    for it in items:
        k = (round(it["_x"], 4), round(it["_y"], 4))
        buckets.setdefault(k, []).append(it)
    for (bx, by), group in buckets.items():
        n = len(group)
        if n == 1:
            continue
        r = 0.022 + 0.006 * min(n, 8)
        for i, it in enumerate(group):
            ang = 2 * math.pi * i / n - math.pi / 2
            it["_x"] = min(0.985, max(0.015, bx + r * math.cos(ang) * 0.72))
            it["_y"] = min(0.985, max(0.015, by + r * math.sin(ang)))


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def esc(s):
    return html.escape(str(s), quote=True)


def badge_text(item):
    n = len(item["votes"])
    if SHOW_VOTER_NAMES and n:
        return "・".join(item["votes"])
    if n:
        return f"{n}票"
    return "確定"


def render_pin(item):
    cls = ["pin"]
    if is_closed(item):
        cls.append("closed")
    if not item["_exact"]:
        cls.append("approx")
    tip = item["name"] + "（" + badge_text(item) + "）"
    return (
        f'<button class="{" ".join(cls)}" data-k="{esc(item["_key"])}" '
        f'style="left:{item["_x"] * 100:.2f}%;top:{item["_y"] * 100:.2f}%" '
        f'aria-label="{esc(tip)}">'
        f'<span class="dot">{item["_num"]}</span>'
        f'<span class="tip">{esc(tip)}</span>'
        f"</button>"
    )


def render_row(item):
    icon = TYPE_ICON.get(item["kind"], "•")
    name = esc(item["name"])
    if item["url"]:
        name = f'<a href="{esc(item["url"])}" target="_blank" rel="noopener">{name}</a>'

    bits = []
    if item["minutes"]:
        bits.append(f'{int(item["minutes"])}分')
    if item["manual"]:
        bits.append("確定")
    if not item["_exact"] and item["_num"]:
        bits.append("エリア内")
    meta = f'<span class="meta">{esc(" ・ ".join(bits))}</span>' if bits else ""

    cls = "row closed" if is_closed(item) else "row"
    num = (
        f'<span class="num">{item["_num"]}</span>'
        if item["_num"]
        else '<span class="num none">–</span>'
    )
    attr = f' data-k="{esc(item["_key"])}" tabindex="0"' if item["_num"] else ""
    return (
        f'<li class="{cls}"{attr}>{num}'
        f'<span class="icon">{icon}</span>'
        f'<span class="body"><span class="nm">{name}</span>{meta}</span>'
        f'<span class="badge">{esc(badge_text(item))}</span>'
        f"</li>"
    )


def render_legend(items):
    if not items:
        return (
            '<p class="none">まだ決定した場所はありません。'
            "Notion で投票が集まると、ここと地図に出てきます。</p>"
        )
    groups, order = {}, []
    for it in items:
        if it["area"] not in groups:
            groups[it["area"]] = []
            order.append(it["area"])
        groups[it["area"]].append(it)

    out = []
    for area in order:
        rows = "".join(render_row(i) for i in groups[area])
        out.append(
            f'<div class="group"><h4>{esc(area)}'
            f'<span class="gcount">{len(groups[area])}</span></h4>'
            f"<ul>{rows}</ul></div>"
        )
    return "".join(out)


def render_park(park, index, rows):
    items = [extract(p) for p in rows]
    items = [i for i in items if i["name"] and is_decided(i)]

    placed, unplaced = [], []
    for it in items:
        hit = index.lookup(it)
        if hit is None:
            it["_x"] = it["_y"] = None
            it["_exact"] = False
            unplaced.append(it)
        else:
            it["_x"], it["_y"], it["_exact"] = hit
            placed.append(it)

    spread(placed)

    # エリア順 → 票数順で番号を振る
    area_order = list(index.area_center)
    placed.sort(
        key=lambda i: (
            area_order.index(i["area"]) if i["area"] in area_order else 99,
            -len(i["votes"]),
            i["name"],
        )
    )
    for n, it in enumerate(placed, 1):
        it["_num"] = n
        it["_key"] = f'{park["key"]}{n}'
    for it in unplaced:
        it["_num"] = None
        it["_key"] = ""

    pins = "".join(render_pin(i) for i in placed)
    total = len(placed) + len(unplaced)

    return f"""
    <section class="park" id="park-{park["id"]}">
      <header class="park-head">
        <h2>{esc(park["title"])}</h2>
        <p>{esc(park["day"])} ・ 決定 {total} か所</p>
      </header>
      <div class="split">
        <figure class="figure">
          <div class="mapwrap">
            <img class="mapimg" src="{esc(park["image"])}"
                 alt="{esc(park["title"])}の簡易マップ" loading="lazy">
            {pins}
          </div>
          <figcaption>番号は一覧の番号に対応しています。
          ピンをタップすると名前が出て、一覧の該当行が光ります。</figcaption>
        </figure>
        <div class="legend">{render_legend(placed + unplaced)}</div>
      </div>
    </section>"""


CSS = """
:root{
  --bg:#f6f7f9; --panel:#fff; --ink:#1a1d23; --muted:#6b7280;
  --line:#e3e6ea; --accent:#1f6feb; --accent-soft:#e8f0fc; --on-accent:#fff;
  --hl:#e8590c; --hl-soft:#fdece3; --shadow:rgba(16,22,34,.22);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#14161a; --panel:#1c1f25; --ink:#e8eaed; --muted:#9aa3ad;
    --line:#2b2f36; --accent:#4d90f0; --accent-soft:#1f2c40; --on-accent:#fff;
    --hl:#ff8a3d; --hl-soft:#3a2415; --shadow:rgba(0,0,0,.5);
  }
}
:root[data-theme="dark"]{
  --bg:#14161a; --panel:#1c1f25; --ink:#e8eaed; --muted:#9aa3ad;
  --line:#2b2f36; --accent:#4d90f0; --accent-soft:#1f2c40; --on-accent:#fff;
  --hl:#ff8a3d; --hl-soft:#3a2415; --shadow:rgba(0,0,0,.5);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;
  line-height:1.6; -webkit-text-size-adjust:100%;
}
.wrap{max-width:1280px; margin:0 auto; padding:32px 16px 64px}
h1{font-size:1.5rem; margin:0 0 4px}
.lede{color:var(--muted); margin:0 0 14px; font-size:.9rem}

/* 更新バー */
.statusbar{
  display:flex; align-items:center; gap:12px; flex-wrap:wrap;
  background:var(--panel); border:1px solid var(--line);
  border-radius:10px; padding:9px 13px; margin:0 0 32px;
}
.statusbar .when{font-size:.82rem; color:var(--muted); flex:1 1 auto; min-width:0}
.statusbar .when b{color:var(--ink); font-weight:600}
.refresh{
  flex:none; display:inline-flex; align-items:center; gap:6px;
  border:1px solid var(--line); background:transparent; color:var(--ink);
  border-radius:8px; padding:5px 12px; font:inherit; font-size:.82rem;
  font-weight:600; cursor:pointer; transition:background .12s, border-color .12s;
}
.refresh:hover{background:var(--accent-soft); border-color:var(--accent)}
.refresh .spin{display:inline-block; transition:transform .5s}
.refresh:hover .spin{transform:rotate(180deg)}
.fetchnow{
  flex:none; font-size:.78rem; color:var(--muted); text-decoration:none;
  border-bottom:1px dotted var(--line); padding-bottom:1px;
}
.fetchnow:hover{color:var(--accent); border-bottom-color:var(--accent)}
.statusbar.fresh{border-color:var(--hl); background:var(--hl-soft)}
.statusbar.fresh .when b{color:var(--hl)}
.statusbar.fresh .refresh{
  background:var(--hl); border-color:var(--hl); color:#fff;
  animation:nudge 1.6s ease-in-out infinite;
}
.statusbar.fresh .refresh:hover{background:var(--hl); filter:brightness(1.08)}
@keyframes nudge{0%,100%{transform:translateY(0)}50%{transform:translateY(-2px)}}
@media (prefers-reduced-motion:reduce){
  .statusbar.fresh .refresh{animation:none}
  .refresh .spin{transition:none}
}
.park{margin:0 0 52px}
.park-head h2{font-size:1.15rem; margin:0 0 2px}
.park-head p{margin:0 0 14px; color:var(--muted); font-size:.85rem}

.split{
  display:grid; grid-template-columns:minmax(0,1.6fr) minmax(290px,1fr);
  gap:20px; align-items:start;
}
.figure{
  margin:0; background:var(--panel); border:1px solid var(--line);
  border-radius:12px; padding:12px;
  position:sticky; top:12px;
}
.figure figcaption{margin-top:8px; color:var(--muted); font-size:.75rem}
.mapwrap{position:relative; line-height:0; border-radius:8px; overflow:hidden}
.mapimg{width:100%; height:auto; display:block}

/* ピン */
.pin{
  position:absolute; transform:translate(-50%,-50%);
  width:26px; height:26px; padding:0; border:0; background:none;
  cursor:pointer; line-height:1; z-index:2;
}
.pin .dot{
  display:block; width:26px; height:26px; border-radius:50%;
  background:var(--accent); color:var(--on-accent);
  border:2px solid #fff; box-shadow:0 1px 4px var(--shadow);
  font-size:12px; font-weight:700; line-height:22px; text-align:center;
  transition:background .12s, transform .12s;
}
.pin.approx .dot{border-style:dashed; opacity:.9}
.pin.closed .dot{background:#8b949e}
.pin .tip{
  position:absolute; left:50%; bottom:130%; transform:translateX(-50%);
  background:var(--ink); color:var(--bg);
  font-size:11px; line-height:1.45; font-weight:600;
  padding:4px 8px; border-radius:6px; white-space:nowrap;
  opacity:0; pointer-events:none; transition:opacity .12s; z-index:3;
  max-width:240px; overflow:hidden; text-overflow:ellipsis;
}
.pin:hover .dot, .pin.hl .dot{background:var(--hl); transform:scale(1.22); z-index:4}
.pin:hover .tip, .pin.hl .tip, .pin:focus-visible .tip{opacity:1}
.pin:hover, .pin.hl{z-index:5}

/* 凡例 */
.legend{display:grid; gap:12px; align-content:start}
.legend .none{color:var(--muted); font-size:.85rem; margin:0}
.group{
  background:var(--panel); border:1px solid var(--line);
  border-radius:12px; padding:10px 12px;
}
.group h4{
  font-size:.78rem; margin:0 0 7px; color:var(--muted);
  font-weight:600; display:flex; align-items:center; gap:6px;
}
.gcount{
  background:var(--accent-soft); color:var(--accent);
  border-radius:99px; padding:0 7px; font-size:.7rem; font-weight:700;
}
.group ul{list-style:none; margin:0; padding:0; display:grid; gap:3px}
.row{
  display:flex; align-items:center; gap:7px; font-size:.85rem;
  padding:3px 6px; margin:0 -6px; border-radius:7px;
  outline:none; transition:background .12s;
}
.row[data-k]{cursor:pointer}
.row .num{
  flex:none; width:21px; height:21px; border-radius:50%;
  background:var(--accent); color:var(--on-accent);
  font-size:.7rem; font-weight:700; text-align:center; line-height:21px;
}
.row .num.none{background:transparent; color:var(--muted)}
.row.closed .num{background:#8b949e}
.row .icon{flex:none}
.row .body{flex:1 1 auto; min-width:0}
.row .nm{font-weight:600}
.row .nm a{color:inherit; text-decoration:none; border-bottom:1px solid var(--line)}
.row .nm a:hover{color:var(--accent); border-bottom-color:var(--accent)}
.row .meta{color:var(--muted); font-size:.74rem; margin-left:6px}
.row .badge{
  flex:none; background:var(--accent-soft); color:var(--accent);
  border-radius:99px; padding:1px 8px; font-size:.72rem; font-weight:700;
}
.row.closed .nm{text-decoration:line-through; opacity:.55}
.row.hl, .row[data-k]:focus-visible{background:var(--hl-soft)}
.row.hl .num{background:var(--hl)}

footer{
  margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--muted); font-size:.78rem;
}
/* Notion への埋め込み（?park=land など） */
body.compact .wrap{padding:14px 14px 22px; max-width:none}
body.compact h1, body.compact .lede{display:none}
body.compact .statusbar{margin-bottom:16px}
body.compact .park{margin-bottom:0}
body.compact .park-head h2{font-size:1rem}
body.compact footer{margin-top:22px; padding-top:12px}

@media (max-width:900px){
  .split{grid-template-columns:1fr}
  .figure{position:static}
}
@media (max-width:720px){
  .wrap{padding:24px 16px 48px}
  .pin, .pin .dot{width:22px; height:22px}
  .pin .dot{font-size:11px; line-height:18px}
}
"""

JS = """
/* ?park=land / ?park=sea … 片方のパークだけ表示（Notion 埋め込み用）
   ?compact=1 …… タイトルを省いて詰めて表示 */
(function(){
  var q = new URLSearchParams(location.search);
  var park = (q.get('park') || '').toLowerCase();
  if (park === 'land' || park === 'sea') {
    document.querySelectorAll('.park').forEach(function(s){
      if (s.id !== 'park-' + park) s.remove();
    });
  }
  if (park || q.get('compact') === '1') document.body.classList.add('compact');

  /* ?admin=1 のときだけ「いますぐ取得」を出す。
     権限のない人には押せないリンクなので、既定では隠しておく。 */
  if (q.get('admin') === '1') {
    var a = document.getElementById('fetchnow');
    if (a) a.hidden = false;
  }
})();

/* 「◯分前に更新」の表示と、新しいビルドの検知 */
(function(){
  var bar = document.getElementById('statusbar');
  if (!bar) return;
  var when  = document.getElementById('when');
  var btn   = document.getElementById('refresh');
  var built = new Date(bar.dataset.built);
  var hash  = bar.dataset.hash;
  var stale = false;

  function ago(){
    var s = Math.max(0, (Date.now() - built.getTime()) / 1000);
    if (s < 60)    return 'たった今';
    if (s < 3600)  return Math.floor(s / 60) + '分前';
    if (s < 86400) return Math.floor(s / 3600) + '時間前';
    return Math.floor(s / 86400) + '日前';
  }
  function paint(){
    if (stale) return;
    when.innerHTML = '最終更新 <b>' + ago() + '</b> ・ 5分おきに Notion から自動更新';
  }
  function markStale(){
    stale = true;
    bar.classList.add('fresh');
    when.innerHTML = '<b>新しい投票結果があります</b> ・ 読み込むと反映されます';
    btn.textContent = '最新を表示';
  }
  function check(){
    if (stale || document.hidden) return;
    fetch('status.json?t=' + Date.now(), {cache: 'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(d){ if (d && d.hash && d.hash !== hash) markStale(); })
      .catch(function(){ /* オフラインなどは黙って無視 */ });
  }

  paint();
  setInterval(paint, 20000);
  setInterval(check, 60000);
  document.addEventListener('visibilitychange', function(){
    if (!document.hidden) { paint(); check(); }
  });
  btn.addEventListener('click', function(){ location.reload(); });
  setTimeout(check, 3000);
})();

(function(){
  var sticky = null;
  function mark(k, on){
    document.querySelectorAll('[data-k="'+k+'"]').forEach(function(el){
      el.classList.toggle('hl', on);
    });
  }
  function scrollTo(k){
    var row = document.querySelector('li[data-k="'+k+'"]');
    if (row) row.scrollIntoView({block:'nearest', behavior:'smooth'});
  }
  document.querySelectorAll('[data-k]').forEach(function(el){
    var k = el.getAttribute('data-k');
    if (!k) return;
    el.addEventListener('mouseenter', function(){ mark(k, true); });
    el.addEventListener('mouseleave', function(){ if (sticky !== k) mark(k, false); });
    el.addEventListener('focus', function(){ mark(k, true); });
    el.addEventListener('blur', function(){ if (sticky !== k) mark(k, false); });
    el.addEventListener('click', function(e){
      if (e.target.tagName === 'A') return;
      if (sticky && sticky !== k) mark(sticky, false);
      sticky = (sticky === k) ? null : k;
      mark(k, sticky === k);
      if (sticky && el.tagName === 'BUTTON') scrollTo(k);
    });
  });
})();
"""


def content_hash(park_rows):
    """決定した項目だけのハッシュ。無関係な編集では変わらない。"""
    sig = []
    for p, rows in park_rows:
        for page in rows:
            it = extract(page)
            if it["name"] and is_decided(it):
                sig.append(
                    (p["key"], it["name"], it["area"], it["manual"],
                     tuple(sorted(it["votes"])))
                )
    sig.sort()
    return hashlib.sha1(repr(sig).encode("utf-8")).hexdigest()[:16]


def build_html(park_rows, built_iso, digest):
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    rule = f"{THRESHOLD}票以上、または Notion で「決定」にチェックが入ったもの"
    parks = "".join(
        render_park(p, SpotIndex(os.path.join(HERE, p["spots"])), rows)
        for p, rows in park_rows
    )

    fetch_now = (
        f'<a class="fetchnow" id="fetchnow" hidden href="{esc(ACTIONS_URL)}"'
        f' target="_blank" rel="noopener"'
        f' title="GitHub Actions を手動で実行します（リポジトリの権限が必要）">'
        f'いますぐ取得</a>'
        if ACTIONS_URL
        else ""
    )
    statusbar = f"""
  <div class="statusbar" id="statusbar"
       data-built="{esc(built_iso)}" data-hash="{esc(digest)}">
    <span class="when" id="when">最終更新 {esc(now)} JST</span>
    {fetch_now}
    <button class="refresh" id="refresh" type="button">
      <span class="spin" aria-hidden="true">⟳</span>更新
    </button>
  </div>"""

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
  {statusbar}
  {parks}
  <footer>
    破線のピンと「エリア内」は正確な位置が分からない項目で、エリアの中心に置いています。<br>
    取り消し線と灰色のピンは、旅行日程中に休止予定の項目です。<br>
    地図は位置関係をつかむための簡易マップで、正確な縮尺ではありません。
  </footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("環境変数が設定されていません: NOTION_TOKEN")

    park_rows = []
    for p in PARKS:
        db = os.environ.get(p["env"])
        if not db:
            sys.exit(f'環境変数が設定されていません: {p["env"]}')
        park_rows.append((p, query_database(db, token)))

    out_dir = os.path.join(HERE, "public")
    os.makedirs(out_dir, exist_ok=True)
    for p in PARKS:
        shutil.copyfile(
            os.path.join(HERE, p["src"]), os.path.join(out_dir, p["image"])
        )

    built_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    digest = content_hash(park_rows)

    with open(os.path.join(out_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"built": built_iso, "hash": digest}, f, ensure_ascii=False)

    out = os.path.join(out_dir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(park_rows, built_iso, digest))

    counts = " / ".join(f'{p["title"]} {len(r)}件' for p, r in park_rows)
    print(f"{counts} を読み込み、{out} を書き出しました。")


if __name__ == "__main__":
    main()
