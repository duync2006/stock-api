"""Kokka Stock API — bọc vnstock (thế hệ 5) thành REST cho app Flutter.

Schema JSON giữ nguyên như app Dart đang parse:
    {"data": [{symbol, name, exchange, type, price, change, changePercent, logo}]}
"""

import logging
import os

from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from vnstock import Listing, Market

load_dotenv()

API_KEY = os.environ["STOCK_API_KEY"]  # không hardcode
# Giá từ price_board là VND (52700.0). Đặt PRICE_SCALE=0.001 nếu app Flutter
# đang hiển thị theo nghìn đồng (52.7).
PRICE_SCALE = float(os.getenv("PRICE_SCALE", "1"))

app = FastAPI(title="Kokka Stock API")
log = logging.getLogger("uvicorn.error")

# Cache 60s: sàn VN không nhảy giá nhanh hơn thế, và tránh bị upstream chặn IP
quote_cache = TTLCache(maxsize=4, ttl=60)
# Tên công ty gần như không đổi -> cache riêng, 24 giờ
name_cache = TTLCache(maxsize=1, ttl=86_400)

# Danh sách mã muốn hiển thị. Lấy hết ~1518 mã sẽ rất nặng cho app mobile.
WATCHLIST = ["VCB", "ACB", "TCB", "BID", "FPT", "HPG", "VIC", "MWG"]


def verify(key: str | None):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # loại NaN


def _names() -> dict[str, str]:
    """symbol -> organ_name. Market.price_board không trả tên công ty."""
    if "names" not in name_cache:
        df = Listing().all_symbols()
        name_cache["names"] = dict(zip(df["symbol"], df["organ_name"]))
    return name_cache["names"]


@app.get("/api/v1/vietfin/symbols")
def symbols(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    verify(x_api_key)

    if "symbols" in quote_cache:
        return {"data": quote_cache["symbols"]}

    try:
        board = Market().price_board(WATCHLIST)
        names = _names()
    except Exception as exc:
        # vnstock 5 nâng exception có kiểu; code/action nằm trong thuộc tính
        log.exception(
            "upstream fetch failed: code=%s action=%s",
            getattr(exc, "code", None),
            getattr(exc, "action", None),
        )
        raise HTTPException(status_code=502, detail="Upstream data source failed")

    out = []
    for row in board.to_dict("records"):
        sym = row.get("symbol")
        price = _num(row.get("close_price"))
        ref = _num(row.get("reference_price"))
        change = None if price is None or ref is None else price - ref
        pct = None if change is None or not ref else change / ref * 100

        out.append({
            "symbol":        sym,
            "name":          names.get(sym),
            "exchange":      row.get("exchange"),
            "type":          "STOCK",
            "price":         None if price is None else price * PRICE_SCALE,
            "change":        None if change is None else change * PRICE_SCALE,
            "changePercent": pct,
            "logo":          None,
        })

    quote_cache["symbols"] = out
    return {"data": out}


@app.get("/health")
def health():
    return {"ok": True}
