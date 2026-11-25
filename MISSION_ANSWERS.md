# Day 14 Lab — Mission Answers

> Môi trường chạy: Ubuntu 22.04 (`os.name == posix`), Python 3.11.18, Docker 29.10.1 / Compose v5.8.0.
> Mọi output dưới đây được chép từ lệnh tôi đã chạy trên máy, không chép từ README.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | **Hardcode secret**: `OPENAI_API_KEY = "sk-..."` và `DATABASE_URL` chứa mật khẩu `password123` | 17–18 | Push lên GitHub là lộ key/mật khẩu ngay; muốn đổi key phải sửa code và deploy lại; key nằm vĩnh viễn trong lịch sử git |
| 2 | **Ghi secret ra log**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Ai đọc được log (log aggregator, đồng nghiệp, dịch vụ bên thứ ba) đều thấy key. Đã thấy thật trong log khi chạy (xem 1.2) |
| 3 | **`print()` thay cho logging**: không có level, không có timestamp, không có cấu trúc | 33, 34, 38 | Không lọc được theo mức độ, không parse/tìm kiếm được trong hệ thống log tập trung |
| 4 | **Config cứng trong code**: `DEBUG = True`, `MAX_TOKENS = 500`; `import os` nhưng không đọc biến môi trường nào | 7, 21–22 | Không đổi được cấu hình giữa dev/staging/prod nếu không sửa code (vi phạm 12-Factor "Config") |
| 5 | **Không có health check** (`/health`, `/ready`) | 42–43 | Platform không biết agent còn sống hay đã treo để restart; load balancer không biết khi nào nên đưa traffic vào. Đo được: `GET /health` → **404** |
| 6 | **Bind `host="localhost"`** | 51 | Chỉ nhận kết nối từ chính máy đó. Đo được: server lắng nghe `127.0.0.1:8000`, gọi qua IP LAN của máy thì không kết nối được. Trong container cũng vậy: `docker run -p` sẽ không gọi vào được |
| 7 | **Port cố định `8000`** | 52 | Railway/Render cấp port qua biến `PORT`; app không đọc biến này thì platform không route được traffic vào |
| 8 | **`reload=True`** trong lệnh chạy | 53 | Bật thêm process reloader theo dõi file (log có `Started reloader process ... using WatchFiles`): tốn tài nguyên, có thể tự restart giữa chừng khi file thay đổi; chỉ dành cho dev |
| 9 | **Không xử lý shutdown**: không có `lifespan` hay xử lý SIGTERM | cả file | Không có chỗ để đóng kết nối, dọn tài nguyên khi platform tắt/redeploy container |
| 10 | **Không validate input**: `question` rỗng vẫn trả 200 và vẫn gọi LLM | 31 | Tốn tiền LLM cho request vô nghĩa. Đo được: `POST /ask?question=` → **200** |
| 11 | **Không có xác thực** cho `/ask` | 30–31 | Có URL public là ai cũng gọi được, tiêu hết budget LLM |

### Exercise 1.2: Chạy bản develop

Lệnh (theo lưu ý K5: bản develop nhận `question` qua query string):

```bash
cd 01-localhost-vs-production/develop
python app.py
curl -i -X POST "http://localhost:8000/ask?question=Hello"
```

Kết quả:

```text
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Các phép thử thêm:

```text
POST /ask  (JSON body {"question":"Hello"})  → HTTP/1.1 422  {"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required",...}]}
GET  /health                                 → HTTP/1.1 404  {"detail":"Not Found"}
POST /ask?question=   (câu hỏi rỗng)          → HTTP/1.1 200  (vẫn gọi LLM)
Địa chỉ lắng nghe (ss -ltn)                   → 127.0.0.1:8000
Gọi qua IP LAN của máy                        → không kết nối được (curl trả 000)
```

Log của server, **lộ secret ra stdout**:

```text
INFO:     Started reloader process [14931] using WatchFiles
Starting agent on localhost:8000...
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
INFO:     127.0.0.1:58838 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

**Quan sát:** app chạy được, nhưng chưa sẵn sàng cho production: lộ key trong log, chỉ nhận kết nối từ localhost, không có health check, không validate input.

### Exercise 1.3: So sánh develop và production

Chạy bản production (`cp .env.example .env`, file `.env` đã nằm trong `.gitignore`):

```text
Địa chỉ lắng nghe                 → 0.0.0.0:8000
GET  /health                      → 200 {"status":"ok","uptime_seconds":0.2,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:40:25.086868+00:00"}
GET  /ready                       → 200 {"ready":true}
POST /ask {"question":"What is deployment?"} → 200 {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","model":"gpt-4o-mini"}
POST /ask {}                      → 422 {"detail":"question field is required"}
```

Thử graceful shutdown: gửi một request `/ask` rồi gửi `kill -TERM` sau 30 ms, khi request vẫn đang chạy:

```text
in-flight request → HTTP 200 (0.109613s)
process exit code: 0

INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [15069]
```

Request đang chạy vẫn hoàn thành với 200 và process thoát với mã 0.

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| **Config** | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`, dòng 21–22) | Đọc từ env qua `config.py` (`os.getenv("PORT")`, `os.getenv("DEBUG")`…) | Cùng một image/code chạy được ở dev, staging, prod; chỉ đổi biến môi trường. Không phải sửa code mỗi lần đổi môi trường |
| **Secrets** | `OPENAI_API_KEY = "sk-..."` ngay trong code (dòng 17), còn in ra log (dòng 34) | `os.getenv("OPENAI_API_KEY", "")` (config.py dòng 27); log chỉ ghi `question_length`, không ghi secret | Code được commit, chia sẻ, review; secret thì không. Lộ key = mất tiền + phải revoke, và key vẫn còn trong lịch sử git dù xoá file |
| **Host binding** | `host="localhost"` → chỉ nhận `127.0.0.1` | `HOST` mặc định `0.0.0.0` | Trong container hoặc trên cloud, request đi vào qua network interface khác; bind localhost thì không ai gọi vào được |
| **Port** | Cố định `8000` | `int(os.getenv("PORT", "8000"))` | Railway/Render/Cloud Run cấp port qua `PORT`; không đọc thì platform không route được |
| **Health check** | Không có (`/health` → 404) | `GET /health` (liveness) + `GET /ready` (readiness, trả 503 khi chưa sẵn sàng) | Liveness: platform biết khi nào cần restart process bị treo. Readiness: load balancer chỉ gửi traffic vào instance đã sẵn sàng, tránh lỗi lúc khởi động/deploy |
| **Logging** | `print()` thô, có in secret | Định dạng JSON qua `logging` (`{"time":..,"level":..,"msg":..}`), không log secret | Log có cấu trúc thì log aggregator (Loki, Datadog…) parse, lọc, tìm kiếm, tạo alert được. Có level để tắt bớt log debug ở production |
| **Shutdown** | Không xử lý gì | `lifespan` có phần shutdown + đăng ký handler SIGTERM; đo được request đang chạy vẫn trả 200, exit code 0 | Khi platform redeploy/scale down sẽ gửi SIGTERM; tắt êm thì không cắt ngang request của user, kịp đóng kết nối DB/Redis |
| **Debug / reload** | `reload=True` luôn bật | `reload=settings.debug` (chỉ bật khi `DEBUG=true`) | Reloader tốn tài nguyên và có thể restart app bất ngờ; production cần process ổn định |
| **Validate input** | `question` rỗng vẫn 200 | Thiếu `question` → 422 | Chặn request vô nghĩa trước khi tốn tiền gọi LLM; báo lỗi rõ ràng cho client |
| **CORS** | Không cấu hình | `ALLOWED_ORIGINS` đọc từ env | Chỉ cho các frontend được phép gọi API từ trình duyệt |

### Kiểm tra CP1: một anti-pattern bản develop có mà bản production đã sửa

- **Develop, `app.py` dòng 17:** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`, và dòng 34 in luôn key ra log.
- **Production, `config.py` dòng 27:** `openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))`. Key đến từ môi trường, `.env.example` để trống, file `.env` thật bị `.gitignore` chặn, và `app.py` dòng 110–115 chỉ log `question_length` và `client_ip`.

### Quan sát thêm: bản "production" vẫn còn lỗi (bài học cho Part 6)

Khi chạy thật, tôi thấy bản production cũng chưa hoàn hảo:

1. **Log JSON không hiện ra khi `OPENAI_API_KEY` trống.** Lúc import, `config.py` gọi `settings.validate()`, và hàm này gọi `logging.warning(...)` **trước khi** `app.py` gọi `logging.basicConfig(...)`. Root logger vì thế đã được cấu hình mặc định (định dạng `WARNING:root:...`, mức WARNING), nên `basicConfig` sau đó không còn tác dụng và mọi `logger.info(...)` đều bị bỏ. Log thực tế chỉ có:
   ```text
   WARNING:root:OPENAI_API_KEY not set — using mock LLM
   INFO:     Started server process [15069]
   ```
   Khi đặt `OPENAI_API_KEY=dummy-for-test` thì log JSON mới xuất hiện, xác nhận đúng nguyên nhân.
2. **Một số dòng log không phải JSON hợp lệ.** Code `logger.info(json.dumps({...}))` nhét chuỗi JSON vào format `"msg":"%(message)s"` mà không escape dấu ngoặc kép:
   ```text
   {"time":"2026-11-25 14:40:40,130","level":"INFO","msg":"{"event": "startup", "app": "AI Agent", ...}"}
   → json.loads: Expecting ',' delimiter: line 1 column 59
   ```
   Có 3/8 dòng log không parse được. Ở Part 6 tôi tự viết `logging.Formatter` gọi `json.dumps` cho **cả dòng**, không ghép chuỗi.
3. **Body không phải JSON làm app trả 500.** `POST /ask` với body `hello` → `500 Internal Server Error`, log có traceback `JSONDecodeError`. Client không thấy stack trace, nhưng đúng ra phải trả 400/422. Dùng Pydantic model cho body (như khung Part 6) thì FastAPI tự trả 422.
4. **Handler SIGTERM tự viết chạy sau cùng.** Dòng `Received SIGTERM — initiating graceful shutdown` xuất hiện **sau** `Shutdown complete`. Phần tắt êm thực tế là do uvicorn làm; handler tự viết không dùng được để dọn dẹp trước khi tắt. Dọn dẹp nên đặt trong phần shutdown của `lifespan`.

---

## Part 2: Docker

_(chưa làm)_

## Part 3: Cloud Deployment

_(chưa làm, làm sau Part 6 theo CHECKPOINTS)_

## Part 4: API Security

_(chưa làm)_

## Part 5: Scaling & Reliability

_(chưa làm)_

## Part 6: Output `check_production_ready.py`

_(chưa làm)_

---

## AI log

| # | Phần | Hỏi AI gì | AI trả về gì | Tôi tự kiểm tra / sửa thế nào |
|---|---|---|---|---|
| 1 | Part 1 | Dùng Claude Code (Anthropic) đọc `develop/app.py`, `production/app.py`, `config.py`; chạy hai bản app, gọi thử các endpoint và SIGTERM; soạn nháp câu trả lời Part 1 | Danh sách anti-pattern có số dòng, bảng so sánh, và phát hiện 4 lỗi của bản production (log JSON bị nuốt, JSON lồng không hợp lệ, 500 khi body sai, thứ tự handler SIGTERM) | Mọi output trong Part 1 là output thật của lệnh đã chạy (curl, `ss -ltn`, log server). Lỗi log JSON được kiểm chứng bằng cách chạy lại với `OPENAI_API_KEY=dummy-for-test` và parse từng dòng log bằng `json.loads`. _(Bạn tự bổ sung: phần nào bạn đã đọc lại, chạy lại hoặc sửa)_ |
