# Deployment Information

## Public URL

https://agent-production-748cd54a.up.railway.app

## Platform

**Railway**. Agent Part 6 được deploy từ thư mục `06-lab-complete/`. Railway build bằng `06-lab-complete/Dockerfile`, tức đúng image đã đạt `PASS 12/12` với `check_production_ready.py`. Cấu hình nằm trong `06-lab-complete/railway.toml` (builder `DOCKERFILE`, `healthcheckPath = "/health"`).

Project `k5-day14-agent` trên Railway có 2 service:

| Service | Vai trò | Ghi chú |
|---|---|---|
| `agent` | FastAPI agent (uvicorn, 2 worker) | Có domain public; Railway cấp biến `PORT` (đo được: `8080`), `CMD` của Dockerfile lắng nghe theo `${PORT:-8000}` |
| `Redis` | Rate limit + cost guard (state dùng chung) | Thêm bằng `railway add --database redis`; chỉ truy cập qua mạng nội bộ `redis.railway.internal:6379`, không có domain public |

Các lệnh đã dùng (chạy trong `06-lab-complete/`):

```bash
railway login
railway init --name k5-day14-agent
railway add --database redis
railway add --service agent \
  --variables "AGENT_API_KEY=<key ngẫu nhiên, không ghi trong repo>" \
  --variables 'REDIS_URL=${{Redis.REDIS_URL}}' \
  --variables "ENVIRONMENT=production" \
  --variables "LOG_LEVEL=INFO"
railway up --service agent --ci
railway domain --service agent
```

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã đặt trên Railway. Mỗi lệnh chỉ in mã HTTP, nên chụp ảnh không lộ key.

```bash
BASE=https://agent-production-748cd54a.up.railway.app

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đo được (2026-11-25), lần lượt theo 4 lệnh trên:

```text
200
200
401
200
```

### Health Check

```bash
curl https://agent-production-748cd54a.up.railway.app/health
# {"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":27.3}
```

### API Test (with authentication)

```bash
curl -X POST https://agent-production-748cd54a.up.railway.app/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","user_id":null,"usage":{"input_tokens":4,"output_tokens":19},"cost_usd":1.2e-05}
```

### Rate limit (10 request / phút cho mỗi key)

```text
$ for i in $(seq 1 12); do curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" ... -H "X-API-Key: $AGENT_API_KEY" ...; done
200 200 200 200 200 200 200 200 429 429 429 429
$ curl -i ... (request kế tiếp)
HTTP/2 429
retry-after: 40
{"detail":"Rate limit exceeded: 10 requests/minute"}
```

(Có 8 request 200 vì 2 request `/ask` trước đó, ở phần test trên, cũng nằm trong cùng cửa sổ 60 giây: tổng 10 request được phép.)

### Script chấm kèm kiểm tra URL public

```text
$ cd 06-lab-complete && python check_production_ready.py --public-url https://agent-production-748cd54a.up.railway.app
...
     ✅ Public URL: GET https://agent-production-748cd54a.up.railway.app/health → 200
...
  Result: 12/12 tiêu chí đạt · 44/44 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

## Environment Variables Set

Chỉ ghi **tên** biến. Giá trị đặt trên Railway, không nằm trong repo.

| Biến | Đặt ở đâu | Giá trị / nguồn |
|---|---|---|
| `AGENT_API_KEY` | service `agent` | Key ngẫu nhiên 48 ký tự hex (`openssl rand -hex 24`), chỉ lưu trên Railway và trên máy cá nhân, ngoài repo |
| `REDIS_URL` | service `agent` | Biến tham chiếu `${{Redis.REDIS_URL}}`, Railway tự thay bằng địa chỉ nội bộ `redis://...@redis.railway.internal:6379` |
| `ENVIRONMENT` | service `agent` | `production` (tắt `/docs`: `GET /docs` trả `404`) |
| `LOG_LEVEL` | service `agent` | `INFO` |
| `PORT` | Railway tự cấp | `8080` (thấy trong log: `Uvicorn running on http://0.0.0.0:8080`) |

`RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD` không đặt nên dùng giá trị mặc định trong `app/config.py` (10 request/phút, 1.0 USD/ngày, không giới hạn tháng).

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

## Ghi chú

- Lúc deploy, Railway CLI cảnh báo rằng Config as Code (`railway.toml`) đã bị deprecated và vẫn hoạt động tới 2026-12-01, khuyến nghị chuyển sang `.railway/railway.ts`. Bài vẫn giữ `railway.toml`, vì script chấm và rubric yêu cầu file này, và lần deploy này dùng được nó.
- Log trên Railway là JSON. Railway tự tách thành các trường (`event="startup" environment="production" ...`), mỗi worker uvicorn ghi một dòng `startup`.
