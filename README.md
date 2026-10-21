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
- 個人練習で小練習室以外を選んだら、小練習室を優先するよう警告
- 利用時間は 30・60・90分（今回の画面で確認された選択肢で、1日の上限とは別）

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
