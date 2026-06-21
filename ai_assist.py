"""AI応募アシスト（課金プラン・オンデマンド／Gemini API）。

設計方針:
  無料プランは AI を一切呼ばない＝ランニングコスト0。ユーザーが案件詳細で
  「AIで応募準備」をタップしたときだけ Gemini を1回呼び、公告本文・必要書類・
  マイ条件（保有資格/エリア/等級）を読み込んで、

    ・この案件はこういう案件です（要約）
    ・あなたはこの資格を持っているので応募できます（参加資格の適合判定）
    ・この案件向けの必要書類はこれです（具体化）
    ・応募の一歩手前までのやることリスト

  を生成する。結果は DB にキャッシュするので、再タップでは課金されない。

有効化:
  環境変数 GEMINI_API_KEY を設定（ローカルは .env／本番は Render の secret）。
  未設定なら機能は休眠（ボタンは出るが、押すと有効化方法を案内するだけ）。

モデル:
  既定 gemini-2.5-flash（無料枠が大きく高速）。GEMINI_MODEL で上書き可。
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import procurement

_ENV_PATH = Path(__file__).parent / ".env"
_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _load_env() -> None:
    """.env（gitignore済）があれば、未設定のキーだけ os.environ に読み込む。

    本番(Render)は環境変数を直接設定するので .env は無くてよい。ローカル開発用。
    """
    if os.environ.get("GEMINI_API_KEY") or not _ENV_PATH.exists():
        return
    try:
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


def _api_key() -> str:
    _load_env()
    return os.environ.get("GEMINI_API_KEY", "")


def _model() -> str:
    _load_env()
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def is_enabled() -> bool:
    """AI機能が有効か（Geminiのキーが設定されているか）。"""
    return bool(_api_key())


# Gemini の構造化出力スキーマ（responseSchema）。これで型を保証＝壊れにくい。
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "array", "items": {"type": "string"},
            "description": "この案件の要点を3行で（何を・どこが発注・締切や金額の要点）",
        },
        "eligibility": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "description": "〇/△/✕/不明 のいずれか"},
                "reasons": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["verdict", "reasons"],
        },
        "documents": {
            "type": "array", "items": {"type": "string"},
            "description": "この案件で実際に要りそうな提出書類を案件に即して具体化",
        },
        "todo": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["title", "detail"],
            },
            "description": "応募一歩手前までにやることを順番に。最後は『入札書を出す直前』まで。",
        },
        "cautions": {
            "type": "array", "items": {"type": "string"},
            "description": "見落としやすい注意点（締切・資格要件・窓口受領のみ 等）",
        },
    },
    "required": ["summary", "eligibility", "documents", "todo", "cautions"],
}

_SYSTEM = (
    "あなたは日本の公共入札（電気工事系）に精通した入札支援の専門家です。"
    "与えられた案件の公告本文・確定的に算出済みの必要書類・ユーザーの保有資格(マイ条件)を"
    "読み込み、この事業者がこの案件に『応募する一歩手前』まで到達できるよう具体的に支援します。"
    "一般論ではなく、この案件の実態に即して書くこと。"
    "参加資格適合の判定(verdict)は、確証が無ければ△または不明とし、断定しすぎないこと。"
    "必要書類は発注機関により異なるため、最終確認は公告に当たるよう注意書きを添えること。"
    "出力は必ず指定のJSONスキーマに従い、日本語で記述すること。"
)


def _profile_lines(profile: dict | None) -> str:
    p = profile or {}
    parts = []
    if p.get("company"):
        parts.append(f"自社名: {p['company']}")
    if p.get("prefectures"):
        parts.append(f"対応エリア(都道府県): {p['prefectures']}")
    if p.get("categories"):
        parts.append(f"対応業種: {p['categories']}")
    if p.get("grade"):
        parts.append(f"経審等級: {p['grade']}")
    if p.get("quals"):
        parts.append(f"保有資格: {p['quals']}")
    if p.get("budget_max"):
        parts.append(f"予算上限の目安: {p['budget_max']}")
    return "\n".join(parts) if parts else "（マイ条件は未設定）"


def _requirements_lines(req: dict | None) -> str:
    if not req:
        return "（必要書類の確定情報なし）"
    docs = req.get("documents") or []
    req_docs = [d["label"] for d in docs if d.get("required")]
    opt_docs = [d["label"] for d in docs if not d.get("required")]
    lines = [f"区分: {req.get('procurement_kind', '不明')}"]
    if req_docs:
        lines.append("必須(確定): " + " / ".join(req_docs))
    if opt_docs:
        lines.append("任意/確認(確定): " + " / ".join(opt_docs))
    return "\n".join(lines)


def _build_user_text(case: dict, profile: dict | None, req: dict | None) -> str:
    desc = (case.get("description") or "").strip()
    return (
        "# 案件\n"
        f"案件名: {case.get('title', '')}\n"
        f"発注機関: {case.get('agency', '')}（{case.get('agency_type', '')}）\n"
        f"都道府県: {case.get('prefecture', '')} / 地方: {case.get('region', '')}\n"
        f"業種: {case.get('category', '')}\n"
        f"入札方式: {case.get('bid_method', '') or '不明'}\n"
        f"公告日: {case.get('announced_date', '') or '不明'} / 申込締切: {case.get('deadline', '') or '不明'}\n"
        f"予定価格: {case.get('budget', '') or '非公表/不明'}\n\n"
        "# 公告本文（抜粋）\n"
        f"{desc or '（本文なし。公告ページで要確認）'}\n\n"
        "# 確定的に算出済みの必要書類（土台。AIはこれを案件に即して具体化・補強する）\n"
        f"{_requirements_lines(req)}\n\n"
        "# 自社（マイ条件）\n"
        f"{_profile_lines(profile)}\n"
    )


def _call_gemini(user_text: str) -> dict[str, Any]:
    """Gemini に構造化出力で問い合わせ、JSON dict を返す（依存はstdlibのみ）。"""
    key, model = _api_key(), _model()
    url = f"{_API_BASE}/{model}:generateContent?key={key}"
    body = {
        "systemInstruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
            "temperature": 0.3,
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as res:
        data = json.loads(res.read().decode("utf-8"))
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or [{}]
    text = parts[0].get("text", "{}")
    return json.loads(text)


def assist(case: dict, profile: dict | None = None,
           requirements: dict | None = None) -> dict[str, Any]:
    """案件1件に対しオンデマンドで AI 応募アシストを生成して返す。

    返り値: {"enabled": bool, "model": str, ...スキーマの各キー}。
    キー未設定なら {"enabled": False} を返す（呼び出し側で案内表示）。
    """
    if not is_enabled():
        return {"enabled": False}

    if requirements is None:
        try:
            requirements = procurement.application_requirements(case)
        except Exception:  # noqa: BLE001 — 土台が無くてもAIは動かす
            requirements = None

    data = _call_gemini(_build_user_text(case, profile, requirements))
    data["enabled"] = True
    data["model"] = _model()
    return data
