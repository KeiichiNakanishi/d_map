# ディズニー旅 ｜ 決定した行き先マップ

Notion の投票を5分おきに読み取り、決定した行き先をエリア別の模式図として
GitHub Pages に公開します。サーバーは不要で、GitHub の無料枠だけで動きます。

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
ことがあります。「だいたい5〜15分以内に反映」くらいでお考えください。急ぐときは
Actions タブから手動実行してください。

**60日間リポジトリに動きがないとスケジュールが自動停止します。** 今回の旅行では
問題になりませんが、長く使う場合は覚えておいてください。

---

## 設定を変えたいとき

`build.py` の冒頭:

```python
THRESHOLD = 3            # 何票以上で「決定」とみなすか
SHOW_VOTER_NAMES = False # True にすると誰が入れたかを表示する
```

`.github/workflows/update.yml` の `cron: "*/5 * * * *"` で更新間隔を変えられます
（`*/15 * * * *` で15分おき）。最短は5分です。

---

## 決定のルール

次のどちらかを満たした項目が地図に出ます。

1. 投票が **3票以上**
2. Notion の **「決定」チェックボックス** にチェックが入っている

2 は多数決に関係なく必ず入れたい場所（レストランの予約など）のための手動指定です。
