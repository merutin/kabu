# kabu

日本株（最大 5 銘柄）について、**株価 + 配当 + 株主優待** を合わせたトータルリターンの観点から
BUY / HOLD / SELL / WAIT を判断するための個人用ツール。
保有期間は半年〜1 年を基本とし、3 / 6 / 12 ヶ月の複数軸で試算する。

設計の詳細は [docs/DESIGN.md](docs/DESIGN.md)。

## セットアップ

```bash
uv venv && uv pip install -e ".[dev]"
```

## 使い方

1. `config/stocks.yaml` に対象銘柄と予想配当、`config/yutai.yaml` に優待情報、
   `config/portfolio.yaml` に保有状況を記入する（松井証券・GMOクリック証券の画面から転記）。
2. 設定だけで配当・優待の受取予定を確認する:

   ```bash
   .venv/bin/kabu income
   ```

3. 株価を取得して判定し、`reports/latest.md` にレポートを出す:

   ```bash
   .venv/bin/kabu judge
   ```

   ネットワーク無しで動作確認するには `--source demo`（合成データ）。

4. 定期実行は Claude のスケジュールタスク「kabu 週次判定」（毎週土曜 08:44 JST）で行い、
   結果は Claude の通知で届く。スケジュールは claude.ai のスケジュールタスク画面から変更できる。
   Slack / Discord / メールに直接送りたい場合は `config/settings.yaml` の `notify.channels` に
   `webhook` または `email` を加え、環境変数（`KABU_WEBHOOK_URL`、または `KABU_SMTP_*` と
   `KABU_MAIL_TO`）を設定して `--notify` を付ける。`.github/workflows/weekly.yml` は手動起動用。

## テスト

```bash
.venv/bin/python -m pytest -q
```

## 免責

設定ファイルの配当予想・優待情報と過去株価に基づく機械的な試算であり、株価部分のレンジは不確実です。
最終的な投資判断はご自身で行ってください。
