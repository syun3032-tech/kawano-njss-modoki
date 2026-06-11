"""官公需情報ポータルサイト 検索API（中小企業庁・kkj.go.jp）クライアント。

国・地方公共団体・独立行政法人の入札公告を**全国横断で一元集約**した公式・無料API。
HTTP + XML だけ（Playwright不要）なので、デプロイ先でも動く＝最強のデータソース。

API: http://www.kkj.go.jp/api/  （GET, XML, 認証不要）
  Query          検索キーワード（必須。AND/OR等可）
  Category       1=物品 2=工事 3=役務
  LG_Code        都道府県コード(JIS X0401, 2桁, カンマ区切りで複数)
  Procedure_Type 1=一般競争 2=簡易公募型競争 3=簡易公募型指名
  Count          最大件数（既定10, 最大1000）
  CFT_Issue_Date 公告日（期間 YYYY-MM-DD/ 形式）
レスポンス: <Results><SearchResults><SearchResult>... 各案件。添付ファイル=設計図書(仕様書)。
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import db
from regions import region_of

API_URL = "http://www.kkj.go.jp/api/"

# 都道府県名 → JIS X0401 コード（LG_Code 用）。関西を厚くする時に使う。
PREF_CODE = {
    "北海道": "01", "青森県": "02", "岩手県": "03", "宮城県": "04", "秋田県": "05",
    "山形県": "06", "福島県": "07", "茨城県": "08", "栃木県": "09", "群馬県": "10",
    "埼玉県": "11", "千葉県": "12", "東京都": "13", "神奈川県": "14", "新潟県": "15",
    "富山県": "16", "石川県": "17", "福井県": "18", "山梨県": "19", "長野県": "20",
    "岐阜県": "21", "静岡県": "22", "愛知県": "23", "三重県": "24", "滋賀県": "25",
    "京都府": "26", "大阪府": "27", "兵庫県": "28", "奈良県": "29", "和歌山県": "30",
    "鳥取県": "31", "島根県": "32", "岡山県": "33", "広島県": "34", "山口県": "35",
    "徳島県": "36", "香川県": "37", "愛媛県": "38", "高知県": "39", "福岡県": "40",
    "佐賀県": "41", "長崎県": "42", "熊本県": "43", "大分県": "44", "宮崎県": "45",
    "鹿児島県": "46", "沖縄県": "47",
}
KANSAI_CODES = ["25", "26", "27", "28", "29", "30"]  # 滋賀/京都/大阪/兵庫/奈良/和歌山

_PROC = {"1": "一般競争入札", "2": "簡易公募型競争入札", "3": "簡易公募型指名競争入札"}


def _text(el, tag: str) -> str:
    c = el.find(tag)
    return (c.text or "").strip() if c is not None and c.text else ""


def fetch(query: str = "電気工事", category: str = "2",
          lg_codes: list[str] | None = None, count: int = 1000,
          timeout: int = 40) -> list[dict]:
    """官公需APIを叩いて案件の生 dict リストを返す。"""
    params = {"Query": query, "Category": category, "Count": str(count)}
    if lg_codes:
        params["LG_Code"] = ",".join(lg_codes)
    url = API_URL + "?" + urllib.parse.urlencode(params, encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read().decode("utf-8")
    root = ET.fromstring(raw)
    err = root.find("Error")
    if err is not None:
        raise RuntimeError(f"官公需APIエラー: {err.text}")

    out: list[dict] = []
    for sr in root.iter("SearchResult"):
        pref = _text(sr, "PrefectureName")
        # 添付ファイル（設計図書＝仕様書）
        att_uri = ""
        att = sr.find("Attachments")
        if att is not None:
            a = att.find("Attachment")
            if a is not None:
                att_uri = _text(a, "Uri")
        org = _text(sr, "OrganizationName")
        deadline = (_text(sr, "OpeningTendersEvent") or _text(sr, "TenderSubmissionDeadline")
                    or _text(sr, "PeriodEndTime"))[:10]
        out.append({
            "source": "官公需API",
            "external_id": f"KKJ-{_text(sr, 'Key') or _text(sr, 'ResultId')}",
            "title": _text(sr, "ProjectName"),
            "agency": org,
            "agency_type": ("国の機関" if any(k in org for k in ("省", "庁", "局", "国立", "機構"))
                            else "地方公共団体"),
            "region": region_of(pref) or "",
            "prefecture": pref,
            "category": "電気工事",
            "bid_method": _PROC.get(_text(sr, "ProcedureType"), _text(sr, "ProcedureType")),
            "announced_date": _text(sr, "CftIssueDate")[:10],
            "deadline": deadline,
            "detail_url": _text(sr, "ExternalDocumentURI"),
            "spec_status": db.SPEC_AVAILABLE if att_uri else db.SPEC_UNKNOWN,
            "spec_reason": "",
            "spec_url": att_uri,
            "budget": "",
            "winner": "",
            "win_price": "",
        })
    return out


def load(query: str = "電気工事", lg_codes: list[str] | None = None) -> int:
    """官公需APIから取得して DB に投入。件数を返す。"""
    db.init_db()
    rows = fetch(query=query, lg_codes=lg_codes)
    rows = [r for r in rows if r["title"]]
    return db.upsert_cases(rows) if rows else 0


if __name__ == "__main__":
    import sys
    if "--kansai" in sys.argv:
        print(f"官公需API(関西): {load(lg_codes=KANSAI_CODES)} 件")
    else:
        print(f"官公需API(全国): {load()} 件")
