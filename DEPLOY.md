# Deploy Kokka Stock API bằng Docker trên EC2

## 1. Chuẩn bị trên EC2

Amazon Linux 2023:

```bash
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user   # đăng xuất/đăng nhập lại cho có hiệu lực
```

Ubuntu 24.04:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
```

## 2. Đưa code lên và tạo .env

Chỉ cần 4 tệp: `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `main.py`.
**Không** copy `.env` của máy dev lên — tạo khoá riêng cho production:

```bash
umask 077
printf 'STOCK_API_KEY=%s\n' "$(openssl rand -hex 24)" > .env
# Nếu app Flutter hiển thị giá theo nghìn đồng:
# echo 'PRICE_SCALE=0.001' >> .env
```

Lấy lại khoá để cấu hình cho app Flutter: `cat .env`

## 3. Chạy

```bash
docker compose up -d --build
docker compose logs -f api        # Ctrl+C để thoát
curl -s localhost:8000/health
curl -s -H "X-API-Key: $(sed -n 's/^STOCK_API_KEY=//p' .env)" \
     localhost:8000/api/v1/vietfin/symbols
```

## 4. Khoá vnstock trên server

Server là **một thiết bị khác** với máy dev của bạn. Hai cách:

**Cách A — biến môi trường (khuyên dùng cho container).** `VNSTOCK_API_KEY` được
vnstock ưu tiên cao nhất, không cần chạy `register` trong container:

```bash
read -rs VNSTOCK_API_KEY && echo "VNSTOCK_API_KEY=$VNSTOCK_API_KEY" >> .env && unset VNSTOCK_API_KEY
docker compose up -d
```
(`read -rs` không in khoá ra màn hình và không vào shell history)

**Cách B — đăng nhập một lần vào volume:**

```bash
docker compose run --rm api vnstock register
```
Khoá được cất dạng mã hoá trong volume `vnstock-auth`, các lần restart sau dùng lại.
Đừng xoá volume này, vì mỗi container mới không có nó sẽ bị tính là một thiết bị mới
và ăn thêm một suất trong giới hạn thiết bị của tài khoản.

Kiểm tra cấp đang dùng: `docker compose exec api vnstock status`

Không có khoá thì API vẫn chạy ở cấp Khách, nhưng hạn mức rất thấp — xem mục 6.

## 5. TLS và Security Group

`docker-compose.yml` chỉ bind `127.0.0.1:8000`, nên cổng 8000 **không** ra Internet.
Đặt nginx hoặc ALB phía trước để làm HTTPS. Security Group chỉ mở 443 (và 22 cho IP
của bạn); **không** mở 8000.

Nếu muốn phơi trực tiếp (chỉ để test), sửa thành `"8000:8000"` và mở 8000 trong
Security Group — khi đó khoá `X-API-Key` là lớp bảo vệ duy nhất, và traffic là HTTP
chưa mã hoá.

## 6. Hạn mức vnstock — đọc trước khi mở cho người dùng thật

- Cache trong `main.py` là 60 giây, nên mức gọi upstream tối đa là **1440 lượt/ngày**
  nếu có người dùng poll liên tục. Cấp Khách không đủ cho mức đó; cấp Cộng đồng
  (miễn phí) cao hơn.
- Dockerfile cố ý chạy `--workers 1`. `TTLCache` nằm trong tiến trình, mỗi worker có
  cache riêng, nên N worker = N lần gọi upstream = tốn N lần hạn mức. Cần nhiều
  worker thì phải chuyển cache ra Redis trước.
- Theo dõi: `docker compose exec api vnstock usage --detail`
- Lỗi upstream bất thường: `docker compose exec api vnstock doctor`

## 7. Cập nhật

```bash
docker compose build --pull --no-cache api && docker compose up -d
```

Mỗi bản vnstock 5 chỉ dùng được 365 ngày kể từ ngày phát hành (bản 5.2.1 hết hạn
27/10/2027), sau đó các lệnh lấy dữ liệu báo `VNSTOCK_RELEASE_EXPIRED`. Rebuild định
kỳ là đủ để tránh.
