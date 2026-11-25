# Benchmark & Observability Report — Day 14

> Mọi con số trong các bảng mục 2 và 3 được copy từ các file JSON trong `06-lab-complete/benchmark-observability/develop/reports/` do chính tôi chạy ra. Quy ước làm tròn và bảng đối chiếu số liệu ở cuối file (Phụ lục, mục F).
> Trạng thái: mục 1, 2, 3 và Phụ lục (Exercise 7.1–7.3) đã xong ở CP7. Mục 4, 5 điền ở CP8; mục 6 mới điền một phần.

**Họ tên:** Nguyễn Mạnh Tường (2A202603646)
**Ngày chạy:** 2026-11-25
**Môi trường:** Lenovo ThinkPad X1 Carbon Gen 8 (Intel Core i7-10610U, 8 luồng CPU theo `nproc`, 15 GB RAM theo `free -g`), Ubuntu 22.04.5 LTS (kernel 6.8.0-149), Python 3.11.18, fastapi 0.115.0, prometheus-client 0.26.0, httpx 0.27.2. Chạy local, không dùng Docker. Agent (1 process uvicorn) và `load_test.py` chạy **cùng một máy**.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Khi tải vừa phải, p95 đo được là 224.1 ms (c=1), 231.0 ms (c=10) và 416.2 ms (c=50); ngưỡng 500 ms bằng khoảng 2.2 lần p95 ở c=1 nên đủ biên cho dao động bình thường. Ngưỡng này vẫn bắt được sự cố thật: p95 = 4218.7 ms ở c=100 và 1684.1 ms khi `MOCK_SLOW_RATE=0.1` đều vi phạm. |
| p99 latency `/ask` (tham khảo, `load_test.py` không tự kiểm) | < 2000 ms | Với `MOCK_SLOW_RATE=0.03`, p99 đo được 1697.0 ms (mục 2.2), cộng thêm khoảng 1.5 s của `MOCK_SLOW_MS`. Đặt trần 2 s để request chậm nhất của người dùng vẫn nằm dưới ngưỡng timeout 10 s của client, nhưng đủ chặt để thấy khi đuôi chậm xấu đi (p99 = 4625.6 ms ở c=100). |
| Error rate `/ask` | < 2 % | Mock upstream cố ý lỗi 1% (`MOCK_ERROR_RATE=0.01`), nên 2% là gấp đôi mức lỗi nền. Lưu ý mẫu 300 request chỉ cho độ lệch chuẩn khoảng 0.57 điểm %: error rate đo được dao động từ 0.33% (c=10) tới 2.33% (c=50, vượt ngưỡng chỉ vì ngẫu nhiên, xem mục 2.1). |
| Accuracy trên golden dataset | ≥ 85 % | v2 ban đầu đạt 91.3% (21/23), sau khi sửa KB đạt 100.0% (23/23). Với 23 câu, 85% cho phép tối đa 3 câu sai (20/23 = 87.0% đạt, 19/23 = 82.6% không đạt); v1 chỉ đạt 4.3% nên bị chặn. Cùng ngưỡng này được dùng trong job CI (`.github/workflows/eval.yml`). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Cấu hình chung: agent v2 (`AGENT_VERSION=v2`, cổng 8002), 300 request mỗi lần, mặc định `MOCK_SLOW_RATE=0.03` và `MOCK_ERROR_RATE=0.01` cho bảng 2.1. SLO của `load_test.py`: p95 ≤ 500 ms và error rate ≤ 2%.

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.22 | 196.2 | 224.1 | 1702.4 | 0.67% | PASS |
| 10 | 34.48 | 194.3 | 231.0 | 1707.1 | 0.33% | PASS |
| 50 | 97.7 | 213.5 | 416.2 | 1725.4 | 2.33% | FAIL (error rate) |
| 100 | 50.66 | 644.4 | 4218.7 | 4625.6 | 1.00% | FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` (các trường `rps`, `latency_ms.p50/p95/p99`, `error_rate`, `slo.passed`). Mọi lỗi đều là HTTP 503 do mock upstream (`status_codes`: c=1 2/300, c=10 1/300, c=50 7/300, c=100 3/300). Tỉ lệ này do `random.random() < MOCK_ERROR_RATE` trong `mock_llm.py` quyết định, không phụ thuộc concurrency, nên dòng c=50 bị FAIL error rate (2.33% > 2%) là do ngẫu nhiên của mẫu 300 request, không phải do agent quá tải (p95 ở dòng đó vẫn PASS).

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency.

- c=1 → c=10: RPS tăng 8.17 lần (lý tưởng 10 lần, hiệu suất 82%). Agent viết bằng `async`, mock LLM chỉ `await asyncio.sleep(...)` nên một process phục vụ được nhiều request đang chờ cùng lúc. Ở c=1, RPS 4.22 gần với 1 / avg = 1 / 235.2 ms = 4.25 req/s, nghĩa là mỗi request chờ nối tiếp nhau.
- c=10 → c=50: RPS chỉ tăng thêm 2.83 lần (tổng 23.15 lần so với c=1, hiệu suất 46%). Latency bắt đầu tăng: p95 231.0 → 416.2 ms, avg 254.8 → 285.6 ms, p50 194.3 → 213.5 ms. Một phần "mất hiệu suất" là do phép đo: mỗi lần chỉ 300 request, c=50 chạy 3.07 s mà một request chậm nhất đã mất 1901.9 ms (khoảng 62% thời gian chạy; ở c=10 là 20%), nên RPS tính bằng `tổng request / thời gian` bị kéo xuống bởi đuôi.
- c=50 → c=100: RPS **giảm** 0.52 lần (97.7 → 50.66) và latency tăng vọt: avg 1369.2 ms, p50 644.4 ms, p95 4218.7 ms, p99 4625.6 ms, SLO p95 FAIL. Tức là đã quá điểm bão hoà.

**Cái gì bão hoà?** Tôi đã chạy thêm một lần chẩn đoán và lưu kết quả vào `reports/diag_cpu.json` (kèm `diag_load_v2_c50.json`, `diag_load_v2_c100.json`; xem Phụ lục mục E). Ở c=100, process `load_test.py` dùng 5.22 s CPU user trong 7.42 s thời gian chạy (khoảng 70% một lõi, chỉ có một event loop Python), trong khi process agent chỉ tốn 0.53 s CPU (khoảng 7% của một lõi). Ở c=50 thì client chỉ dùng 0.76 s CPU trong 2.92 s. Vậy ở c=100 điểm nghẽn nằm ở **phía công cụ tạo tải** (một process Python/asyncio chạy cùng máy với agent, tranh CPU và gom 100 kết nối), không phải agent hết năng lực. Hệ quả cho cách đọc bảng: dòng c=100 là "agent + load_test.py trên cùng một máy" chứ không phải năng lực thật của agent; năng lực thật của agent chắc chắn không thấp hơn dòng c=50 (97.7 req/s), và muốn đo giới hạn thật cần chạy công cụ tạo tải ở máy khác, nhiều process, hoặc dùng Locust (Bước 2) và chạy dài hơn (`--duration`). Tôi chưa chạy các cách đó ở CP7 nên không có số liệu để khẳng định giới hạn thật.

### 2.2 Tail latency

Cấu hình: v2 khởi động lại cho từng mức `MOCK_SLOW_RATE`, mỗi lần `--requests 300 --concurrency 20`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 197.0 | 228.0 | 239.7 |
| 0.03 (mặc định) | 246.2 | 243.2 | 1697.0 |
| 0.1 | 300.8 | 1684.1 | 1719.2 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` (`latency_ms.avg/p95/p99`). Chênh lệch tính từ các số trên (dòng `0` làm mốc):

| So với `MOCK_SLOW_RATE=0` | avg | p95 | p99 |
|---|---|---|---|
| 0.03 | +49.2 ms (1.25x) | +15.2 ms (1.07x) | +1457.3 ms (7.08x) |
| 0.1 | +103.8 ms (1.53x) | +1456.1 ms (7.39x) | +1479.5 ms (7.17x) |

**Nhận xét:** Chỉ số nhạy nhất với request chậm là **percentile cao (p99, rồi p95)**, không phải average.

- Với 3% request chậm, avg chỉ nhích 49.2 ms (1.25x, vẫn đẹp so với ngưỡng 500 ms) và p95 gần như không đổi (243.2 ms, vẫn PASS), nhưng **p99 nhảy từ 239.7 ms lên 1697.0 ms** (7.08x). Cứ 100 người thì có khoảng 3 người chờ thêm ~1.5 s mà avg không phản ánh.
- Với 10% request chậm (> 5%), cả **p95 cũng nhảy lên 1684.1 ms** (SLO p95 FAIL) trong khi avg mới tăng 103.8 ms.
- Vì sao: average trộn đều phần chậm vào tất cả request. Mỗi request chậm thêm `MOCK_SLOW_MS` = 1500 ms nên avg tăng khoảng `tỉ lệ × 1500` ms (lý thuyết 45 ms với 0.03 và 150 ms với 0.1; đo được +49.2 ms và +103.8 ms, lệch do mẫu 300 request quá nhỏ). Còn p99 là "giá trị mà 99% request nhanh hơn": khi nhóm chậm chiếm hơn 1% thì p99 rơi hẳn vào nhóm chậm, và khi nhóm chậm chiếm hơn 5% thì p95 cũng rơi vào đó. Percentile mô tả trải nghiệm của nhóm người dùng xấu nhất, average thì che giấu họ.
- SLO không nên đặt theo average: avg = 246.2 ms ở `0.03` nhìn rất ổn trong khi p99 = 1697.0 ms. SLO nên đặt theo p95 (và p99 cho đuôi) kèm error rate.
- Lưu ý: `load_test.py` chạy cùng máy với agent nên con số tuyệt đối còn chịu ảnh hưởng của máy; kết luận về hình dạng (avg hầu như không đổi, p99/p95 nhảy) thì không đổi.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.0 | 109.3 | 117.5 |
| Tổng cost (USD) | 0.000402 | 0.000764 | 0.000823 |
| Cost / câu đúng (USD) | 0.00040215 | 0.00003639 | 0.00003580 |
| Quality gate | FAIL (min-accuracy 0.8) | PASS (min-accuracy 0.8, baseline v1) | PASS (min-accuracy 1.0, baseline v2, regression 0) |

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json` (`accuracy`, `passed`, `total`, `avg_tokens`, `total_cost_usd`, `cost_per_correct_usd`, `quality_gate`). Lệnh: v1 `--out reports/eval_v1.json`; v2 `--baseline reports/eval_v1.json --out reports/eval_v2.json`; v2 sửa KB `--min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json`. Cả 3 lần chạy đều có `errors = 0` (không câu nào dính lỗi upstream ngẫu nhiên). Gate của v1 FAIL vì accuracy 4.3% < 80% (ngưỡng mặc định); v1 không có baseline nên không có regression.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key trong xác thực?") | token, hết hạn, chữ ký (score 0.0) | Không có entry nào có trigger khớp câu hỏi nên retrieval rỗng và v2 trả câu mẫu chung chung. Thêm entry trigger `["jwt"]` giải thích JWT là token có chữ ký số và thời điểm hết hạn, so với API key cố định. Sau khi sửa: score 1.0, không còn keyword thiếu. |
| scaling-03 ("Kubernetes HPA scale dựa trên những chỉ số nào?") | cpu, memory, custom metrics (score 0.0) | Tương tự, thêm entry trigger `["hpa", "kubernetes"]` nói HPA scale theo CPU, memory và custom metrics. Sau khi sửa: score 1.0, không còn keyword thiếu. |

Nội dung hai entry mới và bằng chứng "chỉ 2 câu này đổi kết quả retrieval, không regression" nằm ở Phụ lục mục D. Hai entry này cũng đã được chép sang `production/utils/mock_llm.py`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 (có retrieval) từ 4.3% (1/23) lên 91.3% (21/23), tức đúng thêm 20 câu; v1 chỉ đúng 1 câu (`basic-01`) vì không có tài liệu để dựa vào. Sau khi sửa 2 lỗ hổng KB, v2 đạt 100.0% (23/23).
- **Chi phí theo câu:** v2 tốn gấp 1.92 lần token mỗi câu (avg tokens 57.0 → 109.3) vì prompt chứa thêm context, tổng cost gấp 1.9 lần (0.000402 → 0.000764 USD cho 23 câu, tức khoảng 0.00001748 → 0.00003322 USD mỗi câu).
- **Chi phí theo câu đúng:** nhìn riêng "cost / câu" thì v2 trông đắt hơn, nhưng **cost / câu đúng của v2 là 0.00003639 USD so với 0.00040215 USD của v1, rẻ hơn 11.05 lần**. Lý do: v1 trả tiền cho 23 câu nhưng chỉ có 1 câu dùng được, nên toàn bộ chi phí dồn vào 1 câu đúng; v2 trả gấp ~1.9 lần nhưng có 21 câu đúng. Đó là lý do dùng "cost / câu đúng" để so hai phiên bản: nó tính cả chất lượng, còn "cost / câu" thì thưởng cho agent rẻ nhưng sai.
- **Sau khi sửa KB:** thêm 2 câu đúng làm avg tokens tăng 7.5% (109.3 → 117.5) và tổng cost tăng 7.7% do 2 câu này giờ có context, nhưng cost / câu đúng lại giảm 1.6% (0.00003639 → 0.00003580) vì chia cho 23 câu đúng thay vì 21. So với v1, v2 sau sửa rẻ hơn 11.23 lần trên mỗi câu đúng.
- **Latency:** p50 trong eval tăng từ 168.8 ms (v1) lên 190.9 ms (v2), +22.1 ms (+13.1%). Phần tăng này khớp với thiết kế của mock: bước retrieval (`MOCK_RETRIEVAL_MS` = 20 ms) cộng prompt dài hơn (latency tăng 0.2 ms mỗi token input). Không nên so p95 giữa các lần eval (1493.3 / 221.5 / 1537.4 ms cho v1 / v2 / v2 sau sửa): mẫu chỉ 23 câu và số request chậm ngẫu nhiên (> 1000 ms, đếm từ `results[].latency_ms`) là 2 / 1 / 2 request cho ba lần chạy; một request chậm không đổi p95 (221.5 ms ở v2 dù có 1 request chậm) nhưng hai request chậm (≥ 2/23 ≈ 8.7%) là p95 nhảy lên khoảng 1.5 s, nên p95 ở eval không đáng tin. Latency phải đo bằng load test (mục 2). Trong CP7 tôi chỉ load test v2, chưa load test v1, nên chưa có so sánh latency v1 vs v2 ở tải cao.
- **Kết luận:** đổi lại chi phí mỗi câu gấp ~1.9–2.05 lần và thêm ~22.1 ms ở p50, v2 cho chất lượng gấp 21.0 lần (21 so với 1 câu đúng) và rẻ hơn ~11.05 lần trên mỗi câu đúng. Với agent chạy thật thì v2 đáng đổi, miễn là có eval để phát hiện các lỗ hổng KB như `scaling-03` và `security-02`.

---

## 4. Observability stack (production)

> (điền ở CP8)

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

> (điền ở CP8)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---


## 6. Kết luận

> (bổ sung sau CP8: phần tracing, alert, scaling và câu hỏi cuối)

- 3 điều bạn học được về benchmark & observability (rút ra từ CP7):
  1. Average che giấu đuôi chậm: với `MOCK_SLOW_RATE=0.03`, avg chỉ tăng 49.2 ms trong khi p99 tăng 1457.3 ms (239.7 → 1697.0 ms), nên SLO phải đặt theo p95/p99 và error rate.
  2. Số đo phụ thuộc cách đo: ở c=100, RPS giảm (97.7 → 50.66) vì công cụ tạo tải chạy cùng máy bị nghẽn trước agent; phải kiểm tra CPU của cả hai phía trước khi kết luận "agent chậm". Eval 23 câu cũng quá nhỏ để đo p95 latency.
  3. So sánh phiên bản bằng "cost / câu đúng" chứ không phải "cost / câu" (0.00040215 so với 0.00003639 USD), và dùng exit code của `run_eval.py` làm quality gate trong CI để chặn regression trước khi merge.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa? (bổ sung sau CP8). Đã thêm sẵn metric `agent_question_length_chars` (Phụ lục A) để theo dõi phân bố độ dài câu hỏi.

---

## Phụ lục: Exercise 7.1–7.3

Mọi lệnh chạy trong `06-lab-complete/benchmark-observability/develop/` với Python 3.11 của venv của repo.

### A. Exercise 7.1: đọc metrics của agent

Lệnh: khởi động `AGENT_VERSION=v1 PORT=8001 python app.py` và `AGENT_VERSION=v2 PORT=8002 python app.py`, gọi một `POST /ask` tới cổng 8002 rồi `curl -s http://localhost:8002/metrics | grep -v "^#"`.

**Câu 1: một ví dụ cho mỗi loại metric (dòng thật từ `/metrics`):**

| Loại | Metric | Dòng trong output | Vì sao thuộc loại này |
|---|---|---|---|
| Counter | `http_requests_total` | `http_requests_total{method="POST",route="/ask",status="200"} 1.0` | Chỉ tăng, mỗi request thêm 1; dùng với `rate()` |
| Gauge | `agent_in_flight_requests` | `agent_in_flight_requests 0.0` | Lên xuống: `IN_FLIGHT.inc()` khi request vào, `.dec()` khi xong; đo lúc không có request nào đang xử lý nên bằng 0 |
| Histogram | `http_request_duration_seconds` | xem dưới | Chia thời gian xử lý vào các bucket `le` cộng dồn, kèm `_count` và `_sum`; tính percentile bằng `histogram_quantile()` |

```text
http_request_duration_seconds_bucket{le="0.1",method="POST",route="/ask"} 0.0
http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 1.0
http_request_duration_seconds_bucket{le="+Inf",method="POST",route="/ask"} 1.0
http_request_duration_seconds_count{method="POST",route="/ask"} 1.0
http_request_duration_seconds_sum{method="POST",route="/ask"} 0.1857371530004457
```

(Request `/ask` duy nhất đó mất 0.1857 s nên rơi vào bucket `le="0.2"` trở lên, `_sum` ≈ 0.1857.)

**Câu 2: vì sao label `route` dùng `route.path` (template) chứ không dùng `request.url.path`?** `route.path` là mẫu route đã khai báo (`/ask`, `/health`, `/metrics`), một tập nhỏ cố định; request không khớp route nào thì gán `unmatched`. `request.url.path` là URL thật do client gửi, tập giá trị **không giới hạn**, và bot quét có thể tự do tạo ra. Mỗi giá trị label mới là một time series mới. Tôi đã thử trên agent đang chạy: gọi `/wp-admin`, `/.env`, `/a1b2c3`, `/x9y8z7` (cả 4 trả 404) thì `/metrics` chỉ có **một** series:

```text
http_requests_total{method="GET",route="unmatched",status="404"} 4.0
http_request_duration_seconds_count{method="GET",route="unmatched"} 4.0
```

Nếu dùng URL thật thì 4 URL này thành 4 nhóm series riêng. Mỗi tổ hợp (method, đường dẫn, status) của agent này tốn 15 series (counter 1 + histogram 12 bucket kể cả `+Inf` + `_count` + `_sum`; đếm từ output `/metrics` ở trên, bucket có 11 mốc), nên 1000 URL lạ ≈ 15 000 series. Bot quét hàng nghìn URL thì số series tăng không giới hạn: Prometheus ngốn RAM và CPU (cardinality explosion), query chậm, `/metrics` phình to, và kẻ tấn công có thể dùng chính việc này để làm hỏng hệ thống giám sát. Dùng `route.path` giữ số series cố định bất kể bot gọi bao nhiêu URL.

**Nhiệm vụ: thêm Histogram `agent_question_length_chars`.** Đã sửa `develop/app.py` (và phản chiếu sang `production/app/metrics.py` + `production/app/main.py`):

```python
QUESTION_LENGTH = Histogram(
    "agent_question_length_chars", "Độ dài câu hỏi (ký tự)",
    buckets=(20, 50, 100, 200, 500, 1000, 2000),
)

# trong ask(), trước khi gọi LLM:
QUESTION_LENGTH.observe(len(body.question))
```

Bucket tối đa 2000 vì `AskRequest` giới hạn `max_length=2000`; các mốc 20/50/100 tách câu ngắn kiểu "Docker là gì?" khỏi câu dài có ngữ cảnh. Sau khi khởi động lại agent v2 tôi gửi 3 câu hỏi dài 40, 13 và 320 ký tự (kiểm bằng `len()` của Python) và `/metrics` cho:

```text
agent_question_length_chars_bucket{le="20.0"} 1.0
agent_question_length_chars_bucket{le="50.0"} 2.0
agent_question_length_chars_bucket{le="100.0"} 2.0
agent_question_length_chars_bucket{le="200.0"} 2.0
agent_question_length_chars_bucket{le="500.0"} 3.0
agent_question_length_chars_bucket{le="1000.0"} 3.0
agent_question_length_chars_bucket{le="2000.0"} 3.0
agent_question_length_chars_bucket{le="+Inf"} 3.0
agent_question_length_chars_count 3.0
agent_question_length_chars_sum 373.0
```

Khớp tay: 13 → bucket 20; 40 → bucket 50; 320 → bucket 500; tổng 13 + 40 + 320 = 373 = `_sum`. (Lần chạy thử này dùng một instance khởi động lại sau đó nên không lẫn vào các file JSON của mục 2 và 3.)

**Vì sao Histogram mà không phải label `length=...`?** Độ dài câu hỏi có hàng nghìn giá trị (1 tới 2000), mỗi giá trị làm label sẽ thành một time series riêng (cardinality 2000 nhân với số tổ hợp label khác), đúng kiểu label cardinality cao mà README cảnh báo. Histogram chỉ cần số series cố định (số bucket cộng `_count`, `_sum`: ở đây 7 bucket + `+Inf` + 2 = 10 series) dù có bao nhiêu câu hỏi, mà vẫn trả lời được "bao nhiêu % câu hỏi dài dưới 100 ký tự" qua `histogram_quantile()`.

Phần phản chiếu sang `production/`: tôi chỉ thêm 1 định nghĩa metric trong `app/metrics.py` và 1 dòng `m.QUESTION_LENGTH.observe(...)` trong `app/main.py`, kiểm cú pháp bằng `ast.parse`. Tôi **chưa chạy** bản production vì máy này không có Docker (và thiếu cả thư viện OpenTelemetry của bản đó), nên chỉ khẳng định được đã kiểm cú pháp, chưa kiểm hoạt động.

### B. Exercise 7.2: câu hỏi "vì sao avg chỉ tăng nhẹ mà p99 tăng vọt, SLO nên đặt theo chỉ số nào?"

Số liệu: bảng 2.2 ở trên (`MOCK_SLOW_RATE` 0 → 0.03: avg +49.2 ms nhưng p99 +1457.3 ms).

- Chỉ một nhóm nhỏ request bị chậm (3%), mỗi request chậm thêm 1500 ms. Average chia đều phần chậm đó cho **tất cả** 300 request, nên chỉ tăng ~ `0.03 × 1500 = 45` ms (đo 49.2 ms). Percentile thì chỉ nhìn vị trí xếp hạng: p99 là request thứ 99% khi xếp theo thời gian, nên chỉ cần > 1% request chậm là p99 rơi hẳn vào nhóm chậm và nhảy cả ~1.5 s.
- Với 3% chậm, p95 chưa thấy (243.2 ms) vì nhóm chậm chưa vượt 5%; với 10% chậm thì p95 cũng nhảy (1684.1 ms).
- **SLO nên đặt theo p95 hoặc p99 (percentile), kèm error rate**, không đặt theo average, vì percentile phản ánh nhóm người dùng bị chậm còn average thì che giấu họ. Chọn p95 hay p99 tuỳ mức "đuôi" cần bảo vệ; ở lab này p95 < 500 ms là SLO chính và p99 < 2000 ms là trần tham khảo (mục 1). Lưu ý thêm: không lấy trung bình của p95 giữa nhiều instance, mà phải gộp histogram rồi tính `histogram_quantile`.

Exit code của `load_test.py` trong các lần chạy mục 2 (đo bằng `$?` ngay sau mỗi lệnh): c=1 → 0, c=10 → 0, c=50 → 1 (error rate), c=100 → 1 (p95); `MOCK_SLOW_RATE=0` → 0, `0.03` → 0, `0.1` → 1 (p95). File JSON vẫn được lưu khi exit code là 1.

### C. Exercise 7.3: quality gate bằng exit code (README Bước 1, bài tập 4) và job CI

**Demo exit code** (không dùng `--out` nên không sinh thêm file report):

| Lệnh | Kết quả | Exit code |
|---|---|---|
| `python eval/run_eval.py --url http://localhost:8001 --baseline reports/eval_v2.json` (agent **v1** so với baseline v2) | Accuracy 4.3% (1/23); 20 câu regression (v2 từng đúng, v1 sai); `Quality gate ... ❌ FAIL` | **1** |
| `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85` (agent **v2 đã sửa KB**) | Accuracy 100.0% (23/23); `Quality gate (accuracy ≥ 85%, không regression): ✅ PASS` | **0** |

Cả hai exit code lấy từ `echo $?` ngay sau lệnh. `run_eval.py` kết thúc bằng `raise SystemExit(0 if gate_ok else 1)`, trong đó `gate_ok = accuracy >= min_accuracy and not regressions`: nên cả **accuracy thấp** lẫn **regression so với baseline** đều cho exit code 1.

**Job CI:** [`.github/workflows/eval.yml`](.github/workflows/eval.yml). Kích hoạt khi `pull_request` và `workflow_dispatch` (chạy tay); `working-directory` là `06-lab-complete/benchmark-observability/develop`; dùng `actions/checkout@v4` và `actions/setup-python@v5` (Python 3.11); `pip install -r requirements.txt`; bật `AGENT_VERSION=v2 MOCK_ERROR_RATE=0` (tắt lỗi ngẫu nhiên để gate không flaky) ở background trên cổng 8000; **chờ `/health` bằng vòng lặp retry** (tối đa 30 lần cách nhau 1 giây, hết thời gian thì in log agent và `exit 1`) thay vì `sleep` cố định; rồi chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`; step cuối (`if: always()`) tắt agent. Tôi kiểm file YAML parse được bằng `yaml.safe_load` (trigger `pull_request`, `workflow_dispatch`, 7 step) và **mô phỏng cục bộ** bằng script ngoài repo: đọc các step `run` từ chính file YAML và chạy tuần tự bằng `bash -eo pipefail` (bỏ qua 2 step `uses:` và thay `pip` bằng stub vì venv không có pip). Lần chạy thật chưa diễn ra trên GitHub vì tôi chưa push.

```text
[sim] skip action actions/checkout@v4
[sim] skip action actions/setup-python@v5

[sim] ### Cài dependencies
[stub pip] install -r requirements.txt (bỏ qua: đã cài sẵn trong venv)
[sim] step exit code = 0

[sim] ### Bật agent v2 ở background
[sim] step exit code = 0

[sim] ### Chờ agent sẵn sàng (/health)
agent sẵn sàng sau 2 lần thử
[sim] step exit code = 0

[sim] ### Quality gate (fail nếu accuracy < 85%)

🧪 Eval agent tại http://localhost:8000


══════════════════════════════════════════════════════════
  EVAL REPORT — agent v2
══════════════════════════════════════════════════════════
  Accuracy      : 100.0%  (23/23)
  Errors        : 0
  Latency (ms)  : p50=184.1  p95=213.8
  Avg tokens    : 117.5
  Total cost    : $0.000823   (cost / câu đúng: $0.00003580)
  Theo category :
    - benchmark      3/3  (100%)
    - cost           1/1  (100%)
    - deployment     3/3  (100%)
    - docker         2/2  (100%)
    - observability  6/6  (100%)
    - reliability    3/3  (100%)
    - scaling        3/3  (100%)
    - security       2/2  (100%)
──────────────────────────────────────────────────────────
  Quality gate (accuracy ≥ 85%, không regression): ✅ PASS
══════════════════════════════════════════════════════════

[sim] step exit code = 0

[sim] ### Tắt agent
[sim] step exit code = 0

[sim] JOB RESULT: SUCCESS (exit 0) -> PR check xanh
```

Mô phỏng một PR làm hỏng agent (thay `AGENT_VERSION=v2` bằng `v1` trong lệnh khởi động, tức mất retrieval):

```text
[sim] skip action actions/checkout@v4
[sim] skip action actions/setup-python@v5
[sim] ### Cài dependencies
[sim] step exit code = 0
[sim] ### Bật agent v2 ở background
[sim] step exit code = 0
[sim] ### Chờ agent sẵn sàng (/health)
[sim] step exit code = 0
[sim] ### Quality gate (fail nếu accuracy < 85%)
  Accuracy      : 4.3%  (1/23)
  Quality gate (accuracy ≥ 85%, không regression): ❌ FAIL
[sim] step exit code = 1
[sim] ### Tắt agent
[sim] step exit code = 0
[sim] JOB RESULT: FAILED (exit 1) -> PR check đỏ
```

**Exit code chặn merge như thế nào:** GitHub Actions chạy mỗi step `run` bằng shell với `-e`, step nào thoát với mã khác 0 thì step đó fail và các step sau bị bỏ qua (trừ step có `if: always()`), job `eval` có kết luận **failure**, và status check `eval` của Pull Request hiện dấu đỏ. Chỉ riêng dấu đỏ chưa cấm bấm merge. Phải bật **branch protection** cho nhánh chính: Settings → Branches → Branch protection rule → **Require status checks to pass before merging** → chọn check `eval` (tên job). Khi đó nút merge bị khoá cho tới khi gate xanh, tức PR làm accuracy giảm dưới 85% hoặc gây regression so với bản trước không thể vào nhánh chính. (Cần thêm `--baseline` trỏ tới một report đã commit mới bắt được regression; job hiện tại chỉ chặn theo accuracy < 85%, đúng yêu cầu bài.)

### D. Exercise 7.3: sửa Knowledge Base, bằng chứng không regression

Hai entry thêm vào cuối `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (viết bằng lời của tôi, không chép lời giải mẫu):

```python
    # --- Exercise 7.3: bổ sung cho 2 câu v2 trả lời sai (scaling-03, security-02) ---
    (["hpa", "kubernetes"],
     "HPA (Horizontal Pod Autoscaler) của Kubernetes tự tăng hoặc giảm số pod theo mức dùng CPU "
     "và memory của pod; ngoài ra còn có thể scale theo custom metrics như số request mỗi giây "
     "hay độ dài hàng đợi."),
    (["jwt"],
     "JWT là một token tự mô tả: bên trong có thông tin người dùng và thời điểm hết hạn, được ký "
     "bằng chữ ký số nên server chỉ cần kiểm tra chữ ký là tin được, không phải tra database. "
     "API key thì khác: là chuỗi bí mật cố định, không tự hết hạn, muốn vô hiệu phải thu hồi thủ công."),
]
```

Chọn trigger cẩn thận vì `retrieve_context` lấy `top_k=1` theo số keyword khớp, entry mới không được cướp câu hỏi khác. Trước khi chọn, tôi đếm trong dataset: `hpa` và `kubernetes` chỉ có ở `scaling-03`; `jwt` chỉ có ở `security-02`. Tôi tránh các trigger rộng như `token` (đã là trigger của entry chi phí LLM nên sẽ tranh điểm với nó) và `api key` (khớp thêm cả những câu về xác thực nói chung). Rồi chạy script so sánh (đặt ngoài repo) `retrieve_context` cho cả 23 câu của dataset (và 6 câu của `load_test.py`) trên KB gốc (18 entry, lấy từ bản trước khi sửa) và KB mới (20 entry):

```text
KB entries: before=18 after=20
id             changed?  before ok  after ok
basic-01       -         False      False
docker-01      -         True       True
docker-02      -         True       True
probe-01       -         True       True
probe-02       -         True       True
reliability-01 -         True       True
config-01      -         True       True
security-01    -         True       True
security-02    CHANGED   False      True
scaling-01     -         True       True
scaling-02     -         True       True
scaling-03     CHANGED   False      True
bench-01       -         True       True
bench-02       -         True       True
obs-01         -         True       True
obs-02         -         True       True
obs-03         -         True       True
obs-04         -         True       True
obs-05         -         True       True
obs-06         -         True       True
slo-01         -         True       True
cost-01        -         True       True
cloud-01       -         True       True
changed ids: ['security-02', 'scaling-03']
load_test questions changed: []
OK: only scaling-03 and security-02 changed
```

(`basic-01` luôn "False" ở cột before/after vì không có entry nào khớp: nó được trả lời bằng `V1_RESPONSES["deploy"]`, câu này chứa đủ từ khoá và đúng ở cả v1 lẫn v2; script chỉ kiểm tài liệu retrieval.)

Đối chiếu KB giữa `develop/` và `production/` sau khi chép (so `KNOWLEDGE_BASE` trong hai module, cộng với `diff` hai file không ra khác biệt nào):

```text
len develop: 20 len production: 20
KNOWLEDGE_BASE identical: True
```

Kết quả eval cuối (lệnh đúng như CP7 bước 4): `Accuracy : 100.0% (23/23)`, `Câu được cải thiện : 2`, `Câu bị regression : 0`, `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS`, và `reports/eval_v2_fixed.json` đã tồn tại.

### E. Chẩn đoán điểm nghẽn ở c=100 (số liệu trong `reports/diag_cpu.json`)

Sau khi có bảng 2.1, tôi chạy lại c=50 và c=100 trên agent v2 (cấu hình mặc định, 300 request) để xem bên nào bị nghẽn. Script chẩn đoán đo hai thứ: CPU của process `load_test.py`, bằng `resource.getrusage(RUSAGE_CHILDREN)` quanh tiến trình con; và CPU của agent, bằng chênh lệch `process_cpu_seconds_total` ở `/metrics` trước và sau mỗi lần chạy. Kết quả ghi vào `reports/diag_cpu.json`, report load test tương ứng ghi vào `reports/diag_load_v2_c50.json` và `reports/diag_load_v2_c100.json`:

| Concurrency | RPS | avg (ms) | p95 (ms) | Client: wall (s) | Client: CPU user (s) | Client: CPU sys (s) | Agent: CPU (s) |
|---|---|---|---|---|---|---|---|
| 50 | 120.64 | 236.8 | 276.5 | 2.92 | 0.76 | 0.08 | 0.46 |
| 100 | 42.68 | 1482.6 | 4612.9 | 7.42 | 5.22 | 0.29 | 0.53 |

Lần chạy lại này tái hiện đúng hiện tượng ở bảng 2.1. Từ c=50 lên c=100, RPS giảm (120.64 → 42.68; bảng 2.1: 97.7 → 50.66) và latency tăng vọt, trong khi CPU của agent gần như không đổi (0.46 → 0.53 s). Còn CPU của client tăng gần 7 lần (0.76 → 5.22 s), chiếm phần lớn thời gian chạy. Các số này chỉ để giải thích, không thay cho số trong bảng 2.1; RPS lệch giữa hai lần chạy vì mỗi lần chỉ 300 request, có request chậm và lỗi ngẫu nhiên. Tôi chỉ khẳng định điều đo được: ở c=100 process client bận hơn nhiều so với process agent. Tôi chưa truy ra nguyên nhân bên trong `httpx` khiến CPU của client tăng mạnh như vậy.

### F. Đối chiếu số liệu

Quy ước làm tròn: giá trị lấy nguyên văn từ JSON (latency ms 1 chữ số thập phân, RPS 2 chữ số, `total_cost_usd` như JSON). Error rate = `error_rate` × 100 hiển thị 2 chữ số thập phân (JSON lưu 4 chữ số, ví dụ 0.0067 → 0.67%). Accuracy = `accuracy` × 100 làm tròn 1 chữ số (JSON: 0.0435, 0.913, 1.0). Cost / câu đúng hiển thị 8 chữ số thập phân (JSON dạng khoa học, ví dụ `3.639e-05` → 0.00003639). Các giá trị suy ra (tỉ lệ, chênh lệch, phần trăm) do script tính từ các giá trị JSON và làm tròn 2 chữ số (ms: 1 chữ số); chúng không có trường tương ứng trong JSON.

| Số trong báo cáo | File JSON | Trường |
|---|---|---|
| Bảng 2.1: RPS, p50, p95, p99, error rate, SLO (4 dòng) | `reports/load_v2_c{1,10,50,100}.json` | `rps`, `latency_ms.p50`, `latency_ms.p95`, `latency_ms.p99`, `error_rate`, `slo.passed` |
| Số lỗi 503 trong mục 2.1 | cùng các file trên | `status_codes` |
| Bảng 2.2: avg, p95, p99 (3 dòng) | `reports/load_v2_slow_{0,0.03,0.1}.json` | `latency_ms.avg`, `latency_ms.p95`, `latency_ms.p99` |
| Bảng mục 3: accuracy, tokens, cost, cost / câu đúng, gate | `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json` | `passed`, `total`, `accuracy`, `avg_tokens`, `total_cost_usd`, `cost_per_correct_usd`, `quality_gate.passed`, `quality_gate.min_accuracy`, `quality_gate.regressions` |
| Keyword thiếu của `scaling-03`, `security-02` | `reports/eval_v2.json` | `results[].missing_keywords` |
| p50 / p95 latency trong eval | ba file eval | `latency_ms.p50`, `latency_ms.p95` |
| Số liệu chẩn đoán c=50 / c=100 (đoạn "Cái gì bão hoà?" ở mục 2.1, Phụ lục E) | `reports/diag_cpu.json`, `diag_load_v2_c50.json`, `diag_load_v2_c100.json` | `runs[].rps`, `latency_avg_ms`, `latency_p95_ms`, `client_wall_s`, `client_user_cpu_s`, `client_sys_cpu_s`, `agent_cpu_s` |

Script đối chiếu tự động (`check_report.py`, đặt ngoài repo) đọc lại chính các bảng trong file này, so từng ô với JSON và in kết quả:

```text
Đã so 60 giá trị: khớp 60, lệch 0
KẾT QUẢ: TẤT CẢ KHỚP với JSON
```
