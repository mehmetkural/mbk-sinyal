#!/usr/bin/env python3
"""
MBK Sinyal Tarayıcı — TradingView'sız sürüm
UT Bot + Linear Regression Candles + USD hacim şartı + 2 saatlik onay
Binance herkese açık verisiyle çalışır, sinyali ntfy'a gönderir. Emir göndermez.

Kullanım:
  python3 mbk_scanner.py            # bir tarama yap (zamanlayıcı bunu çağırır)
  python3 mbk_scanner.py --test     # ntfy'a deneme bildirimi gönder
  python3 mbk_scanner.py --gecmis   # son ~2 günün sinyallerini listele (bildirim göndermez)
Yalnızca Python 3 standart kütüphanesini kullanır.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
# GitHub Actions'ta kanal adı gizli tutulur (repo secret NTFY_TOPIC)
if os.environ.get("NTFY_TOPIC"):
    CONFIG["ntfy_topic"] = os.environ["NTFY_TOPIC"]
STATE_FILE = HERE / "state.json"
LOG_FILE = HERE / "sinyaller.log"

BINANCE = CONFIG.get("binance_url", "https://data-api.binance.vision")
UA = {"User-Agent": "mbk-sinyal/1.0"}


# ---------------- yardımcılar ----------------
def http_json(url, data=None, timeout=20):
    body = None
    headers = dict(UA)
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def klines(symbol, interval, limit=500):
    raw = http_json(f"{BINANCE}/api/v3/klines?symbol={urllib.parse.quote(symbol)}&interval={interval}&limit={limit}")
    now_ms = int(time.time() * 1000)
    rows = [r for r in raw if int(r[6]) < now_ms]  # yalnızca kapanmış mumlar
    return {
        "t_all": [int(r[0]) for r in raw],  # açık mum dahil
        "t": [int(r[0]) for r in rows],
        "o": [float(r[1]) for r in rows],
        "h": [float(r[2]) for r in rows],
        "l": [float(r[3]) for r in rows],
        "c": [float(r[4]) for r in rows],
        "qv": [float(r[7]) for r in rows],  # USDT cinsinden hacim
    }


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------- Pine eşdeğerleri ----------------
NA = None


def linreg(src, length):
    """ta.linreg(src, length, 0)"""
    out = [NA] * len(src)
    n = length
    xs = list(range(n))
    sx = sum(xs)
    sxx = sum(x * x for x in xs)
    den = n * sxx - sx * sx
    for i in range(n - 1, len(src)):
        ys = src[i - n + 1: i + 1]
        sy = sum(ys)
        sxy = sum(x * y for x, y in zip(xs, ys))
        if den == 0:
            out[i] = ys[-1]
            continue
        slope = (n * sxy - sx * sy) / den
        intercept = (sy - slope * sx) / n
        out[i] = intercept + slope * (n - 1)
    return out


def sma(src, length):
    out = [NA] * len(src)
    for i in range(len(src)):
        win = src[max(0, i - length + 1): i + 1]
        if i >= length - 1 and all(v is not None for v in win):
            out[i] = sum(win) / length
    return out


def ema(src, length):
    out = [NA] * len(src)
    a = 2 / (length + 1)
    prev = None
    for i, v in enumerate(src):
        if v is None:
            continue
        prev = v if prev is None else a * v + (1 - a) * prev
        out[i] = prev
    return out


def atr(h, l, c, length):
    """ta.atr = RMA(true range)"""
    tr = []
    for i in range(len(c)):
        if i == 0:
            tr.append(h[i] - l[i])
        else:
            tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    out = [NA] * len(c)
    if len(c) < length:
        return out
    val = sum(tr[:length]) / length
    out[length - 1] = val
    for i in range(length, len(c)):
        val = (val * (length - 1) + tr[i]) / length
        out[i] = val
    return out


def ut_stop(src, atr_vals, key):
    ts = [NA] * len(src)
    prev = 0.0
    for i in range(len(src)):
        s, a = src[i], atr_vals[i]
        if s is None or a is None:
            continue
        n_loss = key * a
        s1 = src[i - 1] if i > 0 and src[i - 1] is not None else s
        if s > prev and s1 > prev:
            v = max(prev, s - n_loss)
        elif s < prev and s1 < prev:
            v = min(prev, s + n_loss)
        elif s > prev:
            v = s - n_loss
        else:
            v = s + n_loss
        ts[i] = v
        prev = v
    return ts


def compute(k, cfg):
    lo, lh, ll, lc = (linreg(k[x], cfg["lr_len"]) for x in ("o", "h", "l", "c"))
    mode = cfg["kaynak"]
    if mode == "linreg":
        src = lc
    elif mode == "heikin":
        src = [(o + h + l + c) / 4 for o, h, l, c in zip(k["o"], k["h"], k["l"], k["c"])]
    else:
        src = list(k["c"])
    a = atr(k["h"], k["l"], k["c"], cfg["atr_per"])
    ts = ut_stop(src, a, cfg["key"])
    sig = sma(lc, cfg["sig_len"]) if cfg["sig_sma"] else ema(lc, cfg["sig_len"])
    return {"src": src, "ts": ts, "lc": lc, "lo": lo, "sig": sig}


def ok(*vals):
    return all(v is not None for v in vals)


def signals_for(symbol, cfg, last_n):
    k = klines(symbol, cfg["tf"])
    hk = klines(symbol, cfg["htf"])
    hk_t_all = hk["t_all"]
    c = compute(k, cfg)
    hc = compute(hk, cfg)
    out = []
    n = len(k["c"])
    for i in range(max(1, n - last_n), n):
        src, ts, lc, sig = c["src"], c["ts"], c["lc"], c["sig"]
        if not ok(src[i], ts[i], src[i - 1], ts[i - 1]):
            continue
        ut_buy = src[i] > ts[i] and src[i - 1] <= ts[i - 1]
        ut_sell = src[i] < ts[i] and ts[i - 1] <= src[i - 1]
        if not (ut_buy or ut_sell):
            continue
        side = "AL" if ut_buy else "SAT"
        reasons = []
        if cfg["lr_filtre"] and ok(lc[i], sig[i]):
            if (ut_buy and not lc[i] > sig[i]) or (ut_sell and not lc[i] < sig[i]):
                reasons.append("LinReg filtresi")
        vol = k["qv"][i]
        if cfg["hacim_modu"] == "24s":
            bars = max(1, round(86400 / tf_seconds(cfg["tf"])))
            vol = sum(k["qv"][max(0, i - bars + 1): i + 1])
        if cfg["hacim_sarti"] and vol < cfg["min_hacim_usd"]:
            reasons.append(f"hacim {vol:,.0f}$ < {cfg['min_hacim_usd']:,.0f}$")
        ut_d, lr_d = None, None
        if cfg["htf_onay"]:
            # 2S yönü: içinde bulunulan 2S mumundan bir önceki kapanmış mum
            idx = None
            for j, t in enumerate(hk_t_all):
                if t <= k["t"][i]:
                    idx = j
            if idx is not None and 0 <= idx - 1 < len(hk["t"]):
                j = idx - 1
                if ok(hc["src"][j], hc["ts"][j], hc["lc"][j], hc["sig"][j]):
                    ut_d = 1 if hc["src"][j] > hc["ts"][j] else -1
                    lr_d = 1 if hc["lc"][j] > hc["sig"][j] else -1
            want = 1 if ut_buy else -1
            m = cfg["htf_tip"]
            if ut_d is None:
                passed = False
            elif m == "ut":
                passed = ut_d == want
            elif m == "linreg":
                passed = lr_d == want
            else:
                passed = ut_d == want and lr_d == want
            if not passed:
                reasons.append("2S onay yok")
        out.append({
            "symbol": symbol, "side": side, "bar_open": k["t"][i],
            "close": k["c"][i], "stop": ts[i], "vol": vol,
            "htf": (ut_d, lr_d), "filtered": reasons,
        })
    return out


def tf_seconds(tf):
    unit = tf[-1]
    n = int(tf[:-1])
    return n * {"m": 60, "h": 3600, "d": 86400}[unit]


def fmt_price(p):
    if p >= 100:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.8f}".rstrip("0")


def push(sig, cfg):
    is_buy = sig["side"] == "AL"
    htf_txt = f"{cfg['htf']} {'yukarı' if is_buy else 'aşağı'}" if cfg["htf_onay"] else "kapalı"
    msg = (f"Fiyat: {fmt_price(sig['close'])}\n"
           f"UT stop: {fmt_price(sig['stop'])}\n"
           f"Hacim $: {sig['vol']:,.0f}\n"
           f"Onay: {htf_txt}")
    tv_tf = str(tf_seconds(cfg["tf"]) // 60)
    payload = {
        "topic": cfg["ntfy_topic"],
        "title": f"{sig['side']} {sig['symbol']} ({cfg['tf']})",
        "message": msg,
        "tags": ["green_circle", "chart_with_upwards_trend"] if is_buy else ["red_circle", "chart_with_downwards_trend"],
        "priority": 4,
        "click": f"https://www.tradingview.com/chart/?symbol=BINANCE:{sig['symbol']}&interval={tv_tf}",
    }
    http_json(cfg.get("ntfy_url", "https://ntfy.sh"), payload)


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


STABLES = {"USDC", "FDUSD", "TUSD", "DAI", "BUSD", "USDP", "PAX", "EUR", "EURI", "AEUR", "GBP", "TRY", "BRL",
           "USDE", "USD1", "RLUSD", "XUSD", "BFUSD", "PYUSD", "U", "PAXG", "WBTC", "WBETH", "BNSOL"}


def resolve_symbols(cfg):
    """semboller = "TUMU" -> Binance'teki tüm aktif spot USDT pariteleri (stabil/sarılı coinler hariç).
    24 saatlik hacmi hacim eşiğinin altında kalanlar baştan atlanır (o coin'de şart zaten sağlanamaz)."""
    sem = cfg["semboller"]
    if isinstance(sem, list):
        return sem
    info = http_json(f"{BINANCE}/api/v3/exchangeInfo?permissions=SPOT", timeout=60)
    syms = {x["symbol"] for x in info["symbols"]
            if x.get("status") == "TRADING" and x.get("quoteAsset") == "USDT"
            and x.get("baseAsset") not in STABLES and x.get("isSpotTradingAllowed", True)}
    total = len(syms)
    if cfg.get("hacim_sarti"):
        tick = http_json(f"{BINANCE}/api/v3/ticker/24hr?type=MINI", timeout=60)
        qv = {t["symbol"]: float(t.get("quoteVolume") or 0) for t in tick}
        syms = {x for x in syms if qv.get(x, 0) >= cfg["min_hacim_usd"]}
    print(f"Binance USDT pariteleri: {total}, 24s hacmi eşiği geçen: {len(syms)}")
    return sorted(syms)


def main():
    cfg = CONFIG
    args = sys.argv[1:]
    if "--test" in args:
        syms = resolve_symbols(cfg)
        http_json(cfg.get("ntfy_url", "https://ntfy.sh"), {
            "topic": cfg["ntfy_topic"], "title": "MBK Sinyal test",
            "message": f"Tarayıcı çalışıyor. İzlenen sembol sayısı: {len(syms)}",
            "tags": ["white_check_mark"], "priority": 3})
        print("Test bildirimi gönderildi.")
        return
    history = "--gecmis" in args
    last_n = 200 if history else 3
    state = load_state()
    syms = resolve_symbols(cfg)

    from concurrent.futures import ThreadPoolExecutor
    def work(sym):
        try:
            return sym, signals_for(sym, cfg, last_n), None
        except Exception as e:
            return sym, [], e
    with ThreadPoolExecutor(max_workers=int(cfg.get("paralel", 8))) as ex:
        results = list(ex.map(work, syms))

    new = []
    errors = 0
    for sym, sigs, err in results:
        if err:
            errors += 1
            log(f"HATA {sym}: {err}")
            continue
        for s in sigs:
            when = time.strftime("%d.%m %H:%M", time.localtime(s["bar_open"] / 1000))
            tag = "GEÇTİ" if not s["filtered"] else "elendi: " + ", ".join(s["filtered"])
            if history:
                if not s["filtered"] or "--hepsi" in args:
                    print(f"{when}  {s['side']:3} {sym:14} {fmt_price(s['close']):>14}  hacim {s['vol']:>14,.0f}$  2S(ut,lr)={s['htf']}  {tag}")
                continue
            if s["filtered"]:
                continue
            key = f"{sym}:{s['side']}:{s['bar_open']}"
            if state.get(sym) == key:
                continue
            new.append((s, key, when))

    sent = 0
    limit = int(cfg.get("tekil_bildirim_limiti", 8))
    ntfy = cfg.get("ntfy_url", "https://ntfy.sh")
    try:
        if len(new) <= limit:
            for s, key, when in new:
                push(s, cfg)
                state[s["symbol"]] = key
                sent += 1
                log(f"GÖNDERİLDİ {s['side']} {s['symbol']} {when} fiyat={fmt_price(s['close'])} hacim={s['vol']:,.0f}$")
        else:
            # Çok sinyal varsa tek tek bildirim yerine hacme göre sıralı tek özet gönder
            new.sort(key=lambda x: -x[0]["vol"])
            lines = [f"{s['side']:3} {s['symbol']:<12} {fmt_price(s['close'])}  hacim {s['vol']/1e6:,.1f}M$" for s, _, _ in new[:40]]
            if len(new) > 40:
                lines.append(f"... ve {len(new) - 40} sinyal daha")
            al = sum(1 for s, _, _ in new if s["side"] == "AL")
            http_json(ntfy, {"topic": cfg["ntfy_topic"],
                             "title": f"{len(new)} sinyal ({cfg['tf']}): {al} AL / {len(new) - al} SAT",
                             "message": "\n".join(lines), "tags": ["bell"], "priority": 4})
            for s, key, when in new:
                state[s["symbol"]] = key
            sent = len(new)
            log(f"ÖZET GÖNDERİLDİ: {len(new)} sinyal")
    except Exception as e:
        log(f"ntfy HATA: {e}")
    if not history:
        STATE_FILE.write_text(json.dumps(state, indent=1))
        log(f"tarama bitti: {len(syms)} sembol, {errors} hata, {sent} sinyal bildirildi")


if __name__ == "__main__":
    main()
