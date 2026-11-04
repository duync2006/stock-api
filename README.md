# Kokka Stock API

REST API bọc thư viện [vnstock](https://vnstocks.com) thế hệ 5, phục vụ app Flutter Kokka.

## Endpoint

| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/health` | Healthcheck, không cần khoá |
| GET | `/api/v1/vietfin/symbols` | Bảng giá watchlist. Cần header `X-API-Key` |

| POST | `/api/v1/get-prices` | Giá theo danh sách mã trong body. Cần header `X-API-Key` |

```json
{"data": [{"symbol": "VCB", "name": "Ngân hàng TMCP Ngoại thương Việt Nam",
           "exchange": "HOSE", "type": "STOCK", "price": 56300.0,
           "change": -900.0, "changePercent": -1.57, "logo": null}]}
```

### POST `/api/v1/get-prices`

```bash
curl -X POST localhost:8000/api/v1/get-prices \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"symbols": ["ACB", "VCB"]}'
```

- `symbols`: 1 đến `MAX_SYMBOLS` mã (mặc định 100), chỉ gồm chữ và số. Chữ thường được đổi
  thành chữ hoa, mã trùng được bỏ, thứ tự trả về theo thứ tự gửi lên.
- Response giống endpoint GET, thêm `notFound`: các mã upstream không có. Mã sai không
  gây lỗi, chỉ nằm trong `notFound`.
- Mã lỗi: thiếu hoặc sai khoá trả `401`; body sai (rỗng, quá nhiều mã, ký tự lạ) trả `422`;
  nguồn dữ liệu lỗi mà chưa từng có bản cũ của mã đó trả `502`.

## Chạy local

vnstock 5 không có trên PyPI, nên `--extra-index-url` là bắt buộc:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt \
    --extra-index-url https://vnstocks.com/api/packages
cp .env.example .env     # rồi đặt STOCK_API_KEY là một chuỗi ngẫu nhiên
.venv/bin/uvicorn main:app --reload --port 8000
```

### Endpoint nội bộ cho dev (xem và xoá cache)

Chỉ bật khi đặt `INTERNAL_API_KEY`; không đặt thì trả `404`. Dùng header riêng
`X-Internal-Key`, **không** dùng `X-API-Key` của app. Không hiện trong `/docs`.

| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/api/v1/internal/cache` | Xem dữ liệu đang cache. `?symbol=ACB,VCB` để lọc |
| DELETE | `/api/v1/internal/cache` | Xoá toàn bộ cache (giá, bản dự phòng, tên công ty) |

```bash
IK=$(sed -n 's/^INTERNAL_API_KEY=//p' .env)
curl -s -H "X-Internal-Key: $IK" localhost:8000/api/v1/internal/cache
curl -s -X DELETE -H "X-Internal-Key: $IK" localhost:8000/api/v1/internal/cache
```

Gọi **trực tiếp trên server** hoặc qua SSH tunnel. Khối `/stock/api/v1/internal/` trong
[nginx-stock.conf.snippet](nginx-stock.conf.snippet) chặn nó khỏi Internet nên qua domain sẽ ra `404`.
Xoá `stale_cache` lúc vnstock đang lỗi thì request sau trả `502` thay vì dữ liệu cũ.

## Biến môi trường

| Biến | Bắt buộc | Mô tả |
| --- | --- | --- |
| `STOCK_API_KEY` | có | Khoá app Flutter gửi qua header `X-API-Key` |
| `PRICE_SCALE` | không | Mặc định `1` (giá VND). Đặt `0.001` nếu app hiển thị nghìn đồng |
| `INTERNAL_API_KEY` | không | Khoá endpoint nội bộ. Không đặt thì các endpoint đó tắt |
| `MAX_SYMBOLS` | không | Số mã tối đa mỗi request POST, mặc định `100` |
| `QUOTE_CACHE_TTL` | không | Giây cache giá mỗi mã, mặc định `5` |
| `VNSTOCK_SOURCES` | không | Thứ tự thử nguồn dữ liệu, mặc định `vci,kbs` |
| `VNSTOCK_API_KEY` | không | Khoá vnstock. Không có thì chạy ở cấp Khách, hạn mức thấp |

## Deploy

- Docker: [DEPLOY.md](DEPLOY.md)
- systemd trên EC2: [DEPLOY-SYSTEMD.md](DEPLOY-SYSTEMD.md)

## Lưu ý

Cache là `TTLCache` 60 giây trong tiến trình, nên chạy **1 worker**. Nhiều worker
sẽ có nhiều cache riêng và tốn hạn mức vnstock gấp số worker.
