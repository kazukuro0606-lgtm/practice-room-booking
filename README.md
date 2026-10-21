# 練習室予約の予定登録（第1段階・試作）

PC内（localhost）だけで動く、練習室予約の**予定**を記録する画面です。

- 大学サイトへのアクセス、自動ログイン、予約送信、注意事項への自動同意は**行いません**。
- 学籍番号・パスワード・Cookie は入力・保存しません。
- 「予定（未予約）」と「予約完了（大学サイトで手動予約済み）」を分けて表示します。完了にするのは、自分で大学サイトから予約した後です。
- 登録した予定は `data/plans.json` に保存されます（Gitには追加されません）。

## ルール（`booking_rules.py`）

- タイムゾーンは Asia/Tokyo
- 予約可能日時＝利用終了日時の7日前（例：2026-10-28 15:00〜16:00 → 2026-10-21 16:00 から）
- 同じ利用日の「既存予約＋希望予約」が180分を超えたら警告
- 個人練習は「3階の部屋（どこでも）」、アンサンブルは「TBの部屋」を使う。違う部屋を選んだら警告
- 利用時間は 30分〜3時間（30分刻み）

## 初回の準備（Windows / PowerShell）

`practice-room` フォルダで次を実行します。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`Activate.ps1` が「スクリプトの実行が無効」で止まる場合は、次の1行を実行してからやり直してください（今開いているPowerShellだけに効きます）。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

## 起動

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

ブラウザで http://localhost:8501 が開きます。開かない場合はアドレスを直接入力してください。
`.streamlit/config.toml` で待ち受け先を `localhost` に限定しているので、他の端末からは接続できません。

## 停止

起動したPowerShellの画面で **Ctrl + C** を押します。ブラウザのタブを閉じただけでは止まりません。

## テスト

```powershell
python -m unittest -v
```

## 段階2-1：予約ページをEdgeで開く（ログイン・予約送信はしない）

`local_settings.example.toml` をコピーして `local_settings.toml` を作り、`url` に予約ページのアドレスを書きます。
学籍番号・パスワードは書きません。`local_settings.toml` はGitに追加されません。

```powershell
python -m pip install -r requirements.txt
Copy-Item local_settings.example.toml local_settings.toml
notepad local_settings.toml
python open_site.py
```

Edgeが開き、予約ページが表示されます。Edgeのウィンドウを閉じると終了します。

## 段階2-2：自動ログイン（予約の入力・送信はしない）

ログインIDとパスワードは Windows の資格情報マネージャーに保存します（ファイル・Gitには残りません）。

```powershell
python -m pip install -r requirements.txt
python credentials.py save
python auto_login.py
```

- `credentials.py save`：ログインIDとパスワードを入力して保存します。パスワードは入力しても表示されません。
- `auto_login.py`：Edgeを開いて自動でログインします。ログイン情報は `www4.revn.jp` のページにだけ入力します。
- 保存したログイン情報を消すとき：`python credentials.py delete`

## 段階2-3の準備：予約画面の構造を調べる

```powershell
python inspect_page.py
```

自動でログインした後、予約の画面を1つずつ進め、画面ごとにPowerShellで Enter を押すと記録します。終わるときは `q` を入力して Enter。
**最後の「予約する」「申し込む」などのボタンは押さないでください。**
入力欄・ボタン・リンクの名前だけを `inspect_result.txt`（Git対象外）に保存します。入力された中身・Cookie は書き出さず、URLの秘密らしい値は `***` で伏せます。

## 段階2-3：予約内容を入力し、確認画面で止める（練習モード）

```powershell
python reserve_dryrun.py --room E312 --date 2026-10-28 --start 09:30 --minutes 60
```

- `--room`：部屋の名前（3階の部屋か E452。番号は `rooms.py`）
- `--use-type`：利用区分の表示名（省略すると「個人練習」）
- E452（TB）は利用時間が2時間まで。実行すると同時利用者の学籍番号を1人ずつ聞かれます（保存しません）。
  注意事項「複数人利用 優先のお願い」は、2026-10-21 に承認した文面（`notices.py`）と同じときだけ自動で確認にチェックします。文面が変わっていたら同意せずに止まります。
- `--minutes`：30・60・90・120・150・180 のいずれか
- 自動でログインし、利用区分と利用時間を入力して確認画面まで進みます。
- **確認画面の「登録」ボタンは押しません**（このプログラムには押す処理がありません）。Edgeを閉じると終了します。

## 部屋の番号（event_id）の一覧を調べる

```powershell
python list_rooms.py
```

自動でログインし、予約状況の画面にある部屋の名前と番号を表示します（`rooms_result.txt` にも保存。Git対象外）。

## 段階2-4：予約を送信する

```powershell
python auto_reserve.py --date 2026-10-26 --start 16:30 --minutes 90
```

- `--practice`：`個人練習`（初期値、3階の部屋）か `アンサンブル`（E452）
- 予約可能日時より前に起動すると、その3分前にログインし、時刻（＋2秒）まで待ってから予約します。待っている間はPCをつけたままにしてください。
- 候補の部屋を順に最大5室試し、確認画面まで進めた部屋で「登録」を**1回だけ**押します。押した後は別の部屋を試しません。
- 個人練習の候補は E312・E313 を除く3階の部屋です。先に試したい部屋は `local_settings.toml` の `favorite_rooms` に書きます。
- `--yes` を付けないと、「登録」を押す前に PowerShell で `y` の入力を求めます。全自動にするときだけ `--yes` を付けます。

## 予定登録の画面から自動予約を起動する

```powershell
streamlit run app.py
```

- 「3. 登録済みの予定」の **「自動予約を起動」** を押すと、新しいウィンドウで `auto_reserve.py --plan-id 〜` が起動します。予約可能日時まで、そのウィンドウを閉じずに待ちます。
- 予約が完了すると、その予定が「予約完了（自動・E3xx）」に変わります（画面を再読み込みすると反映されます）。
- 1日の合計＝「アプリの外で取った予約時間（手入力）」＋「このアプリで予約完了の予定」＋「その予定」。180分を超える予定は自動予約できません。
- 「手動で予約した → 完了にする」で、自分で予約した予定を予約完了にできます。

## 自動予約の設定と記録（予定登録の画面）

- 画面上部の「自動予約の設定」で、次を設定して「設定を保存」を押します（`data/settings.json` に保存。Git対象外）。
  - **個人練習で先に試す3階の部屋**：選んだ順に試し、残りは番号順。1回の予約で最大5室。アンサンブル（E452）には使いません。
  - **確認なしで予約する（全自動）**：オンにすると、これから起動する自動予約は `--yes` 付きになり、確認画面で `y` を待たずに送信します。
- 自動予約を実行すると、予定の下に「前回の自動予約」として、実行時刻・結果・埋まっていた部屋が表示されます。注意事項の文面が変わっていた、ログインできなかった等で途中で止まった場合も、その理由が記録されます。
- TBの部屋を選んだ予定は、練習の種類にかかわらず E452 で予約します（同時利用者は予定に入力したものを使います）。
