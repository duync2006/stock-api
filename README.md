# Kokka Stock API

REST API bọc thư viện [vnstock](https://vnstocks.com) thế hệ 5, phục vụ app Flutter Kokka.

## Endpoint

| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/health` | Healthcheck, không cần khoá |
| GET | `/api/v1/vietfin/symbols` | Bảng giá watchlist. Cần header `X-API-Key` |

```json
{"data": [{"symbol": "VCB", "name": "Ngân hàng TMCP Ngoại thương Việt Nam",
           "exchange": "HOSE", "type": "STOCK", "price": 56300.0,
           "change": -900.0, "changePercent": -1.57, "logo": null}]}
```

## Chạy local

vnstock 5 không có trên PyPI, nên `--extra-index-url` là bắt buộc:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt \
    --extra-index-url https://vnstocks.com/api/packages
cp .env.example .env     # rồi đặt STOCK_API_KEY là một chuỗi ngẫu nhiên
.venv/bin/uvicorn main:app --reload --port 8000
```

## Biến môi trường

| Biến | Bắt buộc | Mô tả |
| --- | --- | --- |
| `STOCK_API_KEY` | có | Khoá app Flutter gửi qua header `X-API-Key` |
| `PRICE_SCALE` | không | Mặc định `1` (giá VND). Đặt `0.001` nếu app hiển thị nghìn đồng |
| `VNSTOCK_API_KEY` | không | Khoá vnstock. Không có thì chạy ở cấp Khách, hạn mức thấp |

## Deploy

- Docker: [DEPLOY.md](DEPLOY.md)
- systemd trên EC2: [DEPLOY-SYSTEMD.md](DEPLOY-SYSTEMD.md)

## Lưu ý

Cache là `TTLCache` 60 giây trong tiến trình, nên chạy **1 worker**. Nhiều worker
sẽ có nhiều cache riêng và tốn hạn mức vnstock gấp số worker.
