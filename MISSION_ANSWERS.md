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

> Môi trường: Docker 29.10.1 (image store containerd), Compose v5.8.0. Mọi lệnh build chạy từ gốc repo (`-f ...`), theo lưu ý K5. Số liệu dưới đây là kết quả đo trên máy này.

### Exercise 2.1: Đọc `02-docker/develop/Dockerfile`

| # | Câu hỏi | Trả lời | Dòng |
|---|---|---|---|
| 1 | Base image | `python:3.11`: bản Python đầy đủ (Debian + Python + trình biên dịch và nhiều công cụ build). Không phải bản `-slim`. | 8 |
| 2 | Working directory | `/app`. Các lệnh `COPY`, `RUN`, `CMD` phía sau đều chạy trong thư mục này (xác nhận bằng `docker image inspect`: `WorkingDir=/app`). | 11 |
| 3 | Vì sao `COPY requirements.txt` trước | Để tận dụng layer cache của Docker (giải thích bên dưới). | 14, 17, 20 |
| 4 | CMD vs ENTRYPOINT | `CMD` là lệnh mặc định, **bị ghi đè dễ dàng** khi `docker run <image> <lệnh khác>`. `ENTRYPOINT` là chương trình cố định của container; tham số từ `docker run` chỉ được nối thêm vào, muốn thay phải dùng `--entrypoint`. Dockerfile này chỉ có `CMD ["python", "app.py"]`, không có ENTRYPOINT. | 30 |

**Chi tiết câu 3 (layer cache).** Docker build theo từng lệnh, mỗi lệnh là một layer. Layer được dùng lại (cache) nếu lệnh và nội dung file đầu vào không đổi; hễ một layer bị build lại thì **mọi layer phía sau nó đều build lại**. Thứ tự trong file này:

```text
dòng 14  COPY 02-docker/develop/requirements.txt .   <- chỉ đổi khi sửa requirements.txt
dòng 17  RUN pip install -r requirements.txt         <- chậm (tải và cài package), phụ thuộc dòng 14
dòng 20  COPY 02-docker/develop/app.py .             <- đổi mỗi lần sửa code
```

- Sửa `app.py` (xảy ra liên tục): chỉ layer dòng 20 trở đi build lại, `pip install` vẫn dùng cache.
- Sửa `requirements.txt` (hiếm): dòng 14 đổi, nên dòng 17 (`pip install`) và mọi layer sau chạy lại.
- Nếu đảo thứ tự (`COPY . .` rồi mới `pip install`) thì chỉ cần sửa một dòng code là `pip install` chạy lại từ đầu.

Tôi đã kiểm chứng điều này ở Exercise 2.2 (bảng đo cuối mục).

Kiểm chứng CMD bị ghi đè được và image không có ENTRYPOINT:

```text
$ docker image inspect -f 'Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}} WorkingDir={{.Config.WorkingDir}}' my-agent:develop
Entrypoint=null Cmd=["python","app.py"] WorkingDir=/app

$ docker run --rm my-agent:develop python -c "print('CMD da bi ghi de, khong chay app.py')"
CMD da bi ghi de, khong chay app.py
```

### Exercise 2.2: Build và chạy container develop

Build (từ gốc repo, vì Dockerfile `COPY 02-docker/develop/...` và `COPY utils/...` tính từ gốc):

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
```

Chạy (cổng 8000 trống trước khi chạy; kiểm bằng `ss -ltn`):

```bash
docker run -d --name k5-develop -p 8000:8000 my-agent:develop
```

```text
$ docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
NAMES        IMAGE              PORTS                                         STATUS
k5-develop   my-agent:develop   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp   Up 4 seconds
```

Gọi container. Bản develop nhận `question` qua **query string** (`app.py` dòng 21: `async def ask_agent(question: str)`):

```text
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:45:58 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:45:58 GMT
server: uvicorn
content-length: 53
content-type: application/json

{"status":"ok","uptime_seconds":4.0,"container":true}
```

Gửi JSON như `CODE_LAB.md` ghi thì bị 422 (đúng như lưu ý K5):

```text
$ curl -i -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"What is Docker?"}'
HTTP/1.1 422 Unprocessable Entity
content-length: 94
content-type: application/json

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

Log container (`docker logs k5-develop`):

```text
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:38448 - "POST /ask?question=What%20is%20Docker HTTP/1.1" 200 OK
INFO:     172.17.0.1:38464 - "GET /health HTTP/1.1" 200 OK
INFO:     172.17.0.1:38472 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
```

Kích thước image:

```text
$ docker images my-agent:develop
IMAGE              ID             DISK USAGE   CONTENT SIZE   EXTRA
my-agent:develop   c75f5f4b67b0       1.67GB          426MB
```

> Ghi chú về cột: Docker 29 (containerd image store) in hai cột. `DISK USAGE` là kích thước giải nén trên đĩa, trùng với `docker image inspect -f '{{.Size}}'`. `CONTENT SIZE` là kích thước nén của layer, **không** dùng để so sánh ở đây. Docker dùng GB thập phân (1 GB = 1000 MB).

**Layer cache.** Tôi không sửa file nào của bài; tôi chép `Dockerfile`, `requirements.txt`, `app.py`, `utils/mock_llm.py` sang một thư mục tạm (ngoài repo) cùng cấu trúc, rồi build với tag tạm `throwaway-cache:test` (đã xoá tag sau khi đo).

Build lại **không đổi gì** (trong repo, tag `my-agent:develop`): tất cả 6 bước đều `CACHED`.

```text
#9  [4/7] RUN pip install --no-cache-dir -r requirements.txt   CACHED
#10 [5/7] COPY 02-docker/develop/app.py .                      CACHED
#11 [7/7] COPY utils/mock_llm.py utils/                        CACHED
(cả 6 bước [2/7]..[7/7] đều CACHED; build xong sau 0.1s)
```

Bản sao tạm, chỉ thêm một dòng comment vào `app.py`:

```text
#6  [2/7] WORKDIR /app                                          CACHED
#7  [3/7] COPY 02-docker/develop/requirements.txt .             CACHED
#8  [4/7] RUN pip install --no-cache-dir -r requirements.txt    CACHED     <- pip không chạy lại
#9  [5/7] COPY 02-docker/develop/app.py .                       DONE 0.0s  <- build lại
#10 [6/7] RUN mkdir -p utils                                    DONE 0.2s
#11 [7/7] COPY utils/mock_llm.py utils/                         DONE 0.0s
```

Bản sao tạm, thêm một dòng comment vào `requirements.txt`:

```text
#6  [2/7] WORKDIR /app                                          CACHED
#7  [3/7] COPY 02-docker/develop/requirements.txt .             DONE 0.0s  <- file đổi
#8  [4/7] RUN pip install --no-cache-dir -r requirements.txt    DONE 12.1s <- pip chạy lại
#9..#11 các bước sau                                            build lại
```

| Thay đổi | `pip install` | Thời gian bước pip |
|---|---|---|
| Không đổi gì | CACHED | 0 |
| Chỉ sửa `app.py` | CACHED | 0 |
| Sửa `requirements.txt` | chạy lại | 12.1 s |

Đây là lý do `COPY requirements.txt` đứng trước `COPY app.py`.

Sau khi test xong tôi dừng và xoá container: `docker stop k5-develop && docker rm k5-develop` (cổng 8000 đã trống).

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

**Stage 1 (`builder`, dòng 16–29)** — `FROM python:3.11-slim AS builder`:
- Cài `gcc` và `libpq-dev` bằng `apt-get` (dòng 21–24) để biên dịch các package có phần C nếu cần.
- Copy `requirements.txt` (dòng 28) và chạy `pip install --user` (dòng 29), nên package nằm ở `/root/.local`.
- Stage này chỉ để build; **không được dùng để deploy** (comment dòng 14).

**Stage 2 (`runtime`, dòng 36–72)** — `FROM python:3.11-slim AS runtime`: bắt đầu lại từ một image sạch.
- Tạo user không phải root `appuser` (dòng 40) và chuyển sang user đó bằng `USER appuser` (dòng 58).
- `COPY --from=builder /root/.local /home/appuser/.local` (dòng 45): chỉ lấy thư mục package đã cài từ stage 1.
- Copy `main.py` và `utils/mock_llm.py` (dòng 48, 52), `chown` cho `appuser` (dòng 55).
- Đặt `PATH`, `PYTHONPATH` (dòng 61–62), thêm `HEALTHCHECK` (dòng 68–69), chạy `uvicorn ... --workers 2` (dòng 72).

**Vì sao image nhỏ hơn:**
1. Base `python:3.11-slim` thay cho `python:3.11` (số đo bên dưới: đây là phần lớn chênh lệch).
2. Image cuối chỉ lấy kết quả của stage 1 (`/root/.local`). `gcc`, `libpq-dev`, danh sách apt, các layer của stage 1 không có trong image cuối. Tôi đo thêm: build riêng `--target builder` (tag tạm, đã xoá) ra 559,251,150 byte, còn image runtime 239,811,280 byte. Chênh 319,439,870 byte (khoảng 319.4 MB) là phần `gcc`, `libpq-dev` và các layer apt mà stage 1 cần nhưng image cuối không mang theo. Tôi không build biến thể một-stage dùng base slim để so trực tiếp, nên đây là hiệu giữa hai stage của chính Dockerfile này.
3. Không có công cụ build thì bề mặt tấn công nhỏ hơn, và chạy bằng non-root nên an toàn hơn. Tôi kiểm tra:

```text
$ docker run --rm --entrypoint sh my-agent:advanced -c 'id; which gcc || echo "gcc: khong co"; ls /app /app/utils'
uid=999(appuser) gid=999(appuser) groups=999(appuser)
gcc: khong co
/app:
main.py
utils
/app/utils:
mock_llm.py

$ docker run --rm --entrypoint sh my-agent:develop -c 'id; which gcc'
uid=0(root) gid=0(root) groups=0(root)
/usr/bin/gcc
```

**Vai trò của `target: runtime`** (`docker-compose.yml` dòng 26): bảo Compose dừng build ở stage tên `runtime`, nên image của service `agent` là stage 2, không phải stage `builder`. Ở Dockerfile này `runtime` cũng là stage cuối nên nếu bỏ `target` thì kết quả vẫn là stage `runtime`; dòng đó giúp nói rõ ý định và giữ đúng nếu sau này thêm stage khác vào cuối file. Lệnh `docker build` ở dưới không có `--target`, nên cũng lấy stage cuối.

Build (từ gốc repo):

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
```

```text
$ docker images | grep -E 'IMAGE|my-agent'
IMAGE                         ID             DISK USAGE   CONTENT SIZE   EXTRA
my-agent:advanced             b76092f6e4fa        240MB         57.4MB        
my-agent:develop              b836789b51ee       1.67GB          426MB        
```

(ID của `my-agent:develop` khác với lần `docker images` ở 2.2 (`c75f5f4b67b0`): giữa hai lần tôi có build lại image (toàn bộ `CACHED`) và tag lại. Các layer không đổi, `Size` vẫn là 1667771580 byte.)

Số byte chính xác (`docker image inspect -f '{{.Size}}'`):

```text
$ for i in my-agent:develop my-agent:advanced python:3.11 python:3.11-slim; do printf '%s ' $i; docker image inspect -f '{{.Size}}' $i; done
my-agent:develop 1667771580
my-agent:advanced 239811280
python:3.11 1598512337
python:3.11-slim 187070458
```

| Image | Byte | MB (÷10^6) | MiB (÷2^20) |
|---|---|---|---|
| `my-agent:develop` (single-stage, `python:3.11`) | 1,667,771,580 | 1667.8 | 1590.5 |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | 239,811,280 | 239.8 | 228.7 |
| `python:3.11` (base) | 1,598,512,337 | 1598.5 | 1524.5 |
| `python:3.11-slim` (base) | 187,070,458 | 187.1 | 178.4 |

**Phần trăm giảm** = (develop − advanced) / develop × 100:

```text
(1,667,771,580 − 239,811,280) / 1,667,771,580 × 100
= 1,427,960,300 / 1,667,771,580 × 100
= 85.62 %
```

Image advanced nhỏ hơn develop **1,427,960,300 byte (khoảng 1.43 GB), giảm 85.6%**, và nhỏ hơn mục tiêu 500 MB ghi ở đầu Dockerfile (dòng 4). Lưu ý: `INSTRUCTOR_GUIDE.md` nói 50–70%; số đo trên máy này cao hơn khoảng đó, và README của lab ghi "~800 MB / ~160 MB", không khớp số đo của tôi nên tôi không dùng.

**Phần do đổi base image.** Chênh lệch hai base: 1,598,512,337 − 187,070,458 = **1,411,441,879 byte**, bằng 1,411,441,879 / 1,427,960,300 = **98.8%** tổng mức giảm. Phần còn lại 16,518,421 byte (khoảng 16.5 MB, 1.2%) đến từ các khác biệt khác. Theo `docker history`, layer cài package của develop là 53.3 MB còn layer `COPY --from=builder /root/.local` của advanced là 40.8 MB. Khoản chênh này **không** do khác package: hai bản dùng `requirements.txt` giống hệt nhau, và `pip list --format=freeze` trong hai image ra cùng 24 package, cùng phiên bản. Một phần đến từ việc lệnh `pip install` ở develop chạy như root trong `/usr/local`, nên sinh thêm khoảng 5.2 MB file `.pyc` của thư viện chuẩn Python vào layer (vd `/usr/local/lib/python3.11/xml/__pycache__/`). Phần còn lại tôi chưa quy được cho nguyên nhân cụ thể; khoản này chỉ chiếm khoảng 1% mức giảm nên không làm đổi kết luận. Như vậy trong bài này, gần như toàn bộ mức giảm đến từ việc dùng `-slim`; multi-stage giúp ở chỗ giữ `gcc` và `libpq-dev` ngoài image cuối (xem số 319.4 MB ở trên) và cho phép tách quyền, còn `requirements.txt` của bài chỉ gồm package thuần Python (`fastapi`, `uvicorn`) nên về lý thuyết stage builder không bắt buộc.

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

**Services được start (4 service):**

| Service | Image | Vai trò | Cổng publish ra host | Healthcheck | Phụ thuộc |
|---|---|---|---|---|---|
| `nginx` | `nginx:alpine` | Reverse proxy, load balancer, rate limit 10 r/s | `80:80`, `443:443` (dòng 91–93) | không có | `depends_on: agent` (dòng 96–97) |
| `agent` | build từ `02-docker/production/Dockerfile`, `target: runtime` | FastAPI agent, `uvicorn --workers 2`, cổng 8000 | **không publish** (dòng 49: chỉ qua Nginx) | `urllib` gọi `/health`, mỗi 30s (dòng 41–47) | `redis` và `qdrant` phải `service_healthy` (dòng 36–40) |
| `redis` | `redis:7-alpine` | Cache/session/rate limit, `maxmemory 256mb`, `allkeys-lru`, volume `redis_data` | không | `redis-cli ping`, mỗi 10s (dòng 61–65) | không |
| `qdrant` | `qdrant/qdrant:v1.9.0` | Vector database cho RAG, volume `qdrant_data` | không | `bash -c 'echo > /dev/tcp/localhost/6333'`, mỗi 15s (dòng 76–82) | không |

Cả 4 service cùng một network `internal` (driver `bridge`, dòng 112–114). Hai volume: `redis_data`, `qdrant_data` (dòng 105–107).

**Sơ đồ kiến trúc:**

```text
                         HOST (máy chạy Docker)
                  cổng 80 và 443 được publish (0.0.0.0)
                                 |
                                 v
 +--- network "internal" (bridge): k5-day14-docker_internal ------------------------+
 |                                                                                   |
 |    +-------------------------+                                                    |
 |    | nginx  (nginx:alpine)   |  listen 80 (nginx.conf dòng 28; không có listen   |
 |    | reverse proxy + LB      |  443 nên cổng 443 publish nhưng chưa có dịch vụ)   |
 |    | rate limit 10 r/s       |                                                    |
 |    +------------+------------+                                                    |
 |                 |  HTTP agent:8000   (upstream agent_backend -> "agent:8000")      |
 |                 v                                                                 |
 |    +-------------------------+     redis://redis:6379/0      +----------------+   |
 |    | agent (FastAPI)         | ----------------------------> | redis :6379    |   |
 |    | uvicorn, 2 workers      |                               | volume:        |   |
 |    | cổng 8000, KHÔNG publish|                               |  redis_data    |   |
 |    |                         |     http://qdrant:6333        +----------------+   |
 |    |                         | ----------------------------> +----------------+   |
 |    +-------------------------+                               | qdrant :6333   |   |
 |                                                              | volume:        |   |
 |                                                              |  qdrant_data   |   |
 |                                                              +----------------+   |
 +-----------------------------------------------------------------------------------+

 Thứ tự khởi động (depends_on):
   redis (healthy) --+
                     +--> agent (healthy) --> nginx
   qdrant (healthy) -+

 Luồng request:  Client --:80--> nginx --:8000--> agent --(redis:6379, qdrant:6333)
```

Lưu ý quan trọng đã kiểm chứng: `agent` được cấp `REDIS_URL` và `QDRANT_URL` qua biến môi trường (dòng 30–31), nhưng `main.py` của bài này **không import và không kết nối** Redis hay Qdrant (`grep -i "redis\|qdrant" main.py` không ra dòng nào). Hai mũi tên từ agent sang redis/qdrant trong sơ đồ là đường mạng và cấu hình được chuẩn bị, chưa được code dùng. Redis/Qdrant ở đây chỉ chặn thứ tự khởi động của agent qua `depends_on`.

**Trả lời "Services nào được start? Chúng communicate thế nào?"**
- Start 4 service: `nginx`, `agent`, `redis`, `qdrant`. Compose chờ `redis` và `qdrant` healthy rồi mới start `agent`, sau đó mới start `nginx`.
- Các service nằm chung network `internal` nên gọi nhau bằng **tên service** (DNS nội bộ của Docker), không cần IP. Đã kiểm tra trong container `agent` và `nginx`:

```text
$ docker compose -p k5-day14-docker exec agent python -c "import socket;[print(h,socket.gethostbyname(h)) for h in ('redis','qdrant','agent')]"
redis 172.18.0.3
qdrant 172.18.0.2
agent 172.18.0.4

$ docker compose -p k5-day14-docker exec nginx sh -c 'getent hosts agent'
172.18.0.4        agent  agent

$ docker network inspect k5-day14-docker_internal -f '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'
k5-day14-docker-nginx-1 172.18.0.5/16
k5-day14-docker-agent-1 172.18.0.4/16
k5-day14-docker-redis-1 172.18.0.3/16
k5-day14-docker-qdrant-1 172.18.0.2/16
```

- Chỉ Nginx được publish cổng ra host; `agent`, `redis`, `qdrant` chỉ truy cập được từ trong network `internal` (`docker compose ps` cho thấy `8000/tcp`, `6379/tcp`, `6333-6334/tcp` mà không có `0.0.0.0:...->`). Đây là lớp cô lập: client bên ngoài không gọi thẳng vào agent hay database.
- Nginx (`nginx.conf`): `upstream agent_backend { server agent:8000; keepalive 32; }` (dòng 14–22) và `location /` dùng `proxy_pass http://agent_backend` (dòng 42, 48); `/health` được proxy riêng và tắt access log (dòng 60–63). Nginx round-robin giữa các server trong upstream, nhưng upstream hiện chỉ có **một** server `agent:8000` (các dòng `agent_2`, `agent_3` đang là comment, dòng 17–18), và compose không có `deploy.replicas` hay `scale`, nên stack chạy **1 container agent**. Comment đầu file compose ghi "2 replicas" không khớp với file thực tế; thứ có "2" duy nhất là `--workers 2` của uvicorn bên trong container.
- Nginx còn rate limit `10r/s` mỗi IP, `burst=20` (dòng 25, 44), trả 429 khi vượt, và thêm header bảo mật (dòng 34–37).

**Chạy stack** (project name `k5-day14-docker`, dùng cùng tên cho mọi lệnh compose; cổng 80, 443, 8000 trống trước khi chạy; đã `touch 02-docker/production/.env.local`, và `git check-ignore -v` xác nhận file bị bỏ qua bởi `.gitignore:5:.env.*`):

```bash
cd 02-docker/production
touch .env.local
docker compose -p k5-day14-docker up -d --build
docker compose -p k5-day14-docker ps
```

Compose in cảnh báo `the attribute 'version' is obsolete, it will be ignored`: chỉ là cảnh báo, không ảnh hưởng.

```text
$ docker compose -p k5-day14-docker up -d --build   (rút gọn)
 Image k5-day14-docker-agent Built
 Network k5-day14-docker_internal Created
 Container k5-day14-docker-qdrant-1 Healthy
 Container k5-day14-docker-redis-1 Healthy
 Container k5-day14-docker-agent-1 Started
 Container k5-day14-docker-nginx-1 Started

$ docker compose -p k5-day14-docker ps     (sau khoảng 22 giây)
NAME                       IMAGE                   COMMAND                  SERVICE   CREATED          STATUS                    PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   "uvicorn main:app --…"   agent     22 seconds ago   Up 11 seconds (healthy)   8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            "/docker-entrypoint.…"   nginx     22 seconds ago   Up 11 seconds             0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    "./entrypoint.sh"        qdrant    22 seconds ago   Up 22 seconds (healthy)   6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          "docker-entrypoint.s…"   redis     22 seconds ago   Up 22 seconds (healthy)   6379/tcp
```

Ngay sau `up` (khoảng 11 giây), `agent` hiện `health: starting` rồi chuyển `healthy` ở lần kiểm tra sau; qdrant và redis healthy ngay lần đầu. Không có service nào lỗi, không cần sửa gì.

Image mà Compose build cho `agent` (`k5-day14-docker-agent`) có `Size` = 239,811,412 byte, gần bằng `my-agent:advanced` (239,811,280 byte): cùng Dockerfile, cùng stage `runtime`.

**Test qua Nginx (cổng 80).** `main.py` của bản production đọc **JSON body** (`body = await request.json()`, `main.py` dòng 59), khác bản develop (query string). Vì vậy lệnh dùng JSON như `CODE_LAB.md`:

```text
$ curl -s -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Date: Wed, 25 Nov 2026 07:47:56 GMT
Content-Type: application/json
Content-Length: 96
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":10.4,"version":"2.0.0","timestamp":"2026-11-25T07:47:56.823922"}

$ curl -s -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Date: Wed, 25 Nov 2026 07:47:56 GMT
Content-Type: application/json
Content-Length: 103
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Header `Server: nginx` (không có số phiên bản, do `server_tokens off`) và các header `X-Frame-Options`... chứng tỏ request đi qua Nginx, không phải gọi thẳng agent. (`utils/mock_llm.py` chọn ngẫu nhiên một trong 3 câu "default" khi câu hỏi không chứa từ khoá `docker`, `deploy`, `health`; vì vậy nội dung câu trả lời có thể khác giữa các lần gọi, kích thước 95 hoặc 103 byte, và không liên quan đến Docker.)

Các phép thử thêm qua Nginx:

```text
GET  /                                  -> 200 {"app":"AI Agent","version":"2.0.0","environment":"staging"}
GET  /ready                             -> 200 {"ready":true}
POST /ask  body {}                      -> 422 {"detail":"question required"}
POST /ask?question=Hello (không có JSON)-> 500 Internal Server Error
5 lần POST /ask liên tiếp (JSON)        -> 200 200 200 200 200
curl -k https://localhost/health        -> 000 (curl exit 35: không có dịch vụ TLS ở cổng 443)
```

Giải thích dòng 500: nếu gọi bản production kiểu bản develop (query, không có body), `await request.json()` ném `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` (dòng `File "/app/main.py", line 59, in ask_agent` trong log), vì code không bắt lỗi này. Đây là hạn chế của code lab, không phải lỗi stack; tôi không sửa. Cổng 443 được publish nhưng `nginx.conf` chỉ có `listen 80`, nên HTTPS không hoạt động.

**Về load balancing.** Stack này không có nhiều replica `agent` (xem trên), và response không có header cho biết instance nào xử lý, nên không có chứng cứ load balancing giữa các container để trình bày. Bằng chứng thay thế là log `docker compose -p k5-day14-docker logs agent` và `logs nginx`:

```text
$ docker compose -p k5-day14-docker logs agent      (rút gọn)
agent-1  | INFO:     Started parent process [1]
agent-1  | INFO:     Started server process [8]
agent-1  | INFO:     Started server process [9]
agent-1  | {"time":"2026-11-25 07:47:46,561","level":"INFO","msg":"Agent ready"}
agent-1  | INFO:     127.0.0.1:58516 - "GET /health HTTP/1.1" 200 OK        <- healthcheck của Docker (trong container)
agent-1  | INFO:     172.18.0.5:42680 - "GET /health HTTP/1.1" 200 OK       <- từ nginx (172.18.0.5)
agent-1  | {"time":"2026-11-25 07:47:56,830","level":"INFO","msg":"{"event": "request", "q_len": 21}"}
agent-1  | INFO:     172.18.0.5:42680 - "POST /ask HTTP/1.1" 200 OK
...
agent-1  | INFO:     172.18.0.5:47716 - "POST /ask HTTP/1.1" 200 OK         <- 5 lần gọi, đều từ 172.18.0.5
agent-1  | INFO:     172.18.0.5:47716 - "POST /ask HTTP/1.1" 422 Unprocessable Entity

$ docker compose -p k5-day14-docker logs nginx      (rút gọn)
nginx-1  | 172.18.0.1 - - [25/Nov/2026:07:47:56 +0000] "POST /ask HTTP/1.1" 200 103 "-" "curl/7.81.0"
nginx-1  | 172.18.0.1 - - [25/Nov/2026:07:48:07 +0000] "POST /ask HTTP/1.1" 200 103 "-" "curl/7.81.0"
nginx-1  | 172.18.0.1 - - [25/Nov/2026:07:48:08 +0000] "POST /ask HTTP/1.1" 422 30 "-" "curl/7.81.0"
```

Đọc log: client (172.18.0.1, gateway của network) gọi Nginx; agent chỉ thấy request đến từ 172.18.0.5 (địa chỉ container Nginx), đúng với sơ đồ: client không nói chuyện trực tiếp với agent. Log `/health` của Nginx không xuất hiện vì `access_log off` ở `location /health` (dòng 62). Hai dòng `Started server process [8]` và `[9]` là 2 worker uvicorn trong cùng một container, không phải 2 replica.

**Dọn dẹp:** `docker compose -p k5-day14-docker down -v` (xoá container, network và 2 volume); `docker ps -a` trống; cổng 80, 443, 8000 trống. Giữ lại hai image `my-agent:develop` và `my-agent:advanced` để dùng sau.

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
| 2 | Part 2 | Dùng Claude Code: một agent (Claude Sonnet) đọc Dockerfile, compose, nginx.conf; build `my-agent:develop` và `my-agent:advanced` từ gốc repo; chạy container và stack compose `-p k5-day14-docker`; soạn nháp Part 2. Sau đó một agent khác (Claude Opus) review | Câu trả lời 2.1–2.4, kích thước image đo bằng `docker image inspect`, sơ đồ stack, output test qua Nginx; phát hiện compose ghi "2 replicas" nhưng thực tế chỉ có 1 container agent, và agent không hề dùng Redis/Qdrant | Phần review đối chiếu lại toàn bộ số dòng được trích với file gốc; kiểm tra khoản chênh 12.5 MB bằng `pip list` trong hai image (cùng 24 package) và sửa lại đoạn giải thích; làm nhẹ câu giải thích image ID đổi vì đó là phỏng đoán. _(Bạn tự bổ sung: phần nào bạn đã đọc lại, chạy lại hoặc sửa)_ |
