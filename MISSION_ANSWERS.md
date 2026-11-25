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

> Môi trường: Python 3.11.18. Bản develop chạy bằng `.venv`, bản production chạy bằng `.venv-part4` (cần pydantic >= 2.11), Redis 7.4.12 trong Docker (`redis:7-alpine`, cổng 6380).
> Mọi JWT trong bài đã được che (`eyJhbGciOi...<đã che>`), kể cả trường `hint` của `/auth/token` (trường này nhúng 20 ký tự đầu của token). Đường dẫn thư mục home của máy đã được bỏ.
> Output `curl -i` bên dưới đã bỏ các dòng `date:` và `content-length:`; ở một số lệnh tôi bỏ thêm các header `vary` / `x-*` / `referrer-policy` do middleware thêm (chỗ nào cần xem header thì để nguyên đầy đủ, như response 200 ở 4.2 và response 429 ở 4.3). Không sửa giá trị nào.

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

**Trả lời:**

| Câu hỏi | Trả lời | Vị trí |
|---|---|---|
| API key được check ở đâu? | Hàm dependency `verify_api_key` đọc header `X-API-Key` (qua `APIKeyHeader(name="X-API-Key", auto_error=False)`) rồi so với `API_KEY` lấy từ biến môi trường `AGENT_API_KEY`. Route `/ask` gắn nó bằng `_key: str = Depends(verify_api_key)`. `/` và `/health` không có `Depends` nên công khai | `app.py` dòng 35 (đọc env), 36 (khai báo header), 39–54 (hàm check), 70 (`Depends` trên `/ask`) |
| Sai key thì sao? | **Thiếu key → 401** (dòng 44–48). **Có key nhưng sai → 403**, không phải 401 (dòng 49–53). Đã chạy thật, xem output | `app.py` dòng 44–53 |
| Rotate key thế nào? | Key không nằm trong code mà đọc từ env, nên rotate = sinh key mới, đổi biến `AGENT_API_KEY`, restart app (không phải sửa code). Muốn **không downtime**: cho app chấp nhận một *tập* key (key cũ + key mới) trong thời gian chuyển đổi, cấp key mới cho client, đợi client đổi xong rồi **thu hồi key cũ** (bỏ khỏi tập). Code hiện tại chỉ có một key duy nhất (`api_key != API_KEY`), nên đổi key = mọi client dùng key cũ bị 403 ngay | `app.py` dòng 35 và 49 |

Ví dụ hướng sửa để chấp nhận nhiều key (không có trong repo, chỉ minh hoạ): `API_KEYS = set(os.getenv("AGENT_API_KEYS", "").split(","))` rồi `if api_key not in API_KEYS`. Khi so sánh nên dùng `secrets.compare_digest` thay vì `!=`.

**Lệnh và output thật** (`cd 04-api-gateway/develop && AGENT_API_KEY=secret-key-123 ../../.venv/bin/python app.py`):

```text
# 1) Không có key
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
server: uvicorn
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2) Key sai
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
server: uvicorn
content-type: application/json

{"detail":"Invalid API key."}

# 3) Key đúng
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Thử thêm: key đúng nhưng `{"question":""}` → `HTTP/1.1 422 {"detail":"question is required"}`; `GET /health` (không key) → `HTTP/1.1 200 {"status":"ok"}`.

**Vấn đề bảo mật quan sát được trong `develop/app.py`:**

1. **In API key ra stdout khi khởi động** (dòng 91–92). Log khi chạy thật có dòng `API Key: secret-key-123`. Ai đọc được log đều có key, giống lỗi "ghi secret ra log" ở Part 1.
2. **Giá trị mặc định cứng** `"demo-key-change-in-production"` (dòng 35): quên đặt `AGENT_API_KEY` thì app vẫn chạy và ai biết giá trị mặc định này (nó nằm trong repo) đều gọi được.
3. **`reload=True`** (dòng 93): chỉ dành cho dev, tốn tài nguyên và có thể tự restart.
4. So sánh `api_key != API_KEY` (dòng 49) không phải so sánh thời gian hằng số, về lý thuyết cho phép timing attack; nên dùng `secrets.compare_digest`.
5. Một key dùng chung cho mọi client: không biết ai gọi, không rate limit hay tính tiền theo người, và thu hồi key của một client nghĩa là đổi key của tất cả.
6. Dòng in hướng dẫn `curl ... /ask?question=hello` (dòng 92) sai với chính app này: `/ask` là `POST` đọc JSON body (dòng 73), nên dòng gợi ý đó sẽ không chạy.

### Exercise 4.2: JWT authentication (`04-api-gateway/production/auth.py`)

**Luồng JWT (số dòng trong `auth.py`, trừ khi ghi khác):**

1. **Login:** client `POST /auth/token` với `{"username","password"}` (`app.py` dòng 105–118). `authenticate_user` (dòng 70–75) tra `DEMO_USERS`; sai tên/mật khẩu → **401** `Invalid credentials` (dòng 73–74). Đúng thì `app.py` gọi `create_token(username, role)`.
2. **Tạo token:** `create_token` (dòng 35–43) tạo payload gồm `sub` (username), `role`, `iat` (thời điểm phát hành), `exp` (+60 phút, `ACCESS_TOKEN_EXPIRE_MINUTES` dòng 24), rồi ký **HS256** bằng `SECRET_KEY` (`jwt.encode`, dòng 43). `SECRET_KEY` đọc từ env `JWT_SECRET` (dòng 22). Giải mã (không kiểm chữ ký) token vừa lấy được cho thấy:
   ```text
   header : {'alg': 'HS256', 'typ': 'JWT'}
   payload: {'sub': 'student', 'role': 'user', 'iat': 1795593385, 'exp': 1795596985}
   ```
   (`exp - iat = 3600` giây = 60 phút. Payload chỉ được mã hoá base64, **không bí mật**, ai cũng đọc được, nên không để dữ liệu nhạy cảm trong JWT.)
3. **Gửi token:** client đặt header `Authorization: Bearer <token>`. `HTTPBearer(auto_error=False)` (dòng 32) lấy token ra.
4. **Verify:** `verify_token` (dòng 46–67) là dependency của `/ask` (`app.py` dòng 129), `/me/usage`, `/admin/stats`:
   - Không có header → **401** + `WWW-Authenticate: Bearer` (dòng 51–56).
   - `jwt.decode(..., SECRET_KEY, algorithms=[ALGORITHM])` (dòng 59) kiểm tra chữ ký và `exp`. Hết hạn → **401** `Token expired` (dòng 64–65). Token sai chữ ký/sai định dạng → **403** `Invalid token` (dòng 66–67).
   - Hợp lệ thì trả `{"username","role"}` cho endpoint, **không cần tra DB** (stateless).
5. **Phân quyền:** `/admin/stats` chặn `role != "admin"` bằng 403 (`app.py` dòng 174–175).

**Output thật** (`cd 04-api-gateway/production && ../../.venv-part4/bin/python app.py`):

```text
# Không có token → 401
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"What is docker?"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Token rác → 403 (không phải 401)
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer garbage.token.value" -H "Content-Type: application/json" -d '{"question":"What is docker?"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid token."}

# Sai mật khẩu khi login → 401
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"x"}'
HTTP/1.1 401 Unauthorized

{"detail":"Invalid credentials"}

# Lấy token (student / demo123)
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
content-type: application/json

{"access_token":"eyJhbGciOi...<đã che>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJhbGciOi...<đã che>"}

# Token hợp lệ → 200
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"What is docker?"}'
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json
vary: Origin
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"What is docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

Token đã hết hạn (tôi tự ký một token có `exp` trong quá khứ) → `HTTP/1.1 401 Unauthorized  {"detail":"Token expired. Please login again."}`, đúng như dòng 64–65.

**Điểm yếu của `auth.py` và `/auth/token`:**

- **`JWT_SECRET` có giá trị mặc định cứng** `"super-secret-change-in-production-please"` (dòng 22). Quên đặt biến môi trường thì app vẫn chạy với secret nằm công khai trong repo. HS256 là chữ ký đối xứng: ai biết secret thì **tự ký được token bất kỳ**. Tôi đã thử: ký một token với `sub=attacker`, `role=admin` bằng secret mặc định, gửi vào server đang chạy:
  ```text
  $ curl -i http://localhost:8000/admin/stats -H "Authorization: Bearer <token giả, đã che>"
  HTTP/1.1 200 OK
  {"total_users":"N/A (in-memory demo)","global_cost_usd":0.0,"global_budget_usd":10.0}
  ```
  Server nhận token giả là admin thật. Cách sửa: không có default, thiếu `JWT_SECRET` thì app từ chối khởi động; secret dài, ngẫu nhiên, nằm trong secret manager.
- **`DEMO_USERS` hardcode mật khẩu dạng plain text** (dòng 27–30: `demo123`, `teach456`) và so sánh bằng `!=` (dòng 73). Thực tế phải lưu hash (bcrypt/argon2) trong database và so sánh an toàn. Ngoài ra `/auth/token` không giới hạn số lần đoán mật khẩu.
- Ngoài hai điểm trên: trường `hint` trả 20 ký tự đầu của token (`app.py` dòng 117), vô ích và làm lộ một phần token vào log/proxy nếu response bị ghi lại.

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)

| Câu hỏi | Trả lời | Vị trí |
|---|---|---|
| Algorithm nào? | **Sliding window log**: mỗi user có một `deque` chứa timestamp các request. Mỗi lần gọi, bỏ các timestamp cũ hơn `now - window` (`popleft`), rồi nếu số phần tử còn lại `>= max_requests` thì chặn, ngược lại thì `append(now)`. (Docstring dòng 7 ghi "Sliding Window Counter", nhưng code thực tế lưu từng timestamp nên là *log*, không phải *counter*.) | dòng 27, 39–40, 45, 65 |
| Bao nhiêu req/phút? | **User: 10 req/60 s** (`rate_limiter_user`), **Admin: 100 req/60 s** (`rate_limiter_admin`) | dòng 86–87 |
| Admin vượt limit thế nào? | Không "bypass" mà dùng limiter khác: `app.py` dòng 141 chọn `rate_limiter_admin if role == "admin" else rate_limiter_user`, với `role` lấy từ JWT (tài khoản `teacher` có role `admin`). Admin vẫn bị giới hạn, ở mức 100 | `app.py` dòng 141–142 |
| Khi vượt limit? | `HTTPException(429)` kèm header `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Reset`, `Retry-After` (số giây tới khi timestamp cũ nhất rời khỏi cửa sổ). Request bị chặn **không** được ghi vào deque | dòng 45–62 |

Do `check()` được gọi **sau** `verify_token` (dòng 142 so với dòng 129), chỉ request đã xác thực mới bị đếm theo `username`. Request không token bị chặn ở 401 trước nên không tốn quota của ai, nhưng cũng không bị rate limit gì cả (không có giới hạn theo IP).

**Vòng lặp 20 request** (restart app trước đó để counter về 0; token của `student`, 10 req/phút). Lệnh: `for i in $(seq 1 20); do curl -s -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Test '$i'"}' ...; done`, in dòng trạng thái và phần `usage`/`detail` của body:

```text
Request  1: 200  {'requests_remaining': 9, 'budget_remaining_usd': 1.9e-05}
Request  2: 200  {'requests_remaining': 8, 'budget_remaining_usd': 3.5e-05}
Request  3: 200  {'requests_remaining': 7, 'budget_remaining_usd': 5.1e-05}
Request  4: 200  {'requests_remaining': 6, 'budget_remaining_usd': 6.7e-05}
Request  5: 200  {'requests_remaining': 5, 'budget_remaining_usd': 8.6e-05}
Request  6: 200  {'requests_remaining': 4, 'budget_remaining_usd': 0.000104}
Request  7: 200  {'requests_remaining': 3, 'budget_remaining_usd': 0.000125}
Request  8: 200  {'requests_remaining': 2, 'budget_remaining_usd': 0.000142}
Request  9: 200  {'requests_remaining': 1, 'budget_remaining_usd': 0.000163}
Request 10: 200  {'requests_remaining': 0, 'budget_remaining_usd': 0.000181}
Request 11: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 12: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 13: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 14: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 15: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 16: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 17: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 18: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 19: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
Request 20: 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
```

10 request đầu 200, từ request 11 trở đi 429 (tự kiểm tra CP3 đạt). Toàn bộ response của request đầu tiên bị chặn (request 11):

```text
HTTP/1.1 429 Too Many Requests
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795593489
retry-after: 58
content-type: application/json
vary: Origin
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
```

(`x-ratelimit-reset` là Unix timestamp; `retry-after: 58` nghĩa là chờ 58 giây thì request cũ nhất rời khỏi cửa sổ.)

**Tài khoản admin (`teacher` / `teach456`, role `admin`):** 12 request liên tiếp đều `200` (student đã bị chặn ở request 11 với cùng cách gọi). `GET /me/usage` của teacher sau đó:

```text
{"user_id":"teacher","date":"2026-11-25","requests":12,"input_tokens":48,"output_tokens":372,"cost_usd":0.00023,"budget_usd":1.0,"budget_remaining_usd":0.99977,"budget_used_pct":0.0}
```

Tôi chỉ gửi 12 request nên chưa chứng minh được con số 100; con số 100 lấy từ dòng 87 của code. Student gọi `/admin/stats` → `403 {"detail":"Admin only"}`.

**Vì sao rate limiter in-memory là vấn đề khi có nhiều instance hoặc restart:**

- Counter nằm trong dict của **từng process** (`self._windows`, dòng 27). Chạy N instance sau load balancer thì mỗi instance đếm riêng, user thực tế được `10 x N` request/phút, và request tới instance nào là ngẫu nhiên nên limit không còn chính xác.
- **Restart là mất hết counter.** Tôi thấy thật: vòng lặp đầu bị 429 từ request 11; tôi tắt và bật lại app **ngay trong cùng phút đó**, lấy token mới và chạy lại thì 10 request đầu lại được 200. Kẻ tấn công chỉ cần chờ (hoặc gây) một lần restart/redeploy/crash là reset quota. Lưu ý app còn chạy với `reload=True` nên chỉ cần file `.py` đổi là process tự khởi động lại.
- Hướng sửa: để state ở Redis (ví dụ sorted set hoặc `INCR` + `EXPIRE` bằng Lua, giống cách tôi làm ở 4.4), dùng chung cho mọi instance và sống sót qua restart. Đây cũng là lý do Part 5/Part 6 yêu cầu agent stateless, state ở Redis.

### Exercise 4.4: Cost guard

#### (a) `production/cost_guard.py` hiện có hoạt động thế nào

| Thành phần | Chi tiết | Dòng |
|---|---|---|
| Bản ghi theo user, theo ngày | `UsageRecord(user_id, input_tokens, output_tokens, request_count, day)` với `day` mặc định là ngày hiện tại. `_get_record` tạo bản ghi mới (usage = 0) nếu user chưa có hoặc `record.day != today`, nên budget **reset mỗi ngày** | 25–30, 53–58 |
| Tiền tính từ giá token | `total_cost_usd = input_tokens/1000 x $0.00015 + output_tokens/1000 x $0.0006` (giá kiểu GPT-4o-mini) | 20–21, 33–36 |
| Global budget → **503** | Nếu `_global_cost >= global_daily_budget_usd` ($10) thì log CRITICAL và trả 503 cho **mọi** user | 68–73 |
| Per-user budget → **402** | Nếu `record.total_cost_usd >= daily_budget_usd` ($1/user/ngày) thì 402 kèm `used_usd`, `budget_usd` | 76–85 |
| Cảnh báo 80% | Nếu dùng `>= 80%` (`warn_at_pct = 0.8`) thì chỉ `logger.warning`, vẫn cho qua | 88–91 |
| `record_usage` sau khi gọi LLM | `app.py` gọi `check_budget` **trước** LLM (dòng 145) rồi `record_usage` **sau** LLM (dòng 153): cộng token vào bản ghi của user, cộng cost vào `_global_cost` | `cost_guard.py` 93–110, `app.py` 145, 153 |
| Singleton | `cost_guard = CostGuard(daily_budget_usd=1.0, global_daily_budget_usd=10.0)` | 128 |
| **Giới hạn in-memory** | `_records` và `_global_cost` là biến trong process (dòng 49, 51): restart là mất, nhiều instance mỗi cái đếm riêng nên budget thực tế là `N x`, và không ai thấy tổng chi tiêu. Docstring dòng 9 cũng tự nhận "Trong production: lưu trong Redis/DB" | 49–51 |

Các điểm yếu khác tôi thấy khi đọc code (chưa chạy tới ngưỡng nên **đọc code, không phải đo**):

- `check_budget` chỉ so **chi tiêu đã ghi nhận** với budget, không tính chi phí của request sắp chạy; request cuối cùng luôn có thể làm vượt budget. Cách làm là "ghi sổ sau" (post-hoc), nên chỉ chặn được request *sau* khi đã vượt.
- Không có lock giữa `check_budget` và `record_usage`: nhiều request đồng thời cùng qua cổng kiểm tra.
- `_global_today` được gán ở dòng 50 nhưng không dòng nào đọc lại (`grep` chỉ ra đúng một chỗ), nên `_global_cost` **không bao giờ reset** theo ngày dù thông báo 503 nói "Try again tomorrow". Chỉ restart process mới reset.
- `"resets_at": "midnight UTC"` (dòng 83) nhưng `time.strftime("%Y-%m-%d")` dùng giờ local của server.

#### (b) Implement `check_budget(user_id, estimated_cost) -> bool` bằng Redis

File: `04-api-gateway/production/cost_guard_redis.py` (code đầy đủ ở đó), test: `04-api-gateway/production/test_cost_guard_redis.py`.

**Thiết kế:**

- Key `budget:{user_id}:{YYYY-MM}` (tháng UTC). Sang tháng mới là một key mới nên budget tự reset, không cần cron job.
- Giá trị là **số nguyên micro-USD** (1 USD = 1 000 000), cộng bằng `INCRBY`, tránh sai số của float khi cộng nhiều lần.
- **TTL** bằng `EXPIREAT` tuyệt đối: 00:00 UTC ngày đầu tháng sau + 1 ngày đệm. Key tháng cũ tự bị Redis xoá, không phình bộ nhớ.
- Kiểm tra + trừ tiền trong **một Lua script** (`register_script`), chạy nguyên tử trên Redis:

```python
_CHECK_AND_RESERVE_LUA = """
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost  = tonumber(ARGV[1])
local budget = tonumber(ARGV[2])
if spent + cost > budget then
    return 0
end
redis.call('INCRBY', KEYS[1], cost)
redis.call('EXPIREAT', KEYS[1], tonumber(ARGV[3]))
return 1
"""

def check_budget(self, user_id: str, estimated_cost: float) -> bool:
    cost = _to_micro(estimated_cost)          # từ chối âm / NaN / inf bằng ValueError
    ok = self._reserve(keys=[self.key(user_id)],
                       args=[cost, self.budget_micro, self._expire_at()])
    return bool(ok)
```

- **Có giữ chỗ (reserve) chi phí ước tính ngay không?** Có. `True` nghĩa là `estimated_cost` đã được cộng vào chi tiêu tháng, vì phải trừ ngay trong cùng bước nguyên tử thì mới chặn được race. Hệ quả: sau khi gọi LLM xong phải **đối soát** với chi phí thật. Tôi viết `reconcile(user_id, estimated_cost, actual_cost)`, cộng `actual - estimated` (âm thì là hoàn tiền, và không bao giờ cho tổng xuống dưới 0). LLM lỗi thì gọi `reconcile(user, est, 0)` để hoàn toàn bộ. Luồng dự kiến trong `/ask`: ước tính cost theo độ dài prompt + `max_tokens`, `check_budget` (False → trả 402), gọi LLM, `reconcile` với token thật.
- `reconcile` cũng từ chối `estimated_cost` / `actual_cost` âm bằng `ValueError` (nếu không, truyền chi phí thật âm sẽ thành cách "hoàn tiền" để lách budget).
- Hàm module-level `check_budget(user_id, estimated_cost)` đúng chữ ký đề bài, dùng Redis ở `REDIS_URL`.
- Tôi **chưa** nối vào `production/app.py` vì quy định bài không cho sửa file có sẵn; muốn dùng thật thì thay dòng 145 (`cost_guard.check_budget(username)`) và thêm `reconcile` sau dòng 153.

#### (c) Vì sao không dùng nguyên lời giải mẫu: race condition

Lời giải mẫu của CODE_LAB: `current = float(r.get(key) or 0)` → `if current + cost > 10: return False` → `r.incrbyfloat(key, cost)`. Ba bước này là **ba lệnh Redis riêng** nên request khác xen vào được giữa lúc GET và INCRBYFLOAT: nhiều request cùng đọc `current = 9.5`, cùng thấy `9.5 + 0.5 <= 10`, cùng cộng, kết quả là tiêu quá budget (check-then-act). Đây là chính xác loại lỗi mà cost guard sinh ra để chặn. Ngoài ra nó dùng float và `expire(32 ngày)` gia hạn mỗi lần ghi.

**Hai cách sửa và đánh đổi:**

| | Lua script (tôi chọn) | `INCRBYFLOAT` trước, vượt thì `DECRBY` rollback |
|---|---|---|
| Nguyên tử | Có, một round trip, kiểm tra + cộng không bị chen | Từng lệnh nguyên tử, nhưng cả quy trình thì không |
| Số tiền tạm vượt | Không bao giờ vượt, tổng chi tiêu luôn `<= budget` | Giữa INCR và rollback, tổng tạm thời vượt budget; request khác đến lúc đó có thể bị từ chối oan dù sau rollback vẫn còn chỗ |
| Crash giữa chừng | Không có trạng thái nửa vời | Crash trước khi rollback thì phần vượt bị tính vĩnh viễn |
| Độ phức tạp | Phải viết/hiểu Lua, script chạy tuần tự trong Redis (rất ngắn nên không đáng kể); trên Redis Cluster mọi key phải khai báo trong `KEYS` (ở đây chỉ có một key nên ổn) | Đơn giản, không cần Lua |

Phần so sánh hai cách ở bảng này là phân tích lý thuyết, **tôi không đo cách INCR-rồi-rollback**. Tôi chọn Lua vì đầu ra đúng tuyệt đối và dễ chứng minh bằng test.

#### (d) Test thật trên Redis thật

Chạy: `docker run -d --rm --name k5-redis-test -p 127.0.0.1:6380:6379 redis:7-alpine`, rồi `cd 04-api-gateway/production && REDIS_URL=redis://127.0.0.1:6380/0 ../../.venv/bin/python test_cost_guard_redis.py`.

```text
Redis: redis://127.0.0.1:6380/0  ping=True  version=7.4.12

== Chạy tuần tự cho tới khi vượt budget
  cost    kết quả   tổng đã chi sau bước đó
  3.0     True      3.000000
  3.0     True      6.000000
  3.0     True      9.000000
  1.5     False     9.000000
  1.0     True      10.000000
  1e-06   False     10.000000
  PASS

== Key theo tháng + TTL
  key  = budget:ttl-76f09894:2026-11
  GET  = 500000  (micro-USD, = $0.5)
  TTL  = 575793s  (còn 489393s tới đầu tháng sau, +86400s đệm)
  PASS

== Tách theo user / reset khi sang tháng
  tháng này key = budget:a-fe74283c:2026-11
  tháng sau key = budget:a-fe74283c:2026-12
  PASS

== Reconcile với chi phí thật
  PASS

== Từ chối cost không hợp lệ
  PASS

== Đồng thời 50 thread x $0.5 (atomic vs naive)
  [Lua atomic] 50 thread x $0.5: True = 20, đã chi = $10.00
  [Naive GET->INCRBYFLOAT] cùng bài test, 5 lần chạy:
    lần 1: True = 39, đã chi = $19.50  <-- VƯỢT BUDGET
    lần 2: True = 39, đã chi = $19.50  <-- VƯỢT BUDGET
    lần 3: True = 41, đã chi = $20.50  <-- VƯỢT BUDGET
    lần 4: True = 39, đã chi = $19.50  <-- VƯỢT BUDGET
    lần 5: True = 42, đã chi = $21.00  <-- VƯỢT BUDGET
  => naive chi tối đa $21.00 trên budget $10.00
  PASS

6/6 test PASS
```

Đọc kết quả:

- Tuần tự: ba lần $3 qua (tổng $9), $1.5 bị từ chối vì sẽ thành $10.5 và **không bị cộng** (tổng vẫn $9), $1 qua và chạm đúng $10 (so sánh dùng `>` nên chạm ngưỡng vẫn được), sau đó $0.000001 bị từ chối.
- Key có tháng (`2026-11`) và TTL 575793 s, nằm giữa "còn tới đầu tháng sau" (489393 s) và con số đó cộng 1 ngày đệm. Đổi đồng hồ sang tháng 12 cho key khác (`2026-12`), nên user hết budget tháng 11 lại có budget mới.
- Đồng thời 50 thread x $0.5 (budget $10, tức tối đa 20 request): **bản Lua cho đúng 20 `True`, đã chi đúng $10.00**. **Bản naive (lời giải mẫu) cho 39–42 `True`, chi $19.50–$21.00**, vượt budget ở cả 5 lần thử của lần chạy trên. Tôi chạy file test này nhiều lần (cả lúc viết test và lúc review lại trên một Redis riêng): bản Lua lần nào cũng đúng 20 `True` / $10.00; bản naive lần nào cũng vượt budget, số `True` dao động trong khoảng 31–46 tuỳ lịch chạy của thread. Output dán ở trên là lần chạy cuối, trên đúng phiên bản code được nộp.
- `PASS` ở phần naive chỉ có nghĩa là test đã chạy xong và in số; tôi không đặt assert cho nó vì kết quả race không tất định.

Redis container đã được dừng sau khi test (`--rm` nên tự xoá).

### Rate limit và cost guard: vì sao cần cả hai

**Rate limit bảo vệ tốc độ** (số request trong một khoảng thời gian ngắn, ví dụ 10 req/phút): chặn spam, brute force và việc dồn tải làm sập dịch vụ. **Cost guard bảo vệ tiền** (tổng chi tiêu qua một ngày hoặc một tháng). Hai thứ này che cho nhau những lỗ hổng mà chúng không tự bịt được: user vẫn trong rate limit nhưng gửi prompt rất dài hoặc yêu cầu output lớn thì mỗi request tốn nhiều tiền, 10 request/phút có thể đốt hết budget tháng chỉ sau vài giờ mà rate limit không hề phản ứng. Ngược lại, budget còn nhiều không ngăn được một đợt burst hàng nghìn request/giây làm quá tải service (hoặc quá tải provider LLM) trước khi tiền kịp tính. Nên cần cả hai, đặt theo thứ tự: auth, rate limit, cost guard, rồi mới gọi LLM (đúng thứ tự trong `04-api-gateway/README.md`).

### Quan sát: lỗi thật thấy khi chạy

1. **`budget_remaining_usd` trong response `/ask` không phải "budget còn lại" mà là chi phí đã dùng.** `app.py` dòng 160 gán `usage.total_cost_usd`, trong khi `total_cost_usd` là tiền đã tiêu (`cost_guard.py` dòng 33–36). Đối chiếu bằng số liệu thật: sau request đầu tiên, `/ask` trả `"budget_remaining_usd":1.9e-05`, trong khi `GET /me/usage` ngay sau đó cho `"cost_usd":1.9e-05` và `"budget_remaining_usd":0.999981` (budget $1). Con số `1.9e-05` là chi phí đã dùng, nên tên trường sai và số này **tăng** theo từng request (1.9e-05 → 3.5e-05 → ... → 0.000181 ở request 10 trong vòng lặp) thay vì giảm. Cách sửa: trả `cost_guard.get_usage(username)["budget_remaining_usd"]` hoặc `daily_budget_usd - usage.total_cost_usd`.
2. **Chỉ response 429 mới có `X-RateLimit-*`.** Response 200 của `/ask` không có header nào (xem output 4.2), nên client không biết còn bao nhiêu quota trước khi bị chặn; thông tin chỉ nằm ở `usage.requests_remaining` trong body.
3. **Rate limiter chỉ nhớ trong process.** Đã thấy: restart trong cùng phút là quota về lại 10 (xem 4.3). Ngược lại JWT là stateless nên token lấy từ lần chạy trước vẫn dùng được sau khi restart (token `student` của lần chạy trước vẫn qua được bước xác thực ở lần chạy sau, kết quả sau đó là 429 của rate limit chứ không phải 401/403).
4. **Auth: 401 và 403 không thống nhất.** Thiếu credential → 401, sai key/sai token → 403 (cả bản develop lẫn production); theo chuẩn HTTP thì credential sai/không hợp lệ thường là 401. README ở thư mục `04-api-gateway` viết "401 nếu fail" nên dễ gây hiểu nhầm.
5. **Bài học bảo mật tổng hợp:** `JWT_SECRET` mặc định cho phép giả token admin (đã chứng minh ở 4.2), key in ra log, và cả hai bộ đếm (rate limit, cost guard) đều in-memory nên mất khi restart. Cả ba đều phải sửa trước khi lên production (xem Part 6).

## Part 5: Scaling & Reliability

> Theo hướng dẫn K5 (README mục 7, CHECKPOINTS dòng 8), bài này **chạy và giải thích code mẫu có sẵn** trong `05-scaling-reliability/`, không viết lại. Phần "implement" của 5.1–5.3 trong `CODE_LAB.md` được trả lời bằng cách chỉ ra đoạn code đã có (kèm số dòng) và chứng minh nó chạy bằng output thật.
> Số dòng tính theo từng file riêng (`develop/app.py`, `production/app.py`, ...). Stack Docker dùng project `k5-day14-scaling`, cổng 8080, endpoint `POST /chat`. Python 3.11.18, uvicorn 0.30.0, FastAPI 0.115.0.

### Exercise 5.1: Health check và readiness (`develop/app.py`)

Chạy: `cd 05-scaling-reliability/develop && python app.py` (cổng 8000).

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"status":"ok","uptime_seconds":1.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:09:42.527549+00:00","checks":{"memory":{"status":"ok","used_percent":39.5}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"ready":true,"in_flight_requests":1}
```

**Giải thích từng trường `/health` (liveness, dòng 104–144):**

| Trường | Dòng | Ý nghĩa |
|---|---|---|
| `status` | 133–135 | `"ok"` nếu mọi check con là `ok`, ngược lại `"degraded"` |
| `uptime_seconds` | 117, 139 | Số giây từ lúc process chạy (`START_TIME`, dòng 36) |
| `version` | 140 | Chuỗi cố định `"1.0.0"` để biết đang chạy bản nào |
| `environment` | 141 | Đọc biến môi trường `ENVIRONMENT`, mặc định `development` |
| `timestamp` | 142 | Giờ UTC lúc trả lời |
| `checks.memory` | 123–131 | Dùng `psutil.virtual_memory()`; `degraded` nếu RAM >= 90% (dòng 127). Không có psutil thì trả `ok` kèm ghi chú (dòng 130–131) |

**Giải thích `/ready` (readiness, dòng 147–168):** nếu `_is_ready` là `False` thì ném `HTTPException(503)` (dòng 160–164), ngược lại trả `{"ready": true, "in_flight_requests": N}` (dòng 165–168). `_is_ready` được `lifespan` bật `True` ở dòng 49 (sau khi "load model" xong) và tắt `False` ở dòng 55 (đầu phần shutdown). Con số `in_flight_requests: 1` ở trên là **chính request `/ready` đang gọi**, vì middleware `track_requests` (dòng 72–81) tăng bộ đếm cho mọi request kể cả health check.

**Liveness khác readiness ở đâu:**

| | `/health` (liveness) | `/ready` (readiness) |
|---|---|---|
| Câu hỏi | "Process còn sống, còn trả lời được không?" | "Instance này có nên nhận traffic **ngay bây giờ** không?" |
| Platform làm gì khi fail | **Restart** container/process | **Ngừng route traffic** vào instance (không restart), có sẵn lại thì route tiếp |
| Khi nào trả non-200 | Process treo/chết/timeout. Bản develop gần như luôn 200 (kể cả `degraded`) | **503** khi đang khởi động, đang shutdown, hoặc dependency (DB/Redis) chưa kết nối (docstring dòng 155–158) |
| Nếu check sai | Check quá nặng (gọi DB) thì DB chậm làm platform restart oan agent đang ổn | Check quá nhẹ thì instance chưa sẵn sàng vẫn nhận request và trả lỗi |

Hai ví dụ thật trong lab này nằm ở 5.4: khi Redis chết, `/health` vẫn 200 (`degraded`, không restart container) còn `/ready` trả 503 (ngừng nhận traffic).

**Lưu ý đo được về 503 của `/ready` (bản develop):**
- Lúc khởi động: tôi gọi `/ready` mỗi 10 ms ngay từ trước khi mở cổng. Kết quả: 41 lần đầu là `000` (connection refused), rồi lần thứ 42 là `200`. Uvicorn chỉ mở cổng sau khi lifespan startup xong, nên cờ `_is_ready=False` ở giai đoạn startup **không thể thấy được qua HTTP** trong app này.
- Lúc shutdown: xem 5.2, request tới sau SIGTERM không nhận được 503 mà bị ngắt kết nối.
- Tức là mã 503 chỉ thực sự xuất hiện khi dependency lỗi (trường hợp Redis ở `production/app.py`, xem 5.4).

### Exercise 5.2: Graceful shutdown (`develop/app.py`)

**Cách làm:** khởi động app nền, lấy PID bằng `$!`, gửi `POST /ask?question=Long%20task` nền, gửi `kill -TERM $PID` sau 30 ms.

```text
server PID=27167
kill -TERM at 15:10:13.687158943
process exit code: 0
in-flight request: HTTP 200 in 3.007020s
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Log đầy đủ của app (từ lúc nhận request đến lúc thoát):

```text
INFO:     127.0.0.1:54976 - "GET /health HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     127.0.0.1:54990 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 15:10:16,766 INFO 🔄 Graceful shutdown initiated...
2026-11-25 15:10:16,766 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [27167]
2026-11-25 15:10:16,767 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết quả:** request đang chạy **không bị cắt**: HTTP 200 sau 3.007 s (mock LLM ngủ 3 s), process thoát với mã 0.

**Luồng shutdown trong code (và đối chiếu với log):**

| Bước | Code | Vai trò |
|---|---|---|
| 1 | `signal.signal(SIGTERM/SIGINT, handle_sigterm)` dòng 186–187; `handle_sigterm` dòng 175–183 | Chỉ **ghi log**, không tự tắt gì |
| 2 | `uvicorn.run(..., timeout_graceful_shutdown=30)` dòng 193–198 | Uvicorn chờ tối đa 30 s cho request đang chạy, quá hạn thì huỷ task |
| 3 | `track_requests` middleware dòng 72–81 | `_in_flight_requests += 1` khi vào, `-= 1` ở `finally` khi ra |
| 4 | `lifespan` sau `yield`, dòng 55 | `_is_ready = False` |
| 5 | Vòng chờ dòng 61–64 | `while _in_flight_requests > 0 and elapsed < 30: log "Waiting for N in-flight requests..."; time.sleep(1)` |
| 6 | Dòng 66 | Log `Shutdown complete`, lifespan kết thúc, process thoát |

**Log thật cho thấy gì (không giả định):**

1. **Handler SIGTERM tự viết chạy sau cùng, y hệt Part 1.** Dòng `Received signal 15` nằm **sau** `Finished server process`. Nguyên nhân (đã đọc code uvicorn 0.30.0, `uvicorn/server.py` dòng 311–328): trong `Server.serve()`, `capture_signals()` thay handler SIGTERM/SIGINT bằng `handle_exit` của uvicorn (dòng 318); khi serve xong nó khôi phục handler cũ (dòng 322–323) rồi `signal.raise_signal(...)` (dòng 327–328) để bắn lại signal đã bắt, lúc đó `handle_sigterm` của app mới chạy. Vậy `handle_sigterm` không dùng để dọn dẹp được; việc dọn dẹp phải nằm ở `lifespan` sau `yield`.
2. **Vòng "Waiting for N in-flight requests" không chạy lần nào.** Trong log không có dòng `Waiting for ... in-flight requests...` nào. Lý do (đọc `uvicorn/server.py` dòng 257–290): `Server.shutdown()` đóng listener, rồi `_wait_tasks_to_complete()` (có `timeout_graceful_shutdown`, dòng 272–279) chờ mọi connection/task xong, **sau đó mới** gọi `lifespan.shutdown()` (dòng 289–290). Log khớp: dòng access `POST /ask ... 200 OK` xuất hiện **trước** `Waiting for application shutdown`. Lúc `lifespan` chạy phần shutdown thì `_in_flight_requests` đã bằng 0. Việc chờ thật sự do uvicorn làm, vòng chờ trong `lifespan` là dự phòng không có tác dụng trong tình huống thường (kể cả khi vượt 30 s, uvicorn huỷ task trước nên bộ đếm cũng về 0 qua `finally`; điểm này là suy luận từ code, tôi không chạy ca quá 30 s).
3. **Request đến sau SIGTERM không nhận được 503.** Tôi gửi thêm `GET /ready` ngay sau `kill -TERM`: kết quả `HTTP 000`, curl exit code 56 (kết nối bị reset), sau 2.97 s. Tức là `_is_ready=False` (dòng 55) chỉ có hiệu lực **sau khi uvicorn đã đóng cổng**, nên load balancer không thể thấy 503 từ `/ready` trong lúc shutdown. Thực tế việc "ngừng nhận traffic mới" là do uvicorn đóng listener (dòng 261–262), không phải do cờ `_is_ready`. Trong môi trường có load balancer (Nginx), nhiều khả năng request bị reset kiểu này được thử lại sang instance khác nhờ `proxy_next_upstream error` (xem 5.4; đây là suy luận, tôi không đo ca SIGTERM qua Nginx).

**Điểm đáng ngờ khi đọc code (không đo):**
- `time.sleep(1)` ở dòng 63 là lệnh chặn trong hàm `async` (lifespan), sẽ khoá event loop mỗi vòng 1 s. Vì vòng này gần như không chạy nên ít hậu quả.
- Handler `/ask` là `async def` (dòng 94) nhưng gọi `ask()` dùng `time.sleep(3)` (mock LLM): **chặn cả event loop** trong 3 s. **Đã đo được hậu quả:** gọi `/ready` khi `/ask` đang chạy mất **2.527 s** mới có trả lời (`{"ready":true,"in_flight_requests":1} [200 2.527190s]`). Một liveness probe có timeout ngắn hơn (ví dụ 1–2 s) sẽ fail trong lúc agent đang xử lý một request chậm, và platform có thể restart oan. Sửa: dùng `def` thường (chạy trong threadpool) hoặc `await asyncio.sleep`/client LLM bất đồng bộ.
- Docstring/README nói "SIGTERM → handle_sigterm → uvicorn trigger lifespan shutdown": thứ tự thật ngược lại (xem điểm 1).

### Exercise 5.3: Stateless design (`production/app.py`)

**State lưu trong Redis thế nào:**

| Chức năng | Code | Chi tiết |
|---|---|---|
| Kết nối | dòng 34–41 | `redis.from_url(REDIS_URL)` rồi `_redis.ping()`; thành công thì `USE_REDIS = True` |
| Key | dòng 63, 71 | `session:{session_id}`, giá trị là **một chuỗi JSON** `{"history": [...]}` (kiểu `string`, không phải list/hash) |
| TTL | dòng 59, 63 | `save_session(..., ttl_seconds=3600)` gọi `_redis.setex(key, 3600, json)`: mỗi lần ghi **đặt lại** TTL 1 giờ, session không hoạt động 1 giờ thì hết hạn |
| Đọc | dòng 68–73 | `_redis.get(key)` rồi `json.loads`; không có thì trả `{}` |
| Giới hạn history | dòng 85–87 | `if len(history) > 20: history = history[-20:]`, giữ 20 message cuối (10 lượt) |
| Ghi message | dòng 76–90 | `append_to_history`: load session, append `{role, content, timestamp}`, cắt còn 20, save lại |
| Dùng trong `/chat` | dòng 140, 148 | Ghi message `user` trước khi gọi LLM, ghi `assistant` sau khi có answer |
| Xoá | dòng 176–177 | `DELETE /chat/{id}` gọi `_redis.delete(key)` |

Đã đo giới hạn 20: gửi 15 lượt vào `failover-session-1` thì history còn **đúng 20 message** và chỉ còn nội dung `turn 6 ... turn 15` (turn 1–5 đã bị cắt).

**Fallback in-memory (dòng 34–45, 59–65, 68–73, 176–179) chính là anti-pattern:** nếu `ping()` lỗi thì app im lặng chuyển sang `_memory_store: dict` (dòng 44), tức là biến toàn cục **trong RAM của từng process**. Khi chạy một instance thì hoạt động bình thường, nhưng khi scale ra N instance thì mỗi instance có một dict riêng. Hơn nữa nó **không báo lỗi**: `/health` vẫn `ok` (dòng 197) và `/ready` vẫn 200 (dòng 208–215), chỉ có trường `"storage": "in-memory"` để lộ ra.

**Chứng minh state trong RAM hỏng khi có nhiều instance.** Chạy 2 instance cục bộ **không có Redis** (`REDIS_URL=redis://127.0.0.1:1/0` để `ping()` lỗi), cổng 8001 và 8002, lệnh `python -m uvicorn app:app --port 800X` (không dùng `python app.py` vì dòng 220 có `reload=True`):

```text
$ curl -X POST localhost:8001/chat -d '{"question":"What is Docker?","session_id":"demo-session-1"}'      # lượt 1 -> 8001
HTTP/1.1 200 OK
{"session_id":"demo-session-1","question":"What is Docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","turn":2,"served_by":"local-8001","storage":"in-memory"}

$ curl -X POST localhost:8002/chat -d '{"question":"Tell me more","session_id":"demo-session-1"}'         # lượt 2, CÙNG session -> 8002
HTTP/1.1 200 OK
{"session_id":"demo-session-1","question":"Tell me more","answer":"Đây là câu trả lời từ AI agent (mock). ...","turn":2,"served_by":"local-8002","storage":"in-memory"}

GET :8001/chat/demo-session-1/history  -> count 2:  user "What is Docker?"  | assistant "Container là cách đóng gói..."
GET :8002/chat/demo-session-1/history  -> count 2:  user "Tell me more"     | assistant "Đây là câu trả lời từ AI..."     <- KHÔNG có lượt 1

# session chỉ từng gửi tới 8001, hỏi history ở 8002:
GET :8002/chat/only-1/history -> HTTP/1.1 404 Not Found   {"detail":"Session only-1 not found or expired"}
```

Log khởi động của mỗi instance: `⚠️  Redis not available — using in-memory store (not scalable!)`. Cả hai instance đã được dừng bằng PID sau thử nghiệm.

Kết luận: lượt 2 tới instance khác thì **mất toàn bộ ngữ cảnh** của lượt 1 (history của 8002 chỉ có đúng 2 message của lượt 2, hoặc 404 nếu session chưa từng tới instance đó). User không nhận được lỗi nào, chỉ thấy agent "quên".

**Chứng minh state thật sự nằm trong Redis (stack Docker 5.4 đang chạy):**

```text
$ docker compose -p k5-day14-scaling exec redis redis-cli --scan --pattern 'session:*'
session:e6328872-e85c-4dd2-ab20-15e136eaa8de
session:b6edbf28-0454-4372-972b-5cedb4982970
session:644c2468-7447-4459-9dfc-d40033e46c6c
session:8ef47524-a317-4258-a470-b185e547f871
session:b44c354e-ef6c-408e-9854-3e04d904687b      <- session của test_stateless.py (5.5)
... (tổng 11 key: 10 session của vòng lặp 10 request + 1 của test_stateless.py)

$ redis-cli TTL session:b44c354e-ef6c-408e-9854-3e04d904687b
3593
$ redis-cli TYPE session:b44c354e-...
string
$ redis-cli GET session:b44c354e-... | cut -c1-200
{"history": [{"role": "user", "content": "What is Docker?", "timestamp": "2026-11-25T08:12:24.385639+00:00"}, {"role": "assistant", "content": "Container là cách ...
```

TTL 3593 s (gần 3600 s) khớp `setex(..., 3600)`; key có 1 trường `history` với 10 phần tử.

### Exercise 5.4: Load balancing (Nginx + 3 agent + Redis)

**Chạy stack:** `touch .env.local` (file đã bị `.gitignore` bỏ qua: `git check-ignore -v` in ra `.gitignore:5:.env.*`), rồi:

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
NAME                       IMAGE                    SERVICE   STATUS                   PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   agent     Up 8 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   agent     Up 8 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   agent     Up 8 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             nginx     Up 8 seconds             0.0.0.0:8080->80/tcp, [::]:8080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           redis     Up 19 seconds (healthy)  6379/tcp
```

Có 3 agent + 1 nginx + 1 redis. `docker-compose.yml` dòng 41–42 đã khai báo sẵn `deploy: replicas: 3`, nên `--scale agent=3` chỉ trùng với số đó (cờ `--scale` có tác dụng ghi đè nếu muốn số khác). Compose không đặt `INSTANCE_ID` nên mỗi container tự sinh ID ngẫu nhiên lúc khởi động (dòng 52 của `app.py`). Khớp IP với ID:

| Container | IP (bridge `agent_net`) | `served_by` |
|---|---|---|
| `k5-day14-scaling-agent-1` | 172.18.0.3 | `instance-85d8e5` |
| `k5-day14-scaling-agent-2` | 172.18.0.4 | `instance-effe7a` |
| `k5-day14-scaling-agent-3` | 172.18.0.5 | `instance-2d5f78` |

**10 request `POST /chat` (mỗi request một session mới), qua cổng 8080:**

```text
req 1  | 200 | X-Served-By: 172.18.0.5:8000 | served_by: instance-2d5f78
req 2  | 200 | X-Served-By: 172.18.0.4:8000 | served_by: instance-effe7a
req 3  | 200 | X-Served-By: 172.18.0.3:8000 | served_by: instance-85d8e5
req 4  | 200 | X-Served-By: 172.18.0.5:8000 | served_by: instance-2d5f78
req 5  | 200 | X-Served-By: 172.18.0.4:8000 | served_by: instance-effe7a
req 6  | 200 | X-Served-By: 172.18.0.3:8000 | served_by: instance-85d8e5
req 7  | 200 | X-Served-By: 172.18.0.5:8000 | served_by: instance-2d5f78
req 8  | 200 | X-Served-By: 172.18.0.4:8000 | served_by: instance-effe7a
req 9  | 200 | X-Served-By: 172.18.0.3:8000 | served_by: instance-85d8e5
req 10 | 200 | X-Served-By: 172.18.0.5:8000 | served_by: instance-2d5f78
```

| Instance | Số request (header `X-Served-By`) | Số request (`served_by` trong body) |
|---|---:|---:|
| agent-3 (`172.18.0.5`, `instance-2d5f78`) | 4 | 4 |
| agent-2 (`172.18.0.4`, `instance-effe7a`) | 3 | 3 |
| agent-1 (`172.18.0.3`, `instance-85d8e5`) | 3 | 3 |

Hai cách đếm khớp nhau và thứ tự quay vòng đều (.5 → .4 → .3 → .5 ...) đúng round-robin mặc định của Nginx. Header do `nginx.conf` dòng 17 (`add_header X-Served-By $upstream_addr always`) thêm vào.

`docker compose -p k5-day14-scaling logs agent` (lọc `POST /chat`, gộp theo container; `172.18.0.6` là IP của Nginx), đếm đúng 10 dòng: agent-3 có 4, agent-2 có 3, agent-1 có 3:

```text
agent-3  | INFO:     172.18.0.6:35200 - "POST /chat HTTP/1.1" 200 OK     (x4, cùng cổng nguồn 35200)
agent-2  | INFO:     172.18.0.6:48270 - "POST /chat HTTP/1.1" 200 OK     (x3)
agent-1  | INFO:     172.18.0.6:43084 - "POST /chat HTTP/1.1" 200 OK     (x3)
```

**Failover: dừng 1 instance giữa chừng, cùng một session.** Session `failover-session-1`, 3 lượt trước khi dừng, rồi `docker stop k5-day14-scaling-agent-1` (agent-1 = `instance-85d8e5`, 172.18.0.3), rồi gửi tiếp:

```text
pre-1  | 200 0.115s | X-Served-By: 172.18.0.4:8000 | instance-effe7a
pre-2  | 200 0.148s | X-Served-By: 172.18.0.3:8000 | instance-85d8e5
pre-3  | 200 0.119s | X-Served-By: 172.18.0.5:8000 | instance-2d5f78
$ docker stop k5-day14-scaling-agent-1        # 15:12:41
post-4 | 200  0.133s | X-Served-By: 172.18.0.4:8000            | instance-effe7a
post-5 | 200 39.250s | X-Served-By: 172.18.0.3:8000,... | instance-2d5f78   <- thử instance chết (.3), rồi chuyển sang instance khác
                                                              (bộ lọc header của tôi cắt mất phần sau dấu phẩy; body cho thấy instance phục vụ là 2d5f78)
post-6 | 200  0.147s | X-Served-By: 172.18.0.4:8000            | instance-effe7a
post-7 | 200  0.123s | X-Served-By: 172.18.0.5:8000            | instance-2d5f78
post-8 | 200  0.144s | X-Served-By: 172.18.0.4:8000            | instance-effe7a
post-9 | 200  0.112s | X-Served-By: 172.18.0.5:8000            | instance-2d5f78
history: count 18  (user: turn 1 ... turn 9, đủ 9 lượt x 2 message, không mất lượt nào)
```

Sau khi nghỉ 12 s (qua `fail_timeout` mặc định 10 s của Nginx), gửi tiếp 6 request:

```text
post-10 | 200 0.145s | 172.18.0.5:8000
post-11 | 200 0.132s | 172.18.0.4:8000
post-12 | 200 3.203s | X-Served-By: 172.18.0.3:8000, 172.18.0.5:8000      <- lại thử instance chết
post-13 | 200 0.154s | 172.18.0.4:8000
post-14 | 200 0.113s | 172.18.0.5:8000
post-15 | 200 0.120s | 172.18.0.4:8000
```

Log lỗi của Nginx:

```text
[error] connect() failed (113: Host is unreachable) while connecting to upstream, ... upstream: "http://172.18.0.3:8000/chat"   (08:13:21)
[error] connect() failed (113: Host is unreachable) while connecting to upstream, ... upstream: "http://172.18.0.3:8000/chat"   (08:13:45)
```

Kết quả failover:
- **Không có request nào thất bại**: 12/12 request sau khi dừng đều 200, do 2 instance còn lại phục vụ; history của session còn nguyên vẹn (18 message sau lượt 9) vì state ở Redis.
- **Nhưng có 2 request chậm**: **39.25 s** (post-5) và **3.20 s** (post-12). Đó là những request mà round-robin chọn trúng instance đã chết: Nginx phải đợi `connect()` thất bại (lỗi 113 "Host is unreachable") rồi mới thử instance kế tiếp. Các request còn lại đều ~0.11–0.15 s. Vì sao hai lần chờ khác nhau (39 s và 3 s) tôi không xác định được chắc chắn (có thể liên quan đến việc phân giải ARP của bridge Docker; đây là suy đoán). Chỉ biết giới hạn trên mặc định của Nginx là `proxy_connect_timeout` 60 s.
- Sau mỗi lần fail, Nginx đánh dấu instance chết "không khả dụng" trong 10 s (mặc định `max_fails=1`, `fail_timeout=10s`, tôi suy ra từ việc các request liền sau đều nhanh và lần chậm kế tiếp chỉ xuất hiện sau khi nghỉ 12 s), hết 10 s thì lại thử lần nữa.

**Giải thích `nginx.conf`:**
- Dòng 9 `server agent:8000;`: DNS nội bộ của Docker trả về cả 3 IP của service `agent`, Nginx tạo 3 server trong `upstream` và quay vòng (round-robin mặc định). Các IP này được phân giải **một lần lúc Nginx khởi động** (suy từ tài liệu Nginx; dòng 5 `resolver ... valid=10s` không có tác dụng cho khối `upstream`), nên không tự cập nhật nếu container đổi IP. Trong thử nghiệm, container khởi động lại nhận lại đúng IP cũ (172.18.0.3) nên không gặp tình huống này.
- Dòng 23 `proxy_next_upstream error timeout http_503;`: khi kết nối tới instance bị `error` (connect refused/unreachable), `timeout`, hoặc instance trả `503`, Nginx tự chuyển request sang instance khác thay vì trả lỗi cho client. Đây là cơ chế giúp 12/12 request ở trên vẫn thành công.
- Dòng 24 `proxy_next_upstream_tries 3;`: thử tối đa 3 server cho mỗi request (đủ để quét hết 3 instance).
- Theo tài liệu Nginx, request `POST` (không idempotent) chỉ được thử lại khi chưa gửi tới upstream, tức là lỗi kết nối như trên được thử lại an toàn, còn lỗi sau khi đã gửi (như `http_503` trả về từ agent) thì với `POST` không được thử lại (chỉ đọc tài liệu, tôi không đo riêng ca này).

**Khởi động lại instance đã dừng:** `docker start k5-day14-scaling-agent-1`. Container lên lại cùng IP 172.18.0.3 nhưng **instance ID mới** (`instance-85d8e5` thành `instance-43b049`, vì ID sinh ngẫu nhiên mỗi lần chạy). 6 request mới tiếp theo đều 200, quay vòng đủ 3 instance, instance-43b049 nhận lại traffic ở request thứ 3 và 6.

**Redis chết: `/health` (liveness) khác `/ready` (readiness).** `docker compose -p k5-day14-scaling stop redis`, rồi gọi **trực tiếp trong container** agent-2 (để không bị Nginx can thiệp):

```text
$ docker compose -p k5-day14-scaling exec --index 2 agent python -c "<urlopen /health và /ready>"
/health 200 {"status":"degraded","instance_id":"instance-effe7a","uptime_seconds":178.0,"storage":"redis","redis_connected":false}
/ready  503 {"detail":"Redis not available"}

$ docker compose -p k5-day14-scaling ps agent
k5-day14-scaling-agent-1 Up About a minute (healthy)
k5-day14-scaling-agent-2 Up 2 minutes (healthy)
k5-day14-scaling-agent-3 Up 2 minutes (healthy)
```

Đúng như code (`production/app.py` dòng 187–215): `/health` luôn trả 200 và chỉ đổi `status` thành `degraded` (dòng 197), còn `/ready` ném `HTTPException(503, "Redis not available")` (dòng 211–214). Docker healthcheck của container gọi `/health` (compose dòng 31–36, Dockerfile dòng 40–43) nên container vẫn `healthy`, **không bị restart**: đúng ý nghĩa liveness (agent vẫn sống, tự nó không cần khởi động lại, restart cũng không làm Redis sống lại).

Qua Nginx (cổng 8080) thì kết quả thật khác hẳn kỳ vọng "ready 503, health 200":

```text
$ curl -i :8080/health (x3)  -> HTTP/1.1 200 OK  {"status":"degraded", ... "redis_connected":false}   (3 instance khác nhau)
$ curl -i :8080/ready  (x3)  -> HTTP/1.1 503 Service Unavailable {"detail":"Redis not available"}   [0.216s]
                              -> HTTP/1.1 502 Bad Gateway                                          [0.101s]
                              -> HTTP/1.1 502 Bad Gateway                                          [0.002s]
$ curl -i -X POST :8080/chat -> HTTP/1.1 502 Bad Gateway                                           [0.0006s]
```

Log Nginx cho thấy `no live upstreams while connecting to upstream ... request: "GET /ready"` và `... "POST /chat"`. Giải thích: do `proxy_next_upstream ... http_503` (dòng 23), mỗi lần một agent trả 503 cho `/ready`, Nginx coi đó là upstream lỗi, thử agent kế tiếp (cũng 503), cuối cùng cả 3 bị đánh dấu "không khả dụng" trong 10 s; request đầu trả về 503 của instance cuối, các request ngay sau đó **không còn upstream nào nên Nginx tự trả 502**, kể cả `/chat`. Sau khoảng 11 s:

```text
$ curl -i :8080/health -> HTTP/1.1 200 OK   {"status":"degraded", ... "redis_connected":false}   [0.059s]
$ curl -i -X POST :8080/chat -d '{"question":"hi redis down"}' -> HTTP/1.1 500 Internal Server Error   "Internal Server Error"   [0.054s]
```

`/chat` lúc này là **500 thô** vì `append_to_history` gọi Redis không có `try/except` (log agent: `redis.exceptions.ConnectionError: Error -3 connecting to redis:6379. Temporary failure in name resolution.`). Người dùng nhận 500 (hoặc 502 trong 10 s đầu), không có thông báo lỗi có cấu trúc.

Khôi phục: `docker compose -p k5-day14-scaling start redis`, sau 4 s:

```text
$ redis-cli DBSIZE -> 28            (dữ liệu session vẫn còn vì container Redis chỉ bị dừng chứ chưa bị xoá; Redis trong compose này không có volume, nên chỉ cần `docker compose down`, kể cả không có `-v`, là container bị xoá và mất toàn bộ session)
$ curl -i :8080/health -> 200 {"status":"ok", ... "redis_connected":true}
$ curl -i :8080/ready  -> 200 {"ready":true,"instance":"instance-43b049"}
POST /chat -> 200 (served_by instance-2d5f78)
history failover-session-1 -> count 20 (vẫn còn)
```

Agent không cần restart: client `redis-py` tự kết nối lại ở request tiếp theo.

### Exercise 5.5: Test stateless (`test_stateless.py`)

Chạy trong `05-scaling-reliability/production/` với stack 3 replica:

```text
$ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: b44c354e-ef6c-408e-9854-3e04d904687b

Request 1: [instance-effe7a]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-85d8e5]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-2d5f78]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-effe7a]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-85d8e5]
  Q: What is Redis used for?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-effe7a', 'instance-2d5f78', 'instance-85d8e5'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

✅ Session history preserved across all instances via Redis!
```

**Giải thích:**
- 5 lượt cùng một `session_id` được 3 instance khác nhau phục vụ theo vòng `effe7a → 85d8e5 → 2d5f78 → effe7a → 85d8e5` (round-robin của Nginx), cả 3 instance đều tham gia.
- History có **10 message** = 5 `user` + 5 `assistant`, đúng thứ tự, dù mỗi lượt nằm ở một instance khác. Lý do: instance nào cũng ghi vào và đọc từ cùng một key `session:{id}` trong Redis (dòng 63, 71 của `app.py`), bản thân tiến trình agent không giữ gì trong RAM. Ngược lại với thí nghiệm 2 instance không Redis ở 5.3, nơi lượt 2 mất lượt 1.
- **Script này không tắt instance nào** (đọc `test_stateless.py`: chỉ `post` 5 lần rồi `get` history). Phần "kill một instance rồi gọi tiếp" của CODE_LAB 5.5 đã được làm thủ công ở **5.4 (Failover)**: dừng `agent-1` giữa session, các lượt sau vẫn 200 và history đủ 18 message.

### Quan sát: lỗi và điểm đáng chú ý thật sự thấy khi chạy

1. **Race condition ở `append_to_history` (đã đo).** Hàm này đọc session, sửa, ghi lại (dòng 78–89), **không nguyên tử**. Hai request cùng session ở hai instance khác nhau có thể cùng đọc một bản rồi ghi đè nhau, mất message. Thử: 8 request `POST /chat` song song, cùng một session mới (mỗi session kỳ vọng 16 message, dưới giới hạn 20), lặp 10 vòng trên stack 3 replica:

   ```text
   round  1: HTTP [200] x8 | expected 16 msgs, got 15 (user=7, assistant=8) | lost=1
   round  2: HTTP [200] x8 | expected 16 msgs, got 14 (user=6, assistant=8) | lost=2
   round  3: HTTP [200] x8 | expected 16 msgs, got 16 (user=8, assistant=8) | lost=0
   round  4: HTTP [200] x8 | expected 16 msgs, got 14 (user=6, assistant=8) | lost=2
   round  5: HTTP [200] x8 | expected 16 msgs, got 14 (user=6, assistant=8) | lost=2
   round  6: HTTP [200] x8 | expected 16 msgs, got 14 (user=7, assistant=7) | lost=2
   round  7: HTTP [200] x8 | expected 16 msgs, got 16 (user=8, assistant=8) | lost=0
   round  8: HTTP [200] x8 | expected 16 msgs, got 15 (user=7, assistant=8) | lost=1
   round  9: HTTP [200] x8 | expected 16 msgs, got 15 (user=7, assistant=8) | lost=1
   round 10: HTTP [200] x8 | expected 16 msgs, got 16 (user=8, assistant=8) | lost=0
   TOTAL lost messages: 11 over 10 rounds
   ```

   Mất message ở 7/10 vòng (11 trên tổng 160), dù cả 80 request đều trả 200. "Stateless + Redis" giải quyết được việc chia sẻ state giữa instance nhưng **chưa an toàn khi ghi đồng thời**. Vì `append_to_history` là code đồng bộ trong một process (không có `await` giữa load và save) nên theo suy luận của tôi các lần mất xảy ra giữa các instance khác nhau. Cách sửa: dùng `RPUSH`/`LTRIM` trên Redis list (nguyên tử), hoặc Lua/`WATCH` + `MULTI`.
2. **Failover có request chậm 39.25 s và 3.20 s** (xem 5.4), dù không có request nào lỗi. Nguyên nhân là `nginx.conf` chỉ có passive health check và chưa đặt `proxy_connect_timeout` ngắn. Chữa: đặt `proxy_connect_timeout 1s;` và `max_fails`/`fail_timeout` rõ ràng.
3. **Khi Redis chết, Nginx khuếch đại 503 của `/ready` thành 502 cho toàn bộ traffic** trong ~10 s (kể cả `/chat`) rồi sau đó là 500 thô (xem 5.4). Nginx mã nguồn mở không dùng `/ready` làm health check chủ động; nó chỉ suy luận từ lỗi thật của request qua `proxy_next_upstream ... http_503`. Platform (K8s, Railway, Render) mới là nơi dùng `/ready` để rút instance khỏi load balancer. `/chat` cũng nên bắt `redis.exceptions.ConnectionError` và trả 503 có thông báo.
4. **Fallback in-memory âm thầm (đã đo).** Khi mất Redis lúc khởi động, app vẫn `/health` ok và `/ready` 200, trả 200 cho `/chat`, nhưng mất ngữ cảnh khi gặp instance khác (xem 5.3). Ở môi trường nhiều instance nên để app **không khởi động được** (hoặc `/ready` = 503) khi thiếu Redis thay vì chạy tiếp ở chế độ sai.
5. **Trường `turn` sai 1 đơn vị (đã đo).** Lượt 1 của một session mới trả `"turn":2` (xem output 5.3). Nguyên nhân (dòng 140–154): `append_to_history(... "user" ...)` đã chạy trước, rồi `history` được load lại và `turn = số message user + 1`, cộng thừa 1.
6. **`history` không được đưa vào LLM**: dòng 142–145 chỉ gọi `ask(body.question)` (chú thích dòng 142 thừa nhận "trong mock chỉ dùng câu hỏi hiện tại"), biến `history` ở dòng 144 chỉ dùng để tính `turn`. Đây là hạn chế của code mẫu, không phải lỗi scale.
7. **Dockerfile (đã kiểm tra trong container):** `CMD` ở dòng 45 dùng **dạng exec** và **không có `--workers`**. Kiểm tra `/proc/1/cmdline` trong container agent: `python -m uvicorn app:app --host 0.0.0.0 --port 8000`, PID 1 là uvicorn (một process duy nhất), chạy bằng user `agent` (uid 999). Vì PID 1 là uvicorn nên `docker stop` gửi SIGTERM thẳng cho nó và container thoát êm. Kiểm chứng riêng bằng image `k5-day14-scaling-agent`: `docker stop` xong sau **0.47 s**, `ExitCode=0`, log kết thúc bằng `Waiting for application shutdown.` → `Application shutdown complete.` → `Finished server process [1]` (PID 1). Việc scale ngang ở đây hoàn toàn do số container, không phải số worker.
8. **Instance ID đổi sau mỗi lần khởi động** (`instance-85d8e5` thành `instance-43b049`, đã đo) vì compose không đặt `INSTANCE_ID`. Muốn log/metrics theo dõi được một instance qua lần restart thì đặt ID cố định (ví dụ từ hostname).
9. **Cấu hình Redis trong compose** (dòng 52–53): `--maxmemory 128mb --maxmemory-policy allkeys-lru` nghĩa là khi đầy bộ nhớ Redis sẽ **xoá bớt key bất kỳ ít dùng nhất, kể cả session còn hạn**; và không có volume nên chỉ cần `docker compose down` (xoá container) là mất toàn bộ session (đọc code, không đo).
10. **`/health` của bản develop** trả 200 kể cả khi `status` là `degraded` (RAM >= 90%), nên platform không restart vì RAM cao (đọc code, dòng 127–144).

### Tổng kết: liveness vs readiness; vì sao state trong RAM hỏng khi scale

**Liveness (`/health`) trả lời "process còn sống không", readiness (`/ready`) trả lời "có nên gửi traffic vào đây lúc này không".** Platform restart khi liveness fail và chỉ rút instance khỏi load balancer khi readiness fail. Thí nghiệm Redis chết cho thấy rõ sự khác biệt: trực tiếp trên mỗi instance `/health` vẫn 200 (`degraded`, container vẫn `healthy`, không bị restart vì restart cũng không cứu được Redis) còn `/ready` là 503 (instance không dùng được, nên ngừng nhận traffic). Thí nghiệm cũng cho thấy ranh giới của cách làm: Nginx trong lab không dùng `/ready` mà chỉ phản ứng qua `proxy_next_upstream`, nên 503 của cả 3 instance biến thành 502 rồi 500 cho người dùng; bản đầy đủ cần platform hoặc health check chủ động đọc `/ready`, và `/chat` cần trả 503 có kiểm soát. Còn khi shutdown, đo được rằng cổng bị uvicorn đóng trước khi cờ `_is_ready` có tác dụng, nên việc "không mất request" là nhờ uvicorn chờ request đang chạy (3.007 s, HTTP 200, exit code 0) chứ không nhờ vòng chờ trong `lifespan` (vòng này không chạy lần nào).

**State trong RAM hỏng khi scale vì mỗi instance có một bộ nhớ riêng còn load balancer thì không biết user thuộc instance nào.** Bằng chứng: hai instance không Redis, lượt 1 vào 8001 và lượt 2 vào 8002 cho history chỉ có 2 message của lượt 2 (hoặc 404 với session chưa từng tới đó), và không có lỗi nào được báo. Khi chuyển state vào Redis (key `session:{id}`, TTL 3600 s, tối đa 20 message), `test_stateless.py` cho 5 lượt qua 3 instance vẫn ra đủ 10 message, và dừng hẳn một instance giữa session thì các lượt sau vẫn 200 với history nguyên vẹn (18 message), vì instance nào cũng đọc được cùng một nguồn dữ liệu. Stateless chưa đủ để "an toàn": thí nghiệm ghi đồng thời cho thấy `append_to_history` không nguyên tử làm mất message (11/160), và failover thụ động của Nginx làm vài request chậm 3–39 s. Hai điểm này là việc phải xử lý tiếp ở Part 6 và lúc deploy thật.

## Part 6: Output `check_production_ready.py`

_(chưa làm)_

---

## AI log

| # | Phần | Hỏi AI gì | AI trả về gì | Tôi tự kiểm tra / sửa thế nào |
|---|---|---|---|---|
| 1 | Part 1 | Dùng Claude Code (Anthropic) đọc `develop/app.py`, `production/app.py`, `config.py`; chạy hai bản app, gọi thử các endpoint và SIGTERM; soạn nháp câu trả lời Part 1 | Danh sách anti-pattern có số dòng, bảng so sánh, và phát hiện 4 lỗi của bản production (log JSON bị nuốt, JSON lồng không hợp lệ, 500 khi body sai, thứ tự handler SIGTERM) | Mọi output trong Part 1 là output thật của lệnh đã chạy (curl, `ss -ltn`, log server). Lỗi log JSON được kiểm chứng bằng cách chạy lại với `OPENAI_API_KEY=dummy-for-test` và parse từng dòng log bằng `json.loads`. _(Bạn tự bổ sung: phần nào bạn đã đọc lại, chạy lại hoặc sửa)_ |
| 2 | Part 2 | Dùng Claude Code: một agent (Claude Sonnet) đọc Dockerfile, compose, nginx.conf; build `my-agent:develop` và `my-agent:advanced` từ gốc repo; chạy container và stack compose `-p k5-day14-docker`; soạn nháp Part 2. Sau đó một agent khác (Claude Opus) review | Câu trả lời 2.1–2.4, kích thước image đo bằng `docker image inspect`, sơ đồ stack, output test qua Nginx; phát hiện compose ghi "2 replicas" nhưng thực tế chỉ có 1 container agent, và agent không hề dùng Redis/Qdrant | Phần review đối chiếu lại toàn bộ số dòng được trích với file gốc; kiểm tra khoản chênh 12.5 MB bằng `pip list` trong hai image (cùng 24 package) và sửa lại đoạn giải thích; làm nhẹ câu giải thích image ID đổi vì đó là phỏng đoán. _(Bạn tự bổ sung: phần nào bạn đã đọc lại, chạy lại hoặc sửa)_ |
| 3 | Part 4 | Dùng Claude Code: một agent (Claude Sonnet) đọc `04-api-gateway`, chạy bản develop (API key) và production (JWT, rate limit), chạy vòng lặp 20 request, viết `cost_guard_redis.py` (Lua atomic) + test và chạy với Redis thật, soạn nháp Part 4. Sau đó một agent khác (Claude Opus) review | Output 401/403/200/429 (đã che token), giải thích JWT / rate limiter / cost guard, bản cost guard Redis theo tháng có kiểm tra + cộng nguyên tử, test cho thấy bản naive của CODE_LAB vượt budget còn bản Lua thì không | Phần review đối chiếu toàn bộ số dòng được trích với code gốc; sửa `reconcile()` để từ chối chi phí âm (trước đó có thể bị dùng để lách budget); tự chạy lại test trên một Redis riêng (tái hiện được: Lua 20/$10, naive vượt budget), rồi dán output của lần chạy cuối trên đúng code được nộp. _(Bạn tự bổ sung: phần nào bạn đã đọc lại, chạy lại hoặc sửa)_ |
| 4 | Part 5 | Dùng Claude Code: một agent (Claude Sonnet) chạy bản develop (health/ready, SIGTERM), chạy 2 instance không Redis để chứng minh state trong RAM hỏng, chạy stack `-p k5-day14-scaling` 3 replica, thử failover, dừng Redis, chạy `test_stateless.py` và một test ghi đồng thời; soạn nháp Part 5. Sau đó một agent khác (Claude Opus) review | Kết quả đo: round-robin 4/3/3, failover 12/12 request thành công (có 2 request chậm), `/health` 200 degraded còn `/ready` 503 khi Redis chết, lịch sử mất khi không có Redis, mất 11/160 message khi ghi đồng thời | Phần review đối chiếu số dòng trong code lab và trong mã nguồn uvicorn 0.30.0 (`server.py` 257–290, 311–328); kiểm tra lại mock LLM của Part 5 đúng là trễ 3 s; tự chạy lại `docker stop` trên image agent (ExitCode 0, 0.47 s) để thay câu khẳng định chưa có bằng chứng; sửa câu sai về volume Redis (`down` không `-v` cũng mất dữ liệu). _(Bạn tự bổ sung: phần nào bạn đã đọc lại, chạy lại hoặc sửa)_ |
