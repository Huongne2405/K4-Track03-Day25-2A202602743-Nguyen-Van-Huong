# Bước 2 — Kết quả baseline ShopAgent

Chạy `make baseline PY=.venv/bin/python` với cấu hình hiện tại (seed 25).
Nguồn: `gameday/naive.json` và `gameday/naive_G2_overload_storm_timeseries.csv`.
Đây là kết quả NaiveClient; chưa phải kết quả của ResilientClient.

| Băng | Availability | p95 lượt thành công (s) | Amplification | Retry ratio | Recovery (s) | Tiêu chí không đạt |
|---|---:|---:|---:|---:|---:|---|
| G1 | 71,94% | 7,157 | 7,738 | 6,738 | 4 | Availability, retry-after, amplification |
| G2 | 45,60% | 15,034 | 9,904 | 8,904 | 155 | Availability, amplification, recovery |
| G3 | 100% | 4,768 | 1,164 | 0,164 | 0 | Retry ratio |
| G4 | 100% | 13,764 | 1,004 | 0,004 | 0 | p95 |
| G5 | 36,99% | 5,359 | 17,030 | 16,030 | Không xác định | Retry lỗi 400, availability |
| G6 | 51,70% | 4,836 | 12,344 | 11,344 | 0 | Availability |

Tổng: **0/6 băng PASS**. Recovery = 0 không chứng minh hệ thống chịu được sự cố:
metric này chỉ kiểm tra cửa sổ sau thời điểm provider hồi phục.

## Số liệu G2 để dùng cho postmortem

- Tổng lượt user: **2.362**; thành công: **1.077**; thất bại: **1.285** (54,40%).
- Logical LLM call: **3.481**; attempt: **34.475**, tất cả gửi tới `alpha`.
- Amplification: **9,904**, vượt mục tiêu ≤ 1,6.
- p95 của lượt thành công: **15,034 s**; cost/good turn: **4,627** đơn vị mô phỏng.
- Lỗi: **26.298** rate limit, **3.194** overloaded, **2.737** client timeout, **5** api error.
- Vi phạm retry-after: **28.381**.
- Provider phục hồi ở **t=300**; recovery **155 s**, vượt mục tiêu ≤ 30 s.
- Cửa sổ 30 giây đầu tiên đạt ≥95% LLM call thành công bắt đầu tại **t=455**.
  Đây là metric theo cửa sổ, không có nghĩa mọi call tại riêng giây 455 đều thành công.

| t (giây ảo) | Sự kiện / quan sát | Bằng chứng |
|---:|---|---|
| 120 | Alpha còn 25% năng lực | Cấu hình băng G2, kéo dài đến t=300 |
| 290 | Tải attempt tăng cao, call hoàn tất đều lỗi tại giây này | 147 attempt alpha; 0/3 call thành công |
| 300 | Alpha hồi phục năng lực, client vẫn không thành công tại giây này | 115 attempt alpha; 0/5 call thành công |
| 440 | Sau hồi phục 140 giây, vẫn có giây không call nào thành công | 11 attempt alpha; 0/3 call thành công |
| 455 | Bắt đầu cửa sổ đạt tiêu chí recovery | `recovery_s=155`, tính từ t=300 |

**Trigger:** alpha mất 75% năng lực trong 180 giây.

**Cơ chế làm sự cố kéo dài:** client timeout nhưng server vẫn xử lý request cũ;
client tiếp tục retry với delay cố định, không breaker và không fallback.
Request cũ cộng với retry mới duy trì hàng đợi, timeout và rate limit ngay cả sau
khi năng lực provider được khôi phục. Đây là vòng lặp metastable failure.

**Hướng kiểm chứng sau khi triển khai reliability layer:** G2 availability ≥95%,
amplification ≤1,6, recovery ≤30 s và primary_share_after_restore ≥80%.
Giữ số liệu baseline này để so sánh với ResilientClient ở Bước 9.
