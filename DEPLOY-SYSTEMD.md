# Deploy không dùng Docker: clone từ GitHub + systemd trên EC2

Chạy uvicorn dưới systemd, nginx đứng trước làm HTTPS.

## 0. Tạo repo trên GitHub (làm trên máy Windows)

Thư mục `D:\example` là một repo git chưa có commit và chứa nhiều project khác,
nên **đừng** push nó. Tách backend thành repo riêng:

```powershell
cd D:\example\vnstock\kokka-stock-api
git init
git add .
git commit -m "Kokka Stock API: FastAPI wrapper for vnstock 5"
gh repo create kokka-stock-api --private --source . --push
```

`.gitignore` đã loại `.venv/`, `.env`, `__pycache__/`. Kiểm tra trước khi push:

```powershell
git status --short        # không được thấy .env
```

**Không bao giờ commit `.env`.** Nếu đã commit nhầm, đổi khoá mới chứ đừng chỉ xoá file.

## 1. Cài Python và nginx trên EC2

vnstock 5 cần Python **3.10 trở lên**. Kiểm tra trước:

```bash
python3 --version
```

Amazon Linux 2023 (thường có 3.11):

```bash
sudo dnf install -y python3 python3-pip git nginx
```

Ubuntu 24.04 (thường có 3.12):

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git nginx
```

Nếu `python3 -m venv` báo `ensurepip is not available` (Ubuntu), cài thêm
`python3-venv` đúng theo minor version, ví dụ `sudo apt install python3.12-venv`.

## 2. Tạo user riêng cho service

Không chạy service bằng `ec2-user` hay `root`:

```bash
sudo useradd --create-home --shell /usr/sbin/nologin kokka
```
(Amazon Linux dùng `--shell /sbin/nologin`)

## 3. Clone code vào /opt

```bash
sudo git clone https://github.com/<user>/kokka-stock-api.git /opt/kokka-stock-api
sudo chown -R kokka:kokka /opt/kokka-stock-api
```

Repo private thì dùng deploy key: tạo khoá trên server bằng
`sudo -u kokka ssh-keygen -t ed25519 -f /home/kokka/.ssh/id_ed25519 -N ""`,
dán phần `.pub` vào Settings → Deploy keys của repo, rồi clone qua URL dạng
`git@github.com:<user>/kokka-stock-api.git`.

## 4. Tạo venv và cài thư viện

vnstock 5 **không có trên PyPI**. Thiếu `--extra-index-url` là pip lấy vnstock 4.x
và code thế hệ 5 sẽ lỗi:

```bash
cd /opt/kokka-stock-api
sudo -u kokka python3 -m venv .venv
sudo -u kokka .venv/bin/python -m pip install -U pip
sudo -u kokka .venv/bin/python -m pip install -r requirements.txt \
     --extra-index-url https://vnstocks.com/api/packages
sudo -u kokka .venv/bin/python -c "import vnstock; print(vnstock.__version__)"   # phải in 5.x
```

## 5. Tạo .env trên server

Khoá production sinh ngay trên server, không mang `.env` của máy dev lên:

```bash
sudo -u kokka bash -c 'umask 077; printf "STOCK_API_KEY=%s\n" "$(openssl rand -hex 24)" > /opt/kokka-stock-api/.env'
sudo chmod 600 /opt/kokka-stock-api/.env
```

Nếu app Flutter hiển thị giá theo nghìn đồng, thêm `PRICE_SCALE=0.001` vào `.env`.

Lấy khoá để cấu hình cho app: `sudo cat /opt/kokka-stock-api/.env`

## 6. Khoá vnstock cho server

Server là **một thiết bị khác** với máy dev. Hai cách:

**Cách A — biến môi trường (gọn nhất).** `VNSTOCK_API_KEY` được vnstock ưu tiên
cao nhất, không cần `register`:

```bash
read -rs VNSTOCK_API_KEY
sudo -u kokka bash -c "echo 'VNSTOCK_API_KEY=$VNSTOCK_API_KEY' >> /opt/kokka-stock-api/.env"
unset VNSTOCK_API_KEY
```
`read -rs` không in khoá ra màn hình và không lưu vào shell history.

**Cách B — đăng nhập một lần, khoá cất dạng mã hoá ở /home/kokka/.vnstock:**

```bash
sudo -u kokka /opt/kokka-stock-api/.venv/bin/vnstock register
sudo -u kokka /opt/kokka-stock-api/.venv/bin/vnstock status
```

Không có khoá thì API vẫn chạy ở cấp Khách, hạn mức rất thấp — xem mục 10.

## 7. Bật systemd service

```bash
sudo cp /opt/kokka-stock-api/kokka-stock-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kokka-stock-api
sudo systemctl status kokka-stock-api --no-pager
```

Thử ngay trên server (uvicorn chỉ bind 127.0.0.1, chưa ra Internet):

```bash
curl -s localhost:8000/health
curl -s -H "X-API-Key: $(sudo sed -n 's/^STOCK_API_KEY=//p' /opt/kokka-stock-api/.env)" \
     localhost:8000/api/v1/vietfin/symbols
```

Xem log: `sudo journalctl -u kokka-stock-api -f`

## 8. nginx + HTTPS

`/etc/nginx/conf.d/kokka.conf`:

```nginx
server {
    listen 80;
    server_name api.ten-mien-cua-ban.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo nginx -t && sudo systemctl enable --now nginx
```

Cấp chứng chỉ (cần domain đã trỏ A record về IP của EC2):

```bash
sudo dnf install -y certbot python3-certbot-nginx     # Ubuntu: sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.ten-mien-cua-ban.com
```

Dùng ALB thay nginx cũng được: khi đó ALB làm TLS, target group trỏ vào cổng 8000
của instance, và `--host` trong unit phải đổi thành `0.0.0.0` để ALB gọi tới được
(lúc đó Security Group chỉ cho ALB truy cập cổng 8000, không mở ra Internet).

## 9. Security Group

- 443 từ `0.0.0.0/0`
- 80 từ `0.0.0.0/0` (để certbot xác thực và redirect)
- 22 chỉ từ IP của bạn
- **Không mở 8000**

## 10. Hạn mức vnstock

- Cache trong `main.py` là 60 giây → tối đa **1440 lượt gọi upstream/ngày** nếu app
  poll liên tục. Cấp Khách không đủ; cấp Cộng đồng (miễn phí) cao hơn.
- `--workers 1` trong unit là cố ý. Muốn nhiều worker thì phải chuyển `TTLCache`
  sang Redis trước, nếu không mỗi worker gọi upstream riêng.
- Theo dõi: `sudo -u kokka /opt/kokka-stock-api/.venv/bin/vnstock usage --detail`
- Lỗi lạ: `sudo -u kokka /opt/kokka-stock-api/.venv/bin/vnstock doctor`

## 11. Cập nhật code và thư viện

```bash
cd /opt/kokka-stock-api
sudo -u kokka git pull
sudo -u kokka .venv/bin/python -m pip install -U -r requirements.txt \
     --extra-index-url https://vnstocks.com/api/packages
sudo systemctl restart kokka-stock-api
```

Mỗi bản vnstock 5 chỉ dùng được 365 ngày kể từ ngày phát hành (5.2.1 hết hạn
27/10/2027), sau đó lệnh lấy dữ liệu báo `VNSTOCK_RELEASE_EXPIRED`. Cập nhật định kỳ
là đủ để tránh.
