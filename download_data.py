#!/usr/bin/env python3

import calendar
import csv
import gzip
import io
import mysql.connector
import requests as req
import datetime as dt
import os
import json
import tqdm
from compress_pickle import dump, load
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import sys

mydb = mysql.connector.connect(
    host="10.1.0.114",
    user="newsreader",
    password="kee1234!",
    database="newsreader"
)

DATA_URL = "http://10.1.0.115:5000/hist/"
DATA_ROOT = '/opt/nrreport_data/'
INSTRUMENTS_JSON = '/var/www/newschartsweb/instruments.json'

# FXCM public candledata CDN (free, no login needed, M1 only)
FXCM_CANDLE_BASE = "https://candledata.fxcorporate.com"
# Per-event cache: stores only the relevant ~130 candles for a specific event window
FXCM_CDN_CACHE = '/opt/newschartsweb/cache/fxcm_m1'

c = mydb.cursor()
utc = dt.timezone.utc

with open(INSTRUMENTS_JSON, 'r') as f:
    insts = json.load(f)
symbols = insts.keys()


# ---------------------------------------------------------------------------
# FXCM CDN M1 helpers
# ---------------------------------------------------------------------------

def _resolve_fxcm_symbol(symbol):
    """Convert symbol to FXCM CDN format: no slash, uppercase. e.g. EUR/USD -> EURUSD."""
    return symbol.strip().replace('/', '').upper()


def _get_fxcm_week(event_dt):
    """
    Calculate the FXCM trading week number.
    FXCM trading weeks start on Sunday ~21:00 UTC.
    For Sunday, the week number matches the upcoming isocalendar week.
    For Mon-Sat, the week number is isocalendar week - 1.
    """
    y, w, d = event_dt.isocalendar()
    if d == 7:  # Sunday
        return y, w
    fx_w = w - 1
    if fx_w < 1:
        prev_y = y - 1
        last_day = dt.datetime(prev_y, 12, 28)
        _, fx_w, _ = last_day.isocalendar()
        return prev_y, fx_w
    return y, fx_w


def _event_cache_path(symbol_raw, start_ts, end_ts):
    """Path for the per-event candle cache file (tiny, just the relevant window)."""
    symbol = _resolve_fxcm_symbol(symbol_raw)
    os.makedirs(FXCM_CDN_CACHE, exist_ok=True)
    return os.path.join(FXCM_CDN_CACHE, f"{symbol}_{start_ts}_{end_ts}.json.gz")


def _read_event_cache(symbol_raw, start_ts, end_ts):
    """Return cached candle list if it exists, or None on miss."""
    path = _event_cache_path(symbol_raw, start_ts, end_ts)
    if os.path.exists(path):
        try:
            with open(path, 'rb') as fh:
                return json.loads(gzip.decompress(fh.read()).decode('utf-8'))
        except Exception:
            pass
    return None


def _write_event_cache(symbol_raw, start_ts, end_ts, candles):
    """Persist just the filtered candles for this event window."""
    path = _event_cache_path(symbol_raw, start_ts, end_ts)
    try:
        payload = json.dumps(candles, separators=(',', ':')).encode('utf-8')
        with open(path, 'wb') as fh:
            fh.write(gzip.compress(payload, compresslevel=6))
    except Exception:
        pass


def _fetch_cdn_week_to_memory(symbol_cdn, year, week):
    """
    Download one week of M1 candles from FXCM CDN into memory only.
    The weekly file is NOT saved to disk — only the filtered per-event
    result is cached (see _write_event_cache).
    Returns raw gzip bytes, or None on failure.
    """
    url = f"{FXCM_CANDLE_BASE}/m1/{symbol_cdn}/{year}/{week}.csv.gz"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urlopen(request, timeout=15) as resp:
            content = resp.read()
            if content and len(content) > 100:
                return content
    except HTTPError as exc:
        if exc.code != 404:
            pass  # 404 = no data for this week; other errors are transient
    except Exception:
        pass
    return None


def fetch_fxcm_cdn_m1(symbol_raw, start_ts, end_ts):
    """
    Fetch M1 candles from FXCM free CDN for the UTC range [start_ts, end_ts] (Unix seconds).

    Caching strategy:
      1. Per-event cache (~130 candles, tiny .json.gz) — instant on repeat requests.
      2. CDN download to memory — first request only; weekly file is NOT kept on disk.

    Returns list of candle dicts matching the existing format, or None if unavailable.
    """
    # 1. Check per-event cache first — fastest path, avoids any CDN traffic
    cached = _read_event_cache(symbol_raw, start_ts, end_ts)
    if cached is not None:
        return cached if cached else None

    symbol_cdn = _resolve_fxcm_symbol(symbol_raw)

    # Collect all FXCM trading weeks that might cover the requested range
    weeks_needed = set()
    cursor_dt = dt.datetime.utcfromtimestamp(start_ts)
    end_dt_obj = dt.datetime.utcfromtimestamp(end_ts)
    while cursor_dt <= end_dt_obj + dt.timedelta(days=7):
        weeks_needed.add(_get_fxcm_week(cursor_dt))
        cursor_dt += dt.timedelta(days=7)

    all_candles = []

    for year, week in sorted(weeks_needed):
        gz_bytes = _fetch_cdn_week_to_memory(symbol_cdn, year, week)
        if not gz_bytes:
            continue

        try:
            raw_csv = gzip.decompress(gz_bytes).decode('utf-8', errors='replace')
            reader = csv.DictReader(io.StringIO(raw_csv))

            for row in reader:
                dt_str = row.get('DateTime', '')
                if not dt_str:
                    continue

                # CDN format: 'MM/DD/YYYY HH:MM:SS.mmm'
                try:
                    row_dt = dt.datetime.strptime(dt_str, "%m/%d/%Y %H:%M:%S.%f")
                except ValueError:
                    try:
                        row_dt = dt.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                # Treat CDN datetimes as UTC for correct timestamp comparison
                row_ts = calendar.timegm(row_dt.timetuple())
                if start_ts <= row_ts <= end_ts:
                    bid_open  = float(row.get('BidOpen',  0) or 0)
                    bid_high  = float(row.get('BidHigh',  0) or 0)
                    bid_low   = float(row.get('BidLow',   0) or 0)
                    bid_close = float(row.get('BidClose', 0) or 0)
                    all_candles.append({
                        'DateTime': row_dt.strftime('%Y-%m-%d %H:%M:%S.000000'),
                        'BidOpen':  bid_open,
                        'BidHigh':  bid_high,
                        'BidLow':   bid_low,
                        'BidClose': bid_close,
                        # CDN includes Ask columns; fall back to Bid if absent
                        'AskOpen':  float(row.get('AskOpen',  0) or bid_open),
                        'AskHigh':  float(row.get('AskHigh',  0) or bid_high),
                        'AskLow':   float(row.get('AskLow',   0) or bid_low),
                        'AskClose': float(row.get('AskClose', 0) or bid_close),
                    })
        except Exception:
            continue

    # 2. Save just the relevant candles to per-event cache
    #    (empty list is also cached to avoid re-hitting CDN for known-missing data)
    _write_event_cache(symbol_raw, start_ts, end_ts, all_candles)

    return all_candles if all_candles else None


# ---------------------------------------------------------------------------
# Original download_data logic (unchanged)
# ---------------------------------------------------------------------------

def get_intervals(date, check=False):
    global c

    start_ts = dt.datetime.combine(date, dt.datetime.min.time(), tzinfo=utc)
    start = int(start_ts.timestamp()) * 1000
    end = start + 24*3600*1000

    c.execute("SELECT MIN(timestamp) as ts FROM ny_results_log "
              "WHERE (event_time >= %i AND event_time <= %i) "
              "GROUP BY event_time, news_id "
              "ORDER by ts ASC" % (start, end))

    res = c.fetchall()

    tick = []
    mins = []

    for x in res:
        t = x[0]
        t1sec = t // 1000
        t1min = (t1sec // 60) * 60

        ts = t1sec - 60
        te = t1sec + 60
        ms = t1min - 10*60
        me = t1min + 120*60

        if len(tick) == 0 or tick[-1][1] < ts:
            tick.append([ts, te])
        else:
            tick[-1][1] = te

        if len(mins) == 0 or mins[-1][1] < ms:
            mins.append([ms, me])
        else:
            mins[-1][1] = me

    if not check:
        print("%s: Num events %i, num tick intervals: %i, num min intervals: %i" %
              (date.strftime("%Y-%m-%d"), len(res), len(tick), len(mins)))

    return tick, mins


def get_data(symbol, interval, timeframe, retry=0):
    global insts

    assert timeframe == 't1' or timeframe == 'm1'
    assert symbol in insts

    frm = dt.datetime.fromtimestamp(
        interval[0], tz=utc).strftime("%m.%d.%Y %H:%M:%S")
    to = dt.datetime.fromtimestamp(
        interval[1], tz=utc).strftime("%m.%d.%Y %H:%M:%S")

    if retry >= 3:
        print("ERROR: Failed to get %s (%s) from %s to %s" %
              (symbol, timeframe, frm, to))
        return None

    data = {
        "symbol": insts[symbol],
        "timeFrom": frm,
        "timeTo": to,
        "action": "get",
        "timeframe": timeframe
    }

    resp = req.post(DATA_URL, json=data)

    if resp.status_code != 200:
        return get_data(symbol, interval, timeframe, retry + 1)

    j = resp.json()
    if j is None or j['status'] != 'OK':
        return get_data(symbol, interval, timeframe, retry + 1)

    return j['data']


def make_day_path(date):
    return '%s/%i/%s/' % (DATA_ROOT, date.year, date.strftime("%Y-%m-%d"))


def make_path(date, interval, symbol, timeframe):
    assert timeframe == 't1' or timeframe == 'm1'
    odir = '%s/%s_%i_to_%i/' % (make_day_path(date),
                                timeframe, interval[0], interval[1])
    os.makedirs(odir, exist_ok=True)

    fname = "%s.dat.gz" % (symbol)

    return odir + fname


def download_day(date, check=False):
    ticks, mins = get_intervals(date, check)

    args = []
    for s in symbols:
        for t in ticks:
            args.append((s, t, "t1"))

        for m in mins:
            args.append((s, m, "m1"))

    for arg in args if check else tqdm.tqdm(args, leave=False):
        sym, inter, tf = arg

        fout = make_path(date, inter, sym, tf)
        if os.path.exists(fout):
            continue

        jdat = get_data(sym, inter, tf)
        if jdat is None:
            continue

        dat = {}
        dat['ts'] = [dt.datetime.strptime(
            r['DateTime'], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=utc).timestamp() for r in jdat]

        if len(dat['ts']) == 0:
            continue

        if tf == 't1':
            dat['ask'] = [r['Ask'] for r in jdat]
            dat['bid'] = [r['Bid'] for r in jdat]
        elif tf == 'm1':
            dat['o'] = [r['BidOpen'] for r in jdat]
            dat['h'] = [r['BidHigh'] for r in jdat]
            dat['l'] = [r['BidLow'] for r in jdat]
            dat['c'] = [r['BidClose'] for r in jdat]

        dump(dat, fout)


def retrieve_data(args):
    sym = args[1]
    ts = int(args[2])
    tf = args[3]

    res = {}
    res['status'] = 'OK'
    res['data'] = []

    if tf == "t1":
        # round to 1 sec; interval is -60s to +60s
        t = ts // 1000
        start = t - 60
        end = t + 60
    elif tf == "m1":
        # round to 1 min; interval is -10min to +120min
        t = ts // 1000
        t = (t // 60) * 60
        start = t - 10*60
        end = t + 120*60
    else:
        res['status'] = 'ERROR: Invalid timeframe %s' % tf
        return json.dumps(res)

    dt_event = dt.datetime.fromtimestamp(t, tz=utc)
    path = make_day_path(dt_event.date())
    fpath = ''

    if os.path.exists(path):
        for d in os.listdir(path):
            fs = d.split('_')
            assert len(fs) == 4
            assert fs[2] == 'to'

            if fs[0] != tf:
                continue

            if int(fs[1]) <= start and int(fs[3]) >= end:
                # this is the range we want
                fpath = "%s/%s/%s.dat.gz" % (path, d, sym)
                break

    if fpath != '':
        dat = load(fpath)

        if len(dat['ts']) > 0:
            for i in range(len(dat['ts'])):
                t_row = dat['ts'][i]
                if t_row >= start and t_row <= end:
                    row = {}
                    row['DateTime'] = dt.datetime.fromtimestamp(
                        t_row, tz=utc).strftime("%Y-%m-%d %H:%M:%S.%f")
                    if tf == 't1':
                        row['Ask'] = dat['ask'][i]
                        row['Bid'] = dat['bid'][i]
                    elif tf == 'm1':
                        row['BidOpen']  = dat['o'][i]
                        row['BidHigh']  = dat['h'][i]
                        row['BidLow']   = dat['l'][i]
                        row['BidClose'] = dat['c'][i]

                    res['data'].append(row)

            if res['data']:
                return json.dumps(res)

    # ------------------------------------------------------------------
    # No local cache hit. For M1, try FXCM free CDN before giving up.
    # ------------------------------------------------------------------
    if tf == "m1":
        cdn_candles = fetch_fxcm_cdn_m1(sym, start, end)
        if cdn_candles:
            res['data'] = cdn_candles
            return json.dumps(res)

    res['status'] = 'no data'
    return json.dumps(res)


if __name__ == '__main__':
    if len(sys.argv) == 4:
        if sys.argv[1] == "check" or sys.argv[1] == "get-dates":
            start = dt.date.fromisoformat(sys.argv[2])
            end = dt.date.fromisoformat(sys.argv[3])

            if sys.argv[1] == "check":
                date_range = []
                d = end
                while d >= start:
                    date_range.append(d)
                    d -= dt.timedelta(days=1)

                for d in tqdm.tqdm(date_range):
                    download_day(d, check=True)

            elif sys.argv[1] == "get-dates":
                d = end
                while d >= start:
                    download_day(d)
                    d -= dt.timedelta(days=1)

        else:
            print(retrieve_data(sys.argv))

    elif len(sys.argv) == 3 and sys.argv[1] == "get":
        yr = int(sys.argv[2])
        today = dt.date.today() - dt.timedelta(days=1)
        start = dt.date(yr, 12, 31)

        if start > today:
            start = today

        end = dt.date(yr, 1, 1)

        print("Download from %s to %s" %
              (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))

        date = start
        while date >= end:
            download_day(date)
            date -= dt.timedelta(days=1)

    elif len(sys.argv) == 2 and sys.argv[1] == "update":
        date = dt.date.today()
        for i in range(7):
            date -= dt.timedelta(days=1)
            download_day(date)
