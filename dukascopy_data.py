#!/usr/bin/env python3
"""
Dukascopy historical data fetcher (zero external dependencies).
Downloads .bi5 files directly from Dukascopy's CDN, decompresses (LZMA),
and parses the binary tick / M1-candle format.

Compatible with Python 3.6+.

Usage: python3 dukascopy_data.py <symbol> <timestamp_ms> <timeframe>
  symbol       - e.g. EURUSD (no slash)
  timestamp_ms - event time in milliseconds since epoch
  timeframe    - t1 (tick) or m1 (1-minute candles)

Output: JSON to stdout
  {"status": "OK", "data": [...]}
"""

import sys
import os
import json
import gzip
import struct
import lzma
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

CDN_BASE = "http://datafeed.dukascopy.com/datafeed"
# Per-event cache: stores only the filtered rows for this event window.
# Raw CDN .bi5 files are downloaded to memory only — never written to disk.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "dukascopy")

# -- Symbol mapping: common name -> Dukascopy CDN symbol ---------------------
# The dropdown sends names like "US30", "SPX500", etc.
# Dukascopy's CDN uses names like "USA30IDXUSD", "USA500IDXUSD", etc.
# Forex pairs (e.g. EURUSD) need no mapping -- they pass through as-is.
SYMBOL_MAP = {
    # US indices
    "US30":      "USA30IDXUSD",
    "SPX500":    "USA500IDXUSD",
    "NAS100":    "USATECHIDXUSD",
    "US2000":    "USSC2000IDXUSD",
    # European indices
    "GER30":     "DEUIDXEUR",
    "GER40":     "DEUIDXEUR",
    "FRA40":     "FRAIDXEUR",
    "UK100":     "GBRIDXGBP",
    "ESP35":     "ESPIDXEUR",
    "EUSTX50":   "EUSIDXEUR",
    "ITA40":     "ITAIDXEUR",
    "NLD25":     "NLDIDXEUR",
    "SUI20":     "CHEIDXCHF",
    "POL20":     "PLNIDXPLN",
    # Asia-Pacific indices
    "JPN225":    "JPNIDXJPY",
    "AUS200":    "AUSIDXAUD",
    "HKG33":     "HKGIDXHKD",
    "CHN50":     "CHNIDXUSD",
    "SGP":       "SGDIDXSGD",
    # Africa indices
    "SA40":      "SOAIDXZAR",
    # Other indices
    "USDX":      "DOLLARIDXUSD",
    "VIX":       "VOLIDXUSD",
    # Metals
    "XAUUSD":    "XAUUSD",
    "XAGUSD":    "XAGUSD",
    "XPDUSD":    "XPDUSD",
    "XPTUSD":    "XPTUSD",
    # Energy
    "USOil":     "USCROUSD",
    "UKOil":     "UKCROUSD",
    "NGAS":      "NGASUSD",
    "Gasoil":    "DIESELCMDUSD",
    # Bonds
    "10USNOTE":  "USTBONDTRUSD",
    "UKGilt":    "UKGILTTRGBP",
    "USTBond":   "USTBONDTRUSD",
    # Soft commodities
    "Cocoa":     "COCOACMDUSD",
    "Coffee":    "COFFEECMDUSX",
    "Copper":    "COPPERCMDUSD",
    "Cotton":    "COTTONCMDUSX",
    "OJ":        "OJUICECMDUSX",
    "Soybean":   "SOYBEANCMDUSX",
    "Sugar":     "SUGARCMDUSD",
    # Crypto
    "BTCUSD":    "BTCUSD",
    "BCHUSD":    "BCHUSD",
}

# -- Point values (divisor to convert stored integers to price) ---------------
# Forex 5dp = 100000, JPY 3dp = 1000, indices 3dp = 1000, etc.
POINT_VALUES = {
    "USA30IDXUSD":    1000,
    "USA500IDXUSD":   1000,
    "USATECHIDXUSD":  1000,
    "USSC2000IDXUSD": 1000,
    "DEUIDXEUR":      1000,
    "FRAIDXEUR":      1000,
    "GBRIDXGBP":      1000,
    "ESPIDXEUR":      1000,
    "EUSIDXEUR":      1000,
    "ITAIDXEUR":      1000,
    "NLDIDXEUR":      1000,
    "CHEIDXCHF":      1000,
    "PLNIDXPLN":      1000,
    "JPNIDXJPY":      1000,
    "AUSIDXAUD":      1000,
    "HKGIDXHKD":      1000,
    "CHNIDXUSD":      1000,
    "SGDIDXSGD":      1000,
    "SOAIDXZAR":      1000,
    "DOLLARIDXUSD":   1000,
    "VOLIDXUSD":      1000,
    "XAUUSD":         1000,
    "XAGUSD":         100000,
    "XPDUSD":         1000,
    "XPTUSD":         1000,
    "USCROUSD":       1000,
    "UKCROUSD":       1000,
    "NGASUSD":        1000,
    "DIESELCMDUSD":   1000,
    "UKGILTTRGBP":    100000,
    "USTBONDTRUSD":   100000,
    "COCOACMDUSD":    1000,
    "COFFEECMDUSX":   100000,
    "COPPERCMDUSD":   100000,
    "COTTONCMDUSX":   100000,
    "OJUICECMDUSX":   100000,
    "SOYBEANCMDUSX":  100000,
    "SUGARCMDUSD":    1000,

    "BTCUSD":         10,
    "BCHUSD":         10,
}


def resolve_symbol(symbol):
    """Translate a common symbol name to the Dukascopy CDN symbol."""
    symbol = symbol.upper().replace("/", "")
    return SYMBOL_MAP.get(symbol, symbol)


def get_point_value(symbol):
    """Return the divisor to convert integer prices to decimal."""
    if symbol in POINT_VALUES:
        return POINT_VALUES[symbol]
    # Fallback rules for unmapped forex pairs
    if symbol.endswith("JPY"):
        return 1000
    return 100000


_debug_log = []


# ---------------------------------------------------------------------------
# Per-event cache helpers (tiny per-event .json.gz, no full .bi5 on disk)
# ---------------------------------------------------------------------------

def _event_cache_path(symbol, start_ts, end_ts, timeframe):
    """Return path for a per-event cache file (just the filtered rows)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    fname = "{}_{}_{}_{}.json.gz".format(symbol, timeframe, int(start_ts), int(end_ts))
    return os.path.join(CACHE_DIR, fname)


def _read_event_cache(symbol, start_ts, end_ts, timeframe):
    """Return cached row list or None on miss."""
    path = _event_cache_path(symbol, start_ts, end_ts, timeframe)
    if os.path.exists(path):
        try:
            with open(path, "rb") as fh:
                return json.loads(gzip.decompress(fh.read()).decode("utf-8"))
        except Exception:
            pass
    return None


def _write_event_cache(symbol, start_ts, end_ts, timeframe, rows):
    """Persist the filtered rows for this event window."""
    path = _event_cache_path(symbol, start_ts, end_ts, timeframe)
    try:
        payload = json.dumps(rows, separators=(",", ":")).encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(gzip.compress(payload, compresslevel=6))
    except Exception:
        pass


def download_bi5(url, max_retries=3):
    """Download a .bi5 file to memory and return the LZMA-decompressed bytes.
    Files are NOT cached to disk -- only the per-event filtered results are cached.
    Returns empty bytes on 404, timeout, or decompression failure."""

    import time
    import random

    req = Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    decompressed = b""

    for attempt in range(max_retries):
        try:
            resp = urlopen(req, timeout=30)
            data = resp.read()
            if not data:
                _debug_log.append("empty response: {}".format(url))
                break
            # Try standard LZMA/XZ decompression first
            try:
                decompressed = lzma.decompress(data)
            except lzma.LZMAError:
                pass
            if not decompressed:
                try:
                    decompressed = lzma.decompress(data, format=lzma.FORMAT_ALONE)
                except lzma.LZMAError:
                    pass
            if not decompressed:
                try:
                    decompressed = lzma.decompress(data, format=lzma.FORMAT_RAW,
                                                   filters=[{"id": lzma.FILTER_LZMA1}])
                except lzma.LZMAError as e:
                    _debug_log.append("LZMA fail {}: {} (raw_len={})".format(
                        url.split("/")[-1], e, len(data)))
            break  # successful fetch
        except HTTPError as e:
            if e.code == 404:
                return b""
            if e.code in (503, 502, 504, 429) and attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0.1, 1.0))
                continue
            _debug_log.append("HTTP {}: {}".format(e.code, url))
            return b""
        except (URLError, EOFError, OSError, TimeoutError) as e:
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0.1, 1.0))
                continue
            _debug_log.append("DL error: {} {}".format(url, e))
            return b""

    return decompressed


def _hour_range(start, end):
    """Yield each truncated-to-hour datetime between start and end."""
    t = start.replace(minute=0, second=0, microsecond=0)
    while t <= end:
        yield t
        t += timedelta(hours=1)


# -- tick data ----------------------------------------------------------------

def fetch_tick_data(symbol, event_dt):
    """Fetch tick data +-60 seconds around the event.

    CDN path : {SYMBOL}/{YEAR}/{MONTH_0:02d}/{DAY:02d}/{HOUR:02d}h_ticks.bi5
    Record   : 20 bytes  (>iiiff)
               int32 ms-offset-from-hour, int32 ask, int32 bid,
               float32 ask_vol, float32 bid_vol

    Caching: per-event .json.gz -- raw .bi5 files are NOT kept on disk.
    """
    point = get_point_value(symbol)
    start = event_dt - timedelta(seconds=60)
    end   = event_dt + timedelta(seconds=60)
    start_ts = start.timestamp()
    end_ts   = end.timestamp()

    # Per-event cache check
    cached = _read_event_cache(symbol, start_ts, end_ts, "t1")
    if cached is not None:
        return {"status": "OK", "data": cached}

    ticks = []
    for hour_dt in _hour_range(start, end):
        m0 = hour_dt.month - 1
        url = "{}/{}/{}/{:02d}/{:02d}/{:02d}h_ticks.bi5".format(
            CDN_BASE, symbol, hour_dt.year, m0, hour_dt.day, hour_dt.hour)

        raw = download_bi5(url)
        if not raw:
            continue

        rec_size = 20
        for i in range(len(raw) // rec_size):
            ms, ask_i, bid_i, _av, _bv = struct.unpack_from(">iiiff", raw, i * rec_size)
            tick_time = hour_dt + timedelta(milliseconds=ms)
            if tick_time < start or tick_time > end:
                continue

            dt_str = tick_time.strftime("%Y-%m-%d %H:%M:%S.") + \
                     "{:03d}000".format(tick_time.microsecond // 1000)
            ticks.append({
                "DateTime": dt_str,
                "Bid": round(bid_i / point, 6),
                "Ask": round(ask_i / point, 6),
            })

    _write_event_cache(symbol, start_ts, end_ts, "t1", ticks)
    return {"status": "OK", "data": ticks}


# -- M1 candle data -----------------------------------------------------------

def _day_range(start, end):
    """Yield each truncated-to-day datetime between start and end."""
    t = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while t <= end:
        yield t
        t += timedelta(days=1)


def fetch_m1_data(symbol, event_dt):
    """Fetch M1 BID candles -10 min to +120 min around the event.

    CDN path : {SYMBOL}/{YEAR}/{MONTH_0:02d}/{DAY:02d}/BID_candles_min_1.bi5
               (daily file - NOT per-hour)
    Record   : 24 bytes  (>iiiiif)
               int32 ms-offset-from-day-start, int32 open, int32 close,
               int32 low, int32 high, float32 volume

    Fallback: If BID_candles_min_1.bi5 is missing (current day not yet published),
              synthesize M1 candles from hourly tick files.

    Caching: per-event .json.gz -- raw .bi5 files are NOT kept on disk.
    """
    today_utc = datetime.now(timezone.utc).date()

    point = get_point_value(symbol)
    start = event_dt - timedelta(minutes=10)
    end   = event_dt + timedelta(minutes=120)
    start_ts = start.timestamp()
    end_ts   = end.timestamp()

    # Per-event cache check
    cached = _read_event_cache(symbol, start_ts, end_ts, "m1")
    if cached is not None:
        return {"status": "OK", "data": cached}

    candles = []
    for day_dt in _day_range(start, end):
        m0 = day_dt.month - 1
        url = "{}/{}/{}/{:02d}/{:02d}/BID_candles_min_1.bi5".format(
            CDN_BASE, symbol, day_dt.year, m0, day_dt.day)

        # For today's date, the file likely doesn't exist yet; 1 attempt only
        is_today = (day_dt.date() == today_utc)
        raw = download_bi5(url, max_retries=1 if is_today else 3)
        if raw:
            rec_size = 24
            for i in range(len(raw) // rec_size):
                ms, o, c, l, h, vol = struct.unpack_from(">iiiiif", raw, i * rec_size)
                candle_time = day_dt + timedelta(seconds=ms)
                if candle_time < start or candle_time > end:
                    continue

                dt_str = candle_time.strftime("%Y-%m-%d %H:%M:%S.") + \
                         "{:03d}000".format(candle_time.microsecond // 1000)
                candles.append({
                    "DateTime": dt_str,
                    "BidOpen":  round(o / point, 6),
                    "BidClose": round(c / point, 6),
                    "BidLow":   round(l / point, 6),
                    "BidHigh":  round(h / point, 6),
                })
        else:
            # Daily candle file not yet published -- synthesize from hourly tick files
            day_start = max(start, day_dt)
            day_end = min(end, day_dt + timedelta(days=1) - timedelta(microseconds=1))

            minute_buckets = {}
            for hour_dt in _hour_range(day_start, day_end):
                m0_h = hour_dt.month - 1
                h_url = "{}/{}/{}/{:02d}/{:02d}/{:02d}h_ticks.bi5".format(
                    CDN_BASE, symbol, hour_dt.year, m0_h, hour_dt.day, hour_dt.hour)
                h_raw = download_bi5(h_url)
                if not h_raw:
                    continue

                rec_size = 20
                for i in range(len(h_raw) // rec_size):
                    ms, _ask_i, bid_i, _av, _bv = struct.unpack_from(">iiiff", h_raw, i * rec_size)
                    tick_time = hour_dt + timedelta(milliseconds=ms)
                    if tick_time < start or tick_time > end:
                        continue

                    m_dt = tick_time.replace(second=0, microsecond=0)
                    bid = round(bid_i / point, 6)
                    if m_dt not in minute_buckets:
                        minute_buckets[m_dt] = {"open": bid, "high": bid, "low": bid, "close": bid}
                    else:
                        b = minute_buckets[m_dt]
                        if bid > b["high"]: b["high"] = bid
                        if bid < b["low"]:  b["low"]  = bid
                        b["close"] = bid

            for m_dt in sorted(minute_buckets.keys()):
                b = minute_buckets[m_dt]
                candles.append({
                    "DateTime": m_dt.strftime("%Y-%m-%d %H:%M:%S.000000"),
                    "BidOpen":  b["open"],
                    "BidClose": b["close"],
                    "BidLow":   b["low"],
                    "BidHigh":  b["high"],
                })

    _write_event_cache(symbol, start_ts, end_ts, "m1", candles)
    return {"status": "OK", "data": candles}


# -- main ---------------------------------------------------------------------

def main():
    if len(sys.argv) < 4:
        print(json.dumps({"status": "ERROR",
                          "data": "Usage: dukascopy_data.py <symbol> <timestamp_ms> <timeframe>"}))
        sys.exit(1)

    raw_symbol   = sys.argv[1].upper().replace("/", "")
    symbol       = resolve_symbol(raw_symbol)   # Map to Dukascopy CDN name
    timestamp_ms = int(sys.argv[2])
    timeframe    = sys.argv[3]

    # Convert ms epoch -> naive UTC datetime
    event_dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    event_dt = event_dt.replace(tzinfo=None)   # Dukascopy times are naive UTC

    try:
        if timeframe == "t1":
            result = fetch_tick_data(symbol, event_dt)
        elif timeframe == "m1":
            result = fetch_m1_data(symbol, event_dt)
        else:
            result = {"status": "ERROR", "data": "Unknown timeframe: {}".format(timeframe)}
    except Exception as e:
        result = {"status": "ERROR", "data": "Exception: {}".format(str(e))}

    result["resolved_symbol"] = symbol
    if _debug_log:
        result["debug"] = _debug_log
    print(json.dumps(result))


if __name__ == "__main__":
    main()
