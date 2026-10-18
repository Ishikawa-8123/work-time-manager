# クローン後の実行手順

以下の1〜8はWindows用です。WSLのUbuntuでは「9. WSL（Ubuntu）で実行」を参照してください。

## 1. 必要なもの

- Windows PC
- Python 3.10以降（インストール元：https://www.python.org/downloads/）
- Git（クローンに使用）
- 初回セットアップ時のインターネット接続（Flaskの取得に使用）

会社PCでは、ソフトウェアのインストール・通信に関する社内ルールに従ってください。

PowerShellで `py -3 --version` を実行し、Python 3.10以降が表示されることを確認します。`py` が見つからない場合は `python --version` で確認してください。どちらも使えない場合はPythonをインストールし、PowerShellを開き直してください。

## 2. プロジェクトを取得

保存先のフォルダでPowerShellを開き、次を実行します。

```powershell
git clone https://github.com/Ishikawa-8123/work-time-manager.git
cd work-time-manager
```

非公開リポジトリの場合は、アクセス権のあるGitHubアカウントで認証が必要です。公開リポジトリなら閲覧用の認証なしで取得できます。

すでにクローン済みの場合は、この操作を繰り返す必要はありません。`app.py`、`requirements.txt`、`start.bat` があるフォルダを開いてください。

## 3. 起動（通常の方法）

1. エクスプローラーで取得した `work-time-manager` フォルダを開きます。
2. `start.bat` をダブルクリックします。
3. 初回は `.venv`（専用のPython環境）が作られ、Flaskがインストールされます。
4. 黒い画面に `Running on http://127.0.0.1:5000` と表示されるまで待ちます。
5. 自動で開いたブラウザで http://127.0.0.1:5000 を表示します。

ブラウザが先に開いて接続エラーになったら、起動表示を待って再読み込みしてください。黒い画面はアプリ使用中、開いたままにします。2回目以降も同じ `start.bat` で起動できます。

SQLiteのインストールやDBの手動作成は不要です。初回起動時に `app.py` と同じフォルダへ `work_time.db` が自動作成されます。付属の `work_time.empty.db` をコピーする必要もありません。

## 4. 動作を確認

1. タスク名を入力し、「タスク追加」を押します。
2. 開始 `09:00`、終了 `10:00` で「時間を記録」を押し、60分になることを確認します。
3. 一番下のメモ欄に入力し、「メモを保存」を押します。
4. ページを再読み込みして、タスクとメモが残ることを確認します。

確認で作った記録は必要に応じて削除してください。タスク削除では、そのタスクの過去の時間記録も削除されます。

日付は日本時間です。翌日もタスク名と保存したメモは残り、本日の時間集計は0分から始まります。過去の時間記録は「履歴」で確認できます。

## 5. 停止・再起動

起動時の黒い画面を選択し、**Ctrl + C** を押してください。`バッチ ジョブを終了しますか (Y/N)?` と表示されたら `Y` を入力してEnterを押します。黒い画面を閉じても停止できます。

ブラウザのタブを閉じるだけではアプリは停止しません。停止後も保存済みの記録は残ります。再開する場合は `start.bat` を起動し、ブラウザを再読み込みしてください。

## 6. 手動で起動する場合

`start.bat` を使わない場合は、プロジェクトのフォルダで次を実行します。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

`py` が使えず `python` が使える環境では、最初の行だけ `python -m venv .venv` に置き換えてください。仮想環境の有効化スクリプトを使わないため、PowerShellの実行ポリシーを変更する必要はありません。

## 7. バックアップと更新

バックアップはアプリを停止してから `work_time.db` を別のフォルダへコピーします。このファイルに勤務記録・タスク・時間記録・保存したメモが入っています。

復元する場合もアプリを停止し、現在のDBを別名で保管してからバックアップを `work_time.db` として配置します。空のDBで既存のDBを上書きすると記録を失うため、注意してください。

コードを更新する場合は停止・バックアップ後に次を実行します。

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

その後、`start.bat` で再起動します。競合やローカル変更に関するエラーが出たら、変更を消さずに内容を確認してください。`work_time.db` はGit管理対象外で、GitHubへ送信されません。

## 8. 困ったとき

| 状況 | 対応 |
|---|---|
| Pythonが見つからない | Pythonをインストールし、ターミナルを開き直す。上記のバージョン確認を行う。 |
| パッケージのインストールに失敗 | エラーを確認し、ネットワークや会社のプロキシ設定を確認する。解消後に `start.bat` を再実行する。 |
| ブラウザで接続できない | 起動中の黒い画面にエラーがないか確認し、起動完了後に再読み込みする。URLは `http://127.0.0.1:5000`。 |
| ポート5000が使用中 | このアプリを二重起動していないか確認する。別のアプリが使っている場合は、その管理者に確認する。 |
| フォームが期限切れと表示 | アプリ再起動後などに発生する。ページを再読み込みし、入力し直す。 |
| タスクやメモが消えたように見える | 起動したフォルダが以前と同じか、そのフォルダに使用していた `work_time.db` があるか確認する。 |

このアプリは `127.0.0.1` で待ち受け、使用中のPCからアクセスします。GitHubでコードを公開しても、ローカルのアプリやDBが自動的にインターネットへ公開されることはありません。

## 9. WSL（Ubuntu）で実行

WSLとUbuntuが導入済みの環境で、Ubuntuのターミナルを開いて実行してください。アプリにはPython 3.10以降が必要です。

### 初回セットアップ

```bash
sudo apt update
sudo apt install python3 python3-venv git
python3 --version

cd ~
git clone https://github.com/Ishikawa-8123/work-time-manager.git
cd work-time-manager

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

`python3 --version` が3.10未満の場合は、対応するPythonを用意してから進めてください。すでにUbuntu側にクローン済みなら、`git clone` を繰り返さず、そのフォルダで仮想環境の作成以降を実行します。非公開リポジトリの取得にはアクセス権のあるGitHubアカウントでの認証が必要です。

Windowsで作った `.venv` は流用せず、Ubuntu側のホームディレクトリに別途クローンし、UbuntuのPythonで作成します。仮想環境は移動・コピーするより対象環境で再作成するものです（[Python公式説明](https://docs.python.org/3/library/venv.html)）。`start.bat` はUbuntuでは使いません。

### ブラウザで開く

ターミナルに `Running on http://127.0.0.1:5000` と表示されたら、Windowsのブラウザで http://localhost:5000 を開きます。WSLのアプリへWindowsから `localhost` でアクセスする方法は[Microsoft公式説明](https://learn.microsoft.com/en-us/windows/wsl/networking)を参照してください。

接続できない場合は、Ubuntu内で `curl http://127.0.0.1:5000` を実行してサーバーの応答を確認します（curlがない場合は `sudo apt install curl`）。Ubuntu内では応答するのにWindowsから開けない場合は、WSLのネットワーク設定を確認してください。また、Windows側で同じアプリを起動していないか確認します。

### 停止・2回目以降の起動

停止は、起動中のUbuntuターミナルで **Ctrl + C** を押します。ブラウザを閉じるだけでは停止しません。

次回はUbuntuで次を実行します。

```bash
cd ~/work-time-manager
.venv/bin/python app.py
```

保存先を変えた場合は `cd` のパスを置き換えてください。

### データと更新

DBはUbuntu側のプロジェクト内の `work_time.db` に自動保存されます。別途クローンしたWindows版とは別のDBなので、記録は自動共有されません。バックアップはアプリ停止後にこのDBをコピーします。空のDBのコピーは不要です。

更新は停止・バックアップ後、Ubuntuのプロジェクトフォルダで次を実行し、その後に再起動します。

```bash
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

この手順はコードと公式ドキュメントに基づいています。WSL環境での実動作確認は未実施です。
