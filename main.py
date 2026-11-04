"""Kokka Stock API — bọc vnstock (thế hệ 5) thành REST cho app Flutter.

Schema JSON giữ nguyên như app Dart đang parse:
    {"data": [{symbol, name, exchange, type, price, change, changePercent, logo}]}
"""

import logging
import os
import re
import secrets
import threading
from typing import Annotated

from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from vnstock import Listing, Market

load_dotenv()

API_KEY = os.environ["STOCK_API_KEY"]  # không hardcode
# Giá từ price_board là VND (52700.0). Đặt PRICE_SCALE=0.001 nếu app Flutter
# đang hiển thị theo nghìn đồng (52.7).
PRICE_SCALE = float(os.getenv("PRICE_SCALE", "1"))
# Số mã tối đa mỗi request POST. vnstock cho phép tới 500 mã/lần gọi.
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "100"))
# Thời gian cache giá mỗi mã (giây).
QUOTE_TTL = int(os.getenv("QUOTE_CACHE_TTL", "5"))
# Khoá RIÊNG cho endpoint nội bộ (/api/v1/internal/*). STOCK_API_KEY nằm trong app
# Flutter nên ai tải app cũng trích được; không dùng nó để bảo vệ thao tác quản trị.
# Không đặt biến này thì các endpoint nội bộ bị tắt hẳn (trả 404).
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

app = FastAPI(title="Kokka Stock API")
log = logging.getLogger("uvicorn.error")

# Cache theo TỪNG MÃ, nên các request có danh sách mã khác nhau vẫn dùng chung dữ
# liệu và chỉ gọi upstream cho mã chưa có. Giá trị None = upstream không biết mã
# này (cache luôn để mã sai không đốt hạn mức vnstock mỗi lần gọi).
quote_cache = TTLCache(maxsize=4096, ttl=QUOTE_TTL)
# Tên công ty gần như không đổi -> cache riêng, 24 giờ
name_cache = TTLCache(maxsize=1, ttl=86_400)
# Bản sao cuối cùng lấy thành công của từng mã, dùng khi mọi nguồn đều lỗi
stale_cache = TTLCache(maxsize=4096, ttl=3_600)
# Endpoint chạy trong threadpool, TTLCache không an toàn khi dùng đa luồng
_lock = threading.Lock()

# Thứ tự thử nguồn dữ liệu. Nguồn mặc định của vnstock (kbs) thỉnh thoảng không
# trả dữ liệu; vci nhanh và ổn định hơn. Đổi bằng biến môi trường nếu cần.
SOURCES = [s.strip() for s in os.getenv("VNSTOCK_SOURCES", "vci,kbs").split(",") if s.strip()]

# Danh sách mã muốn hiển thị. Lấy hết ~1518 mã sẽ rất nặng cho app mobile.
WATCHLIST = ["VCB", "ACB", "TCB", "BID", "FPT", "HPG", "VIC", "MWG"]

SYMBOL_RE = re.compile(r"[A-Z0-9]{1,12}")


_MISS = object()


def _cache_get(cache: TTLCache, key):
    """Lấy `key` hoặc _MISS. PHẢI gọi trong `with _lock`.

    Không dùng `key in cache` rồi `cache[key]`: mục có thể hết hạn đúng giữa hai
    lệnh đó và `cache[key]` ném KeyError. Cache.get() của cachetools cũng viết
    theo kiểu đó nên không dùng được. Dùng _MISS thay None vì None là giá trị
    hợp lệ (mã upstream không biết).
    """
    try:
        return cache[key]
    except KeyError:
        return _MISS


def require_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    # Là dependency nên chạy TRƯỚC khi kiểm tra body: request thiếu khoá luôn
    # nhận 401, không lộ chi tiết lỗi validate (422) cho người lạ.
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_internal_key(x_internal_key: str | None = Header(default=None, alias="X-Internal-Key")):
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=404, detail="Not Found")  # tắt: như không tồn tại
    # compare_digest so sánh trong thời gian không phụ thuộc vị trí ký tự sai
    if not x_internal_key or not secrets.compare_digest(
        x_internal_key.encode(), INTERNAL_API_KEY.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid internal key")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # loại NaN


def _names() -> dict[str, str]:
    """symbol -> organ_name. Market.price_board không trả tên công ty."""
    with _lock:
        cached = _cache_get(name_cache, "names")
    if cached is not _MISS:
        return cached

    last_exc = None
    for source in SOURCES:
        try:
            df = Listing(source=source).all_symbols()
        except Exception as exc:
            last_exc = exc
            log.warning("names source %s failed: code=%s", source, getattr(exc, "code", None))
            continue
        names = dict(zip(df["symbol"], df["organ_name"]))
        with _lock:
            name_cache["names"] = names
        return names
    raise last_exc


def _fetch_board(symbols: list[str]):
    """Thử lần lượt từng nguồn; trả DataFrame hoặc None nếu mọi nguồn đều lỗi."""
    for source in SOURCES:
        try:
            return Market().price_board(symbols, source=source)
        except Exception as exc:
            # vnstock 5 nâng exception có kiểu; code/action nằm trong thuộc tính
            log.warning(
                "source %s failed: code=%s action=%s",
                source,
                getattr(exc, "code", None),
                getattr(exc, "action", None),
            )
    return None


def _to_item(row: dict, names: dict[str, str]) -> dict:
    sym = row.get("symbol")
    ref = _num(row.get("reference_price"))
    # close_price = 0 nghĩa là chưa khớp lệnh phiên này (hoặc mã bị đình chỉ).
    # Lấy giá tham chiếu thay vì ra -100%.
    price = _num(row.get("close_price")) or None
    if price is None:
        price = ref
    change = None if price is None or ref is None else price - ref
    pct = None if change is None or not ref else change / ref * 100

    return {
        "symbol":        sym,
        "name":          names.get(sym),
        "exchange":      row.get("exchange"),
        "type":          "STOCK",
        "price":         None if price is None else price * PRICE_SCALE,
        "change":        None if change is None else change * PRICE_SCALE,
        "changePercent": pct,
        "logo":          None,
    }


def get_prices(symbols: list[str]) -> tuple[list[dict], list[str]]:
    """Giá của `symbols` theo đúng thứ tự yêu cầu.

    Trả (items, not_found). Raise 502 khi upstream lỗi mà không có dữ liệu cũ
    để thay thế.
    """
    result = {}
    with _lock:
        for s in symbols:
            item = _cache_get(quote_cache, s)
            if item is not _MISS:
                result[s] = item
    missing = [s for s in symbols if s not in result]

    if missing:
        board = _fetch_board(missing)

        if board is None:
            stale = {}
            with _lock:
                for s in missing:
                    item = _cache_get(stale_cache, s)
                    if item is not _MISS:
                        stale[s] = item
            if len(stale) < len(missing):
                raise HTTPException(status_code=502, detail="Upstream data source failed")
            log.warning("all sources failed, serving stale data for %s", missing)
            result.update(stale)
        else:
            try:
                names = _names()
            except Exception:
                log.exception("company names fetch failed")
                names = {}

            fetched = {
                row["symbol"]: _to_item(row, names)
                for row in board.to_dict("records")
                if row.get("symbol")
            }
            with _lock:
                for s in missing:
                    item = fetched.get(s)  # None = upstream không có mã này
                    quote_cache[s] = item
                    if item:
                        stale_cache[s] = item
                    result[s] = item

    items = [result[s] for s in symbols if result.get(s)]
    not_found = [s for s in symbols if not result.get(s)]
    return items, not_found


class PricesRequest(BaseModel):
    symbols: Annotated[list[str], Field(min_length=1, max_length=MAX_SYMBOLS)]

    @field_validator("symbols")
    @classmethod
    def normalize(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            s = s.strip().upper()
            if not SYMBOL_RE.fullmatch(s):
                raise ValueError(f"invalid symbol: {s!r}")
            out.append(s)
        return list(dict.fromkeys(out))  # bỏ trùng, giữ thứ tự


@app.get("/api/v1/vietfin/symbols", dependencies=[Depends(require_key)])
def symbols():
    items, _ = get_prices(WATCHLIST)
    return {"data": items}


@app.post("/api/v1/get-prices", dependencies=[Depends(require_key)])
def get_prices_by_symbols(body: PricesRequest):
    items, not_found = get_prices(body.symbols)
    return {"data": items, "notFound": not_found}


def _snapshot(cache: TTLCache, only: set[str] | None = None) -> dict:
    """Ảnh chụp các mục CÒN HẠN của cache (mục hết hạn bị loại)."""
    with _lock:
        cache.expire()
        entries = {}
        for key in list(cache):
            if only is not None and key not in only:
                continue
            value = _cache_get(cache, key)
            if value is not _MISS:
                entries[key] = value
        return {
            "ttl": cache.ttl,
            "size": len(entries),
            "maxsize": cache.maxsize,
            "entries": entries,
        }


@app.get(
    "/api/v1/internal/cache",
    dependencies=[Depends(require_internal_key)],
    include_in_schema=False,
)
def read_cache(symbol: str | None = None):
    """Xem dữ liệu đang nằm trong cache. `?symbol=ACB` (hoặc `ACB,VCB`) để lọc.

    Giá trị `null` trong quote_cache = upstream không biết mã đó (cache âm).
    """
    only = None
    if symbol:
        only = {s.strip().upper() for s in symbol.split(",") if s.strip()}

    with _lock:
        names = _cache_get(name_cache, "names")
        names_info = {
            "ttl": name_cache.ttl,
            "loaded": names is not _MISS,
            "count": 0 if names is _MISS else len(names),
        }
    return {
        "quote_cache": _snapshot(quote_cache, only),
        "stale_cache": _snapshot(stale_cache, only),
        "name_cache": names_info,  # chỉ báo số lượng, không đổ cả ~1500 tên
        "sources": SOURCES,
    }


@app.delete(
    "/api/v1/internal/cache",
    dependencies=[Depends(require_internal_key)],
    include_in_schema=False,
)
def clear_cache():
    """Xoá toàn bộ cache. Request kế tiếp sẽ gọi lại vnstock.

    Lưu ý: stale_cache là lưới an toàn khi nguồn dữ liệu lỗi. Xoá nó lúc vnstock
    đang chập chờn thì các request sau đó trả 502 thay vì dữ liệu cũ.
    """
    with _lock:
        for cache in (quote_cache, stale_cache, name_cache):
            cache.expire()
        cleared = {
            "quote_cache": len(quote_cache),
            "stale_cache": len(stale_cache),
            "name_cache": len(name_cache),
        }
        for cache in (quote_cache, stale_cache, name_cache):
            cache.clear()
    log.warning("cache cleared: %s", cleared)
    return {"cleared": cleared}


@app.get("/health")
def health():
    return {"ok": True}
