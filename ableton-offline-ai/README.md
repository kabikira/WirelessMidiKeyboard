# Ableton Offline AI

Apple Silicon Mac用の、ローカル資料検索と根拠付き日本語回答のMVPです。

## 起動

このフォルダの `Start.command` をダブルクリックしてください。起動後、ブラウザで
**http://127.0.0.1:8501** を開きます。ターミナルを閉じるか Ctrl+C で終了します。
モデルは最初の質問時に読み込みます。初回は数十秒かかる場合があります。

質問画面はチャット形式です。前の質問と回答を最大6メッセージ分だけ次の質問の補助文脈として渡します。
検索は毎回、現在の質問を中心に行います。「会話をクリア」で画面上の会話文脈を削除できます。

Start.commandはmacOSのsandbox-execで、Pythonとllama.cppの外向き通信を遮断します。
Mac全体のWi-Fi・ファイアウォール設定は変更しません。ブラウザは別プロセスなので、
Wi-Fi OFF試験は別途必要です。アプリ内には外部画像・フォント・クラウド接続を組み込みません。

## 現在の構成

- Qwen3.5-4B Q4_K_M / llama.cpp b10964 / Metal
- Qwen3-Embedding-0.6B Q8_0 / 1024次元 / last pooling / L2正規化
- SQLite FTS5＋NumPyの全文・ベクトル複合検索
- 日本語UI（Streamlit）、引用原文、章・節、資料の版
- 4,096トークン、生成1件、CPU 2スレッド、5分未使用で生成モデルを解放
- EmbeddingもMetalで実行。生成とEmbeddingの計算は直列化
- 外部APIキー不要。クラウドfallback・自動ダウンロードなし

**試験運用です。** 同じLLMによる自己点検も完全ではありません。引用原文を確認してください。
検索の回答抑制閾値0.55は暫定値で、240問の独立評価による校正は未完了です。
メジャー版しか指定されていない資料から、12.3.5など個別の版への適用を断定しません。

## 資料

Live 12 / Live 11の公式HTMLマニュアル、選定したAbleton Knowledge Base、
Cycling '74 Live Object Model / Live API概要をローカル保存しています。
現在は85資料（Live 12が42章、Live 11が37章、補足6資料）、3,671区画を索引に登録済みです。
資料の取得日、対象版、原文ハッシュは各 `.meta.json` に記録しています。
KB記事の対象版が明示されない場合は `unknown` のまま保存します。

PDFはテキストとページ番号を取り込めます。スキャンPDF、文字のないページがあるPDFは
OCR・手動確認が必要として索引の切り替えを止めます。PDFのページ表記は原ファイルから
読み取り、HTMLの架空のページ番号は生成しません。複雑なPDFの見出しは目次情報に依存します。

## CLI

プロジェクトのフォルダで実行してください。

```sh
# 完全ローカル。全文検索だけならモデルを読み込みません。
.venv/bin/python -m app.cli ask 'EchoのDry/Wetとは？' --search-only

# OSによる外向き通信遮断付きの質問応答
/usr/bin/sandbox-exec -f config/offline.sb .venv/bin/python -m app.cli ask 'EchoのDry/Wetとは？'

# ファイルと索引の整合性を検査
.venv/bin/python -m app.cli doctor

# ローカル資料から索引を更新（旧索引は成功まで維持）
/usr/bin/sandbox-exec -f config/offline.sb .venv/bin/python -m app.cli ingest

# 旧snapshotへ戻す
.venv/bin/python -m app.cli restore SNAPSHOT_ID
```

## 資料を追加

UIの「資料」タブからPDF / HTML / Markdown / Textを保存し、索引更新を実行できます。
機材の型番や個人ノートはまだユーザー資料を取り込んでいません。

ファイルを直接置く場合は `knowledge/hardware/` または `knowledge/personal_notes/` に保存し、
同じ名前に `.meta.json` を付けたファイルを配置します。例：`note.md.meta.json`。

```json
{
  "document_id": "my-interface-note",
  "title": "自分のオーディオインターフェース設定",
  "source_type": "personal_notes",
  "language": "ja",
  "live_major": 12,
  "version_scope": "major_only",
  "verified": false
}
```

対象版が不明なら `live_major` は null、`version_scope` は `unknown` にします。
明記された範囲がある場合だけ `live_min` / `live_max` を指定します。
`editions` に許容するEditionの配列を指定できます。
`index: false` の資料は除外します。自動生成した回答は知識ベースへ自動登録しません。

## 必要なときだけオンライン更新

以下は明示的に外部接続する準備・更新コマンドです。Start.commandからは呼ばれません。

```sh
.venv/bin/python -m app.prepare
.venv/bin/python -m app.cli update --major 12
.venv/bin/python -m app.cli update --major 11
.venv/bin/python -m app.seed_sources
```

取得が終わったら、オフラインで `ingest` を実行してください。更新前後の資料は
`updates/staging` と `data/snapshots` に残します。公式から消えた章は自動削除せず、
資料一覧を確認して該当sidecarを `index: false` にしてください。

初回取得時以外はモデル・ライブラリ・資料を自動更新しません。
モデルを差し替える場合はmanifestを検証・更新し、Embedding変更後は全索引を作り直します。

## オフラインで依存環境を復元

Python 3.12がインストール済みの同じMac向けに、固定した50パッケージのwheelを保存しています。
別OS・別Python版にそのまま移植できる配布形式ではありません。

```sh
python3.12 -m app.restore_environment
```

この操作はwheelのハッシュ検証後、`--no-index` でインストールします。
Python本体はMac上の既存インストールを使います。プロジェクトのバックアップには
models / runtime / knowledge / data / offline_bundle を含めてください。
個人ノート、モデル、原資料はGitに登録しない設定です。

## テスト

```sh
.venv/bin/python -m pytest -q
/usr/bin/sandbox-exec -f config/offline.sb .venv/bin/python -m tests.check_os_offline
/usr/bin/sandbox-exec -f config/offline.sb .venv/bin/python -m tests.evaluate_local
```

実装・検証の要約は [実装状況](docs/implementation-status.md)、試験結果は `evaluations/`、
残る受け入れ試験は [受け入れ試験](docs/acceptance.md) を参照してください。
LLMのログは `logs/` に保存します。回答履歴はUIで既定ONです。履歴は `data/history/*.json` に保存され、
質問・回答・引用・検索資料・snapshotに加えて、`improvement_status`（未確認 / 改善に反映済み）、
`improvement_used_at`、`improvement_note`を持ちます。保存しただけでは自動学習に使いません。
内容を確認して「この回答を改善に反映済みとして記録」を押したものだけ、改善済みとして追跡できます。
録音中に索引作成をしないでください。音声に影響が出る場合はモデルを解放して検索のみ使えます。

## ライセンス・適用範囲

モデルはApache 2.0、llama.cppはMITです。実行環境同梱のライセンスを保持します。
第三者資料の権利は発行元に帰属します。個人参照用の保存と再配布は別に扱ってください。
このMVPはAbletonを操作しません。Max for Liveへの操作ブリッジは将来の独立機能です。
