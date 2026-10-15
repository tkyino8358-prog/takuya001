# Instagram自動投稿

お知らせのメモから、文章と画像をAIで作り、Instagramに自動投稿します。
GitHub Actions(無料)で、毎週 月・水・金の21:30(日本時間)に動きます。

## 毎日の使い方
`memos.txt` に、投稿したいお知らせを **1行に1つ** 書き足すだけです。
GitHubの画面で `memos.txt` を開き、鉛筆アイコンから編集できます。
投稿されると、その行は自動で `posted.txt` に移動します。

## ファイルの役割
| ファイル | 役割 |
|---|---|
| `memos.txt` | これから投稿するお知らせ |
| `posted.txt` | 投稿済みの記録 |
| `profile.txt` | アカウントの説明と文章の雰囲気(AIへの指示) |
| `config.json` | 画像の色・サイズ・アカウント名 |
| `scripts/post.py` | 本体のプログラム |
| `.github/workflows/post.yml` | 実行する曜日・時間の設定 |

## テスト方法(投稿しない)
GitHubの「Actions」→「Instagram自動投稿」→「Run workflow」を押します。
「テスト」にチェックが入った状態で実行すると、文章と画像だけ作ります。
画像は、実行結果の画面の一番下「Artifacts」にある `preview` からダウンロードできます。

## 必要なSecrets(GitHubの金庫)
- `IG_ACCESS_TOKEN` : Instagramのアクセストークン(期限は約60日)
- `IG_USER_ID` : InstagramのアカウントID
- `ANTHROPIC_API_KEY` : 文章づくり用のAPIキー
