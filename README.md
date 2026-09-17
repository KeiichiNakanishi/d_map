# ディズニー旅 ｜ 決定した行き先マップ

Notion の投票を15分おきに読み取り、決定した行き先を簡易マップ上にピンで表示して
GitHub Pages に公開します。サーバーは不要で、GitHub の無料枠だけで動きます。

## ファイル構成

```
build.py                    Notion を読んで public/index.html を生成
maps/tdl_map.png            東京ディズニーランド 簡易マップ
maps/tds_map.png            東京ディズニーシー 簡易マップ
data/tdl_spots.json         各スポットの正規化座標（0〜1）
data/tds_spots.json
data/README.md              座標データの仕様
.github/workflows/update.yml  15分おきの自動更新
```

ピンの位置は `data/*_spots.json` の `x` / `y`（画像左上が 0,0、右下が 1,1）を
そのまま使っています。Notion の「名称」と JSON の `name` を突き合わせて配置し、
**座標が見つからないもの（ショー・グリーティング・レストランなど）は
そのエリアの中心に破線のピンで置き、一覧に「エリア内」と表示します。**

---

## 慶一さんにやっていただく作業（全5ステップ・15分ほど）

### 1. Notion のコネクトを作る

1. <https://app.notion.com/developers/connections> を開く
   （Notion左下の「ヘルプ」などから 開発者ツール → **コネクション** でも辿れます。
   以前の `notion.so/my-integrations` はここに移動しました）
2. 右上の **＋ 新規コネクト**
3. コネクト名は `disney_github` など、認証方法は **アクセストークン** を選ぶ
   （OAuth ではありません）
4. **コネクトを作成** を押す
5. 一覧に現れたコネクトを開き、**内部インテグレーションシークレット**
   （`ntn_` で始まる文字列）をコピー

> このトークンは Notion の読み取り鍵です。GitHub の Secret に入れる以外の場所
> （コード内、チャット、issue など）には貼らないでください。
> コピーしたらそのままステップ4まで進んでしまうのが安全です。

### 2. Notion のページにコネクトを接続する

1. Notion で「ディズニー2泊3日旅」のページを開く
2. 右上の「•••」→ **コネクト**（接続を追加）→ さきほど作った `disney_github` を選ぶ
3. 子データベース（ディズニーランド / ディズニーシー）にも自動で権限が下ります

**これを忘れると、トークンが正しくても API は 404（ページが見つからない）を返します。**
うまくいかないときは、まずここを疑ってください。

### 3. GitHub リポジトリを作る

1. GitHub で新しいリポジトリを作成（例：`disney-trip-map`）
2. このフォルダの中身をそのまま push

```bash
git init
git add .
git commit -m "Add Notion-driven Disney map"
git branch -M main
git remote add origin https://github.com/<ユーザー名>/disney-trip-map.git
git push -u origin main
```

### 4. トークンを Secret に登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret**

| Name | Secret |
|---|---|
| `NOTION_TOKEN` | ステップ1でコピーした `ntn_...` |

### 5. GitHub Pages を有効にする

**Settings → Pages → Build and deployment → Source** を **GitHub Actions** に変更。

これで完了です。数分後に
`https://<ユーザー名>.github.io/disney-trip-map/` が公開されます。

---

## ページ上部の更新バー

ページは静的なので、開いたままでは内容が古くなります。そこで上部に:

- 「最終更新 ◯分前」をリアルタイム表示
- 裏で1分おきに `status.json` を見に行き、**新しいビルドがあればバーがオレンジになって
  「新しい投票結果があります」に変わる**
- 「最新を表示」を押すと読み込み直す

`status.json` には**決定した項目のハッシュ**が入っています。備考の修正など投票に関係ない
変更ではバーは光りません。

なお、押した瞬間に Notion を読みに行くわけではありません（静的ページからは
トークンを安全に扱えないため）。実際の取得は15分おきの GitHub Actions が行い、
ボタンはその結果を取りに行くだけです。

### 「いますぐ取得」（管理者向け）

URL に `?admin=1` を付けたときだけ、GitHub Actions の手動実行ページへのリンクが
バーに出ます。リポジトリの権限がある人しか実行できないので、既定では隠してあります。

    https://keiichinakanishi.github.io/d_map/?admin=1

このURLをブックマークしておくと「いますぐ取得 → Run workflow → 30秒後に 更新」で
好きなタイミングに反映できます。`?park=land&admin=1` のように併用もできます。

## Notion に埋め込む

Notion のページで `/embed` → 「埋め込みを作成」に URL を貼ります。

| 埋め込む場所 | URL |
|---|---|
| Day1（ランド）の下 | `https://keiichinakanishi.github.io/d_map/?park=land` |
| Day2（シー）の下 | `https://keiichinakanishi.github.io/d_map/?park=sea` |
| 両方まとめて | `https://keiichinakanishi.github.io/d_map/` |

`?park=land` / `?park=sea` を付けるとそのパークだけを表示し、ページ見出しを省いて
埋め込み向けに詰めたレイアウトになります（`?compact=1` だけでも詰まります）。

埋め込みブロックは右下をドラッグして高さを変えられます。ブロック内はスクロールできるので、
高さは600pxくらいあれば十分です。

## 動作の確認

- リポジトリの **Actions** タブで実行状況が見られます
- すぐ試したいときは Actions → 「Update Disney map」→ **Run workflow**

---

## 知っておいていただきたいこと

**公開ページです。** URLを知っていれば誰でも見られます。非公開にするには
GitHub Enterprise が必要です。そのため個人名は出さず、票数だけを表示しています
（`build.py` の `SHOW_VOTER_NAMES` で切り替えられます）。
`noindex` を入れてあるので検索には出ませんが、URLの取り扱いはご注意ください。

**cron の時刻はズレます。** GitHub Actions のスケジュールは混雑時に数十分遅れる
ことがあります。「だいたい15〜30分以内に反映」くらいでお考えください。急ぐときは
Actions タブから手動実行してください。

**60日間リポジトリに動きがないとスケジュールが自動停止します。** 今回の旅行では
問題になりませんが、長く使う場合は覚えておいてください。

---

## 設定を変えたいとき

`build.py` の冒頭:

```python
THRESHOLD = 3            # 何票以上で「決定」とみなすか
SHOW_VOTER_NAMES = False # True にすると誰が入れたかを表示する

# ピンの位置を手で決めたいときはここに書く（正規化座標 0〜1）
MANUAL_COORDS = {
    "エレクトリカルパレード": (0.50, 0.62),
}
```

`MANUAL_COORDS` に書いた項目は座標データより優先されます。
「エリア内」表示になっている項目の位置をきちんと決めたいときに使ってください。

`.github/workflows/update.yml` の `cron: "*/15 * * * *"` で更新間隔を変えられます
（`*/30 * * * *` で30分おき）。書式上の最短は5分ですが、`*/5` にすると GitHub 側に
間引かれて発火しなくなりやすく、Actions の無料分数（プライベートリポジトリは
2,000分/月）も1週間ほどで使い切ってしまうため、15分を既定にしています。

---

## 決定のルール

地図に出るかどうかは、**Notion の「確定」プロパティ（数式）だけ**が決めています。
`build.py` はその結果を読むだけなので、ルールを変えたいときは Notion を触れば十分です。

現在の「確定」の数式:

```
prop("決定") or length(prop("投票")) >= 3
```

つまり次のどちらかを満たすと地図に出ます。

1. 投票が **3票以上**
2. **「決定」チェックボックス** が入っている（多数決に関係なく行きたい場所用）

### 閾値を変える（Notion の GUI だけで完結）

1. ページ下部の「ディズニーランド」ギャラリーの右上「•••」→ **プロパティ**
2. **確定** をクリック → 数式を編集
3. `>= 3` の数字を変えて保存
4. 「ディズニーシー」も同様に

保存した時点で Notion の表示（🔥 票数で決定 / 🎯 決定済みビュー）はすぐ変わり、
地図は次のビルド（最大15分後、または手動実行）で追従します。**push は不要です。**

`build.py` の `THRESHOLD` は「確定」が読めなかったときの保険なので、
普段は触る必要がありません。
