# 軽量イメージ（Webのみ。スクレイピングはローカルの update.py で行うため Playwright は含めない）
FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 応募導線ロジックの回帰テスト（AI不使用・ネット不要）→ 通れば最新データ生成
RUN python test_procurement.py && python test_kkj.py && python update.py --fast

ENV FLASK_DEBUG=0
EXPOSE 8000
# $PORT が与えられればそれを使う（Render等）。無ければ 8000。
CMD ["sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --timeout 60"]
