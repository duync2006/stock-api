# vnstock 5 phát hành wheel manylinux_2_17 (glibc). KHÔNG dùng alpine (musl)
# -> pip sẽ không tìm được wheel và build fail.
FROM python:3.13-slim

# HOME phải trỏ về thư mục của user 'app' vì vnstock lưu khoá đã mã hoá
# và định danh thiết bị ở ~/.vnstock
ENV HOME=/home/app \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 app

WORKDIR /app

# vnstock 5 không có trên PyPI -> phải có --extra-index-url, nếu không
# pip lấy vnstock 4.x từ PyPI và code thế hệ 5 sẽ lỗi.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
        --extra-index-url https://vnstocks.com/api/packages

COPY main.py .

RUN mkdir -p /home/app/.vnstock && chown -R app:app /home/app /app
USER app

EXPOSE 8000

# slim không có curl; dùng urllib cho gọn
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else sys.exit(1)"

# 1 worker là cố ý: TTLCache nằm trong tiến trình, mỗi worker có cache riêng
# -> N worker = N lần gọi upstream = tốn N lần hạn mức vnstock.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
