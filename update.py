"""データ更新（ローカル実行・ランニングコスト 0 円）。

電気工事入札の最新案件を各無料ソースから取得して SQLite に取り込む。
**有料API・クラウド・サブスク一切なし**。使うのは Playwright（無料）と SQLite（無料）だけ。
ローカルPCで実行するだけなので、実行している間のCPU以外コストはかからない。

使い方:
  python update.py            … 関西サンプル＋PPI近畿(実データ)を取り込み（追記）
  python update.py --reset    … 既存案件をクリアしてから取り込み（関西中心に作り直し）
  python update.py --koukai 茨城県   … 指定自治体の入札情報公開システムも取り込み

定期実行（これも無料）:
  - macOS: launchd か `crontab -e` で1日1回など。例（毎朝7時）:
      0 7 * * * cd /path/to/kawano-njss-modoki && .venv/bin/python update.py --reset >> update.log 2>&1
  - クラウドのcronサービス等は不要。PCが起動している時間に回せばよい。
"""

from __future__ import annotations

import sys

import db
import ppi_scraper
import seed_data


def run(reset: bool = False, koukai_instances: list[str] | None = None) -> None:
    db.init_db()
    if reset:
        removed = db.clear_cases()
        print(f"[reset] 既存案件 {removed} 件をクリア")

    # 1) 関西サンプル（土台）
    n_sample = seed_data.seed()
    print(f"[sample] 関西サンプル {n_sample} 件")

    # 2) PPI（i-ppi.jp）近畿の実データ — 国の機関の電気設備工事
    #    入札公告（現在募集中）と入札の経過（落札者=競合つき）の両方を取り込む。
    for keika, label in [(False, "公告"), (True, "経過(落札者)")]:
        try:
            rows = ppi_scraper.fetch_live(
                keika=keika, kikan="国の機関", district="近畿",
                koji_kbn="電気設備工事", count="100",
                with_winner=keika, max_detail=15,
            )
            norm = [ppi_scraper._normalize(r) for r in rows]
            n = db.upsert_cases(norm) if norm else 0
            print(f"[PPI近畿 {label}] {n} 件")
        except Exception as e:  # noqa: BLE001
            print(f"[PPI近畿 {label}] 取得失敗（スキップ）: {str(e)[:80]}")

    # 3) 自治体の入札情報公開システム（任意・登録があるインスタンスのみ）
    for inst in (koukai_instances or []):
        try:
            import koukai_scraper
            n = koukai_scraper.load(inst, count="100", max_pages=2)
            print(f"[自治体 {inst}] {n} 件")
        except Exception as e:  # noqa: BLE001
            print(f"[自治体 {inst}] 取得失敗（スキップ）: {str(e)[:80]}")

    print(f"=== 更新完了: 案件総数 {db.count_cases()} 件 ===")


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    insts: list[str] = []
    if "--koukai" in sys.argv:
        i = sys.argv.index("--koukai")
        insts = [a for a in sys.argv[i + 1:] if not a.startswith("--")]
    run(reset=reset, koukai_instances=insts)
