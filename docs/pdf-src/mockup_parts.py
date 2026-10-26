M = "\u2212"

VOTERS = [
    ("v1", "modelrouter", "jev-1.13", "izinkan", 0.71),
    ("v2", "experientiallabs", "clef", "izinkan", 0.64),
    ("v3", "experientiallabs", "jev-latest", "kecilkan", 0.40),
    ("v4", "xai-hm", "model chat (contoh)", "izinkan", 0.62),
    ("v5", "tiprouter", "model chat (contoh)", "izinkan", 0.69),
    ("v6", "nutaraline", "deepseek-v4.1-flash-1017", "izinkan", 0.74),
    ("v7", "lucif", "model chat (contoh)", "timeout", None),
]

NAV = ["Ringkas", "Grafik", "Aksi", "Swarm", "Atur"]


def gain(text):
    return '<span class="gain"><i class="ar up"></i>' + text + "</span>"


def loss(text):
    return '<span class="loss"><i class="ar dn"></i>' + text + "</span>"


def label(title):
    return '<div class="lab"><b>' + title + '</b><span class="ex">contoh data, bukan hasil nyata</span></div>'


def row(k, v, cls=""):
    return '<div class="r ' + cls + '"><span class="k">' + k + '</span><span class="v">' + v + "</span></div>"


def sec(title, meta=""):
    m = ' <span class="m">' + meta + "</span>" if meta else ""
    return '<h4 class="sec">' + title + m + "</h4>"


def meter(name, value, limit, pct, hot=False):
    cls = "sig" if hot else ""
    return (
        '<div class="meter"><div class="h"><span>' + name + '</span><b>' + value + ' dari batas ' + limit
        + '</b></div><div class="t"><i class="' + cls + '" style="width:' + str(pct) + '%"></i></div></div>'
    )


def switch(on, text):
    return '<span class="sw ' + ("on" if on else "") + '"><i></i>' + text + "</span>"


def phone(inner, nav_on, dark=False, age="4 dtk lalu", mode="Dry-run", link=True, h=620):
    dot = '<span class="dot"></span>' if link else '<span class="dot hol"></span>'
    nav = "".join('<span class="' + ("on" if n == nav_on else "") + '">' + n + "</span>" for n in NAV)
    return (
        '<div class="dev ui' + (" dark" if dark else "") + '" style="height:' + str(h) + 'px">'
        '<div class="sb"><span>09:41</span><span>PWA</span></div>'
        '<div class="top"><span class="mode">' + mode + "</span><span>" + dot + age + '</span><span class="sp"></span><span class="kb">Hentikan</span></div>'
        '<div class="scr">' + inner + '</div><div class="nav">' + nav + "</div></div>"
    )


def pc(title, html):
    return '<div class="pc">' + label(title) + html + "</div>"


def phones(*items):
    return '<div class="mkw"><div class="phones">' + "".join(items) + "</div></div>"


def desk(inner, nav_on, items=("Ringkas", "Grafik", "Aksi", "Swarm", "Posisi dan riwayat", "Atur"), age="3 dtk lalu"):
    nav = "".join('<div class="' + ("on" if n == nav_on else "") + '">' + n + "</div>" for n in items)
    return (
        '<div class="desk ui"><div class="top"><span class="mode">Dry-run</span><span><span class="dot"></span>' + age
        + '</span><span class="sp"></span><span>Bot A dan Bot B berjalan</span><span class="kb">Hentikan entry baru</span></div>'
        '<div class="dw"><div class="dn2">' + nav + '</div><div class="dm">' + inner + "</div></div></div>"
    )


def trace_svg(vals, w, h, ymin, ymax, limit, limit_label, ticks, second=None):
    pl, pr, pt, pb = 26, 6, 6, 14

    def X(i, n):
        return pl + (w - pl - pr) * i / (n - 1)

    def Y(v):
        return pt + (h - pt - pb) * (ymax - v) / (ymax - ymin)

    out = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;display:block" role="img">' % (w, h)]
    out.append('<rect width="%d" height="%d" fill="var(--panel)"/>' % (w, h))
    n = len(vals)
    for i, t in ticks:
        x = X(i, n)
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="var(--rule)" stroke-width="1"/>' % (x, pt, x, h - pb))
        out.append('<text x="%.1f" y="%d" font-size="9" fill="var(--ink2)" text-anchor="middle">%s</text>' % (x, h - 3, t))
    y0 = Y(0)
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--ink2)" stroke-width="1"/>' % (pl, y0, w - pr, y0))
    out.append('<text x="%d" y="%.1f" font-size="9" fill="var(--ink2)" text-anchor="end">0</text>' % (pl - 4, y0 + 3))
    yl = Y(limit)
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--sig)" stroke-width="2" stroke-dasharray="5 3"/>' % (pl, yl, w - pr, yl))
    out.append('<text x="%d" y="%.1f" font-size="9" fill="var(--loss)" text-anchor="end" font-weight="600">%s</text>' % (w - pr - 2, yl - 3, limit_label))
    if second:
        pts2 = " ".join("%.1f,%.1f" % (X(i, len(second)), Y(v)) for i, v in enumerate(second))
        out.append('<polyline points="%s" fill="none" stroke="var(--ink2)" stroke-width="1.6" stroke-dasharray="4 3"/>' % pts2)
    pts = " ".join("%.1f,%.1f" % (X(i, n), Y(v)) for i, v in enumerate(vals))
    out.append('<polyline points="%s" fill="none" stroke="var(--ink)" stroke-width="1.8" stroke-linejoin="round"/>' % pts)
    out.append('<circle cx="%.1f" cy="%.1f" r="3.2" fill="var(--ink)"/>' % (X(n - 1, n), Y(vals[-1])))
    out.append("</svg>")
    return "".join(out)


def candle_data(n=40, seed=11, entry=28):
    s = seed
    p = 0.0
    rows = []
    for i in range(n):
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        a = s / 0x7FFFFFFF - 0.5
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        b = s / 0x7FFFFFFF
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        c = s / 0x7FFFFFFF
        o = p
        cl = p + a * 0.9 + 0.03
        hi = max(o, cl) + b * 0.35
        lo = min(o, cl) - c * 0.35
        rows.append([o, hi, lo, cl])
        p = cl
    base = rows[entry][0]
    return [[v - base for v in r] for r in rows]


def ema(values, k):
    a = 2.0 / (k + 1)
    out = []
    e = values[0]
    for v in values:
        e = a * v + (1 - a) * e
        out.append(e)
    return out


def candles_svg(w, h, n=40, entry=28, exit_i=14, stop=-1.3):
    data = candle_data(n, 11, entry)
    ymax = max(r[1] for r in data) + 0.3
    ymin = min(min(r[2] for r in data), stop) - 0.3
    pl, pr, pt, pb = 30, 6, 8, 16

    def X(i):
        return pl + (w - pl - pr) * (i + 0.5) / n

    def Y(v):
        return pt + (h - pt - pb) * (ymax - v) / (ymax - ymin)

    cw = max(3.0, (w - pl - pr) / n * 0.62)
    out = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;display:block" role="img">' % (w, h)]
    out.append('<rect width="%d" height="%d" fill="var(--panel)"/>' % (w, h))
    for v in (-1, 0, 1):
        if ymin < v < ymax:
            y = Y(v)
            out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--rule)" stroke-width="1"/>' % (pl, y, w - pr, y))
            lab = ("+1%" if v == 1 else (M + "1%" if v == -1 else "0"))
            out.append('<text x="%d" y="%.1f" font-size="9" fill="var(--ink2)" text-anchor="end">%s</text>' % (pl - 4, y + 3, lab))
    for i, (o, hi, lo, cl) in enumerate(data):
        x = X(i)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--ink2)" stroke-width="1"/>' % (x, Y(hi), x, Y(lo)))
        top, bot = Y(max(o, cl)), Y(min(o, cl))
        fill = "var(--bg)" if cl >= o else "var(--ink2)"
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="var(--ink2)" stroke-width="1"/>' % (x - cw / 2, top, cw, max(1.0, bot - top), fill))
    e = ema([r[3] for r in data], 9)
    out.append('<polyline points="%s" fill="none" stroke="var(--ink)" stroke-width="1.8"/>' % " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(e)))
    ys = Y(stop)
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--sig)" stroke-width="2" stroke-dasharray="5 3"/>' % (pl, ys, w - pr, ys))
    out.append('<text x="%d" y="%.1f" font-size="9" fill="var(--loss)" text-anchor="end" font-weight="600">stop loss (contoh)</text>' % (w - pr - 2, ys - 3))
    xe, ye = X(entry), Y(data[entry][2]) + 5
    out.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="var(--ink)"/>' % (xe, ye, xe - 5, ye + 9, xe + 5, ye + 9))
    out.append('<text x="%.1f" y="%.1f" font-size="9" font-weight="600" fill="var(--ink)" text-anchor="middle">Masuk</text>' % (xe, ye + 20))
    xx, yx = X(exit_i), Y(data[exit_i][1]) - 5
    out.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="var(--ink)"/>' % (xx, yx, xx - 5, yx - 9, xx + 5, yx - 9))
    out.append('<text x="%.1f" y="%.1f" font-size="9" font-weight="600" fill="var(--ink)" text-anchor="middle">Keluar</text>' % (xx, yx - 12))
    out.append('<text x="%d" y="%d" font-size="9" fill="var(--ink2)" text-anchor="middle">1 kandel = 1 jam; sumbu: persen dari harga masuk</text>' % ((pl + w - pr) // 2, h - 3))
    out.append("</svg>")
    return "".join(out)


def dots_svg(w, voters, median, q1, q3):
    pl, pr = 10, 10

    def X(p):
        return pl + (w - pl - pr) * p

    levels = [16, 29, 42, 55]
    placed = [[] for _ in levels]
    dots = []
    for vid, prov, model, ans, p in sorted((v for v in voters if v[4] is not None), key=lambda v: v[4]):
        x = X(p)
        for li, lv in enumerate(levels):
            if all(abs(x - ox) >= 26 for ox in placed[li]):
                placed[li].append(x)
                dots.append((vid, ans, x, lv))
                break
    h = 118
    ax = 70
    out = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;display:block" role="img">' % (w, h)]
    out.append('<rect width="%d" height="%d" fill="var(--panel)"/>' % (w, h))
    out.append('<rect x="%.1f" y="6" width="%.1f" height="58" fill="var(--rule)"/>' % (X(q1), X(q3) - X(q1)))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="var(--ink2)" stroke-width="1"/>' % (pl, ax, w - pr, ax))
    for t, s in ((0, "0"), (0.5, "0,5"), (1, "1")):
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="var(--ink2)" stroke-width="1"/>' % (X(t), ax - 4, X(t), ax + 4))
        out.append('<text x="%.1f" y="%d" font-size="9" fill="var(--ink2)" text-anchor="middle">%s</text>' % (X(t), ax + 16, s))
    out.append('<line x1="%.1f" y1="6" x2="%.1f" y2="%d" stroke="var(--ink)" stroke-width="2.5"/>' % (X(median), X(median), ax))
    for vid, ans, x, lv in dots:
        fill = "var(--ink)" if ans == "izinkan" else "var(--bg)"
        out.append('<circle cx="%.1f" cy="%d" r="5" fill="%s" stroke="var(--ink)" stroke-width="1.6"/>' % (x, lv, fill))
        out.append('<text x="%.1f" y="%d" font-size="9" fill="var(--ink)" font-weight="600">%s</text>' % (x + 8, lv + 3, vid))
    out.append('<text x="%d" y="103" font-size="9" fill="var(--ink2)">Titik penuh = izinkan, kosong = kecilkan.</text>' % pl)
    out.append('<text x="%d" y="114" font-size="9" fill="var(--ink2)">Garis tebal = median, pita = selisih kuartil.</text>' % pl)
    out.append("</svg>")
    return "".join(out)


EQ_OK = [0, 0.05, -0.02, 0.08, 0.02, -0.05, -0.12, -0.08, -0.22, -0.15, -0.1, -0.18, -0.25, -0.3]
EQ_HOLD = [0, -0.1, -0.25, -0.2, -0.4, -0.55, -0.5, -0.7, -0.85, -0.8, -0.9, -0.95, -1.0, -1.0]
EQ_A = [0, 0.1, 0.05, 0.2, 0.15, 0.1, 0.25, 0.2, 0.1, 0.05, 0.12, 0.08, 0.15, 0.1]
EQ_B = [0, 0.08, 0.1, 0.18, 0.22, 0.16, 0.3, 0.26, 0.2, 0.15, 0.22, 0.2, 0.28, 0.25]
HOURS = [(0, "00"), (4, "04"), (8, "08"), (12, "12")]
