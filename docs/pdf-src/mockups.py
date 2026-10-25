from mockup_parts import *


def chips(items, on):
    return '<div class="chips">' + "".join('<span class="' + ("on" if i == on else "") + '">' + i + "</span>" for i in items) + "</div>"


def stp(v):
    return '<span class="stp"><u>' + M + "</u>" + v + "<u>+</u></span>"


def dash_inner(hold):
    if hold:
        board = '<div class="board sig"><div class="w">Ditahan</div><div class="s">Rugi hari ini 1,0% menyentuh batas 1,0%. Entry baru ditahan; posisi terbuka tetap dijaga stop loss.</div></div>'
        tr = trace_svg(EQ_HOLD, 272, 84, -1.2, 0.2, -1.0, "batas harian " + M + "1,0%", HOURS)
        profit = row("Profit hari ini", loss(M + "Rp 20.000 (" + M + "1,0%) rugi"))
        meters = meter("Rugi harian", "1,0%", "1,0%", 100, True) + meter("Rugi total", "1,0%", "10,0%", 10)
        pos = row("BTC/IDR &middot; 1h", loss(M + "0,3% rugi")) + row("ETH/IDR &middot; 1h", loss(M + "0,5% rugi"))
    else:
        board = '<div class="board"><div class="w">Aman</div><div class="s">Rugi hari ini 0,3% dari batas 1,0%. Entry baru boleh dibuka.</div></div>'
        tr = trace_svg(EQ_OK, 272, 84, -1.2, 0.2, -1.0, "batas harian " + M + "1,0%", HOURS)
        profit = row("Profit hari ini", loss(M + "Rp 6.000 (" + M + "0,3%) rugi"))
        meters = meter("Rugi harian", "0,3%", "1,0%", 30) + meter("Rugi total", "0,3%", "10,0%", 3)
        pos = row("BTC/IDR &middot; 1h", gain("+0,4% untung")) + row("ETH/IDR &middot; 1h", loss(M + "0,2% rugi"))
    return (
        board + sec("Hari ini", "jejak per jam, persen dari modal") + '<div style="padding:0 12px">' + tr + "</div>" + profit + meters
        + sec("Posisi terbuka", "2 dari maks 3") + pos + sec("Bot")
        + row("Bot A &middot; aturan saja", "Dry-run") + row("Bot B &middot; aturan + swarm bayangan", "Dry-run")
        + row("Biaya LLM hari ini (informasi)", "Rp 410 &middot; 540 rb token", "sm")
    )


def g1():
    a = phone(dash_inner(False), "Ringkas")
    b = phone(dash_inner(True), "Ringkas", dark=True, age="2 dtk lalu")
    return phones(pc("Layar 1a. Dasbor, tema terang, keadaan aman", a), pc("Layar 1b. Dasbor, tema gelap (ikut sistem), keadaan ditahan", b))


def g2a():
    inner = (
        chips(["BTC/IDR", "ETH/IDR", "SOL/IDR"], 0)
        + sec("BTC/IDR &middot; 1h", "posisi terbuka")
        + '<div style="padding:0 12px">' + candles_svg(272, 236) + "</div>"
        + row("Masuk 14:00", gain("+0,4% untung"))
        + row("Keluar sebelumnya 03:00", gain("+0,7% untung"))
        + row("Indikator", "EMA 9 (garis tebal)", "sm")
        + '<div class="r sm"><span class="k">Penanda swarm</span>' + switch(True, "Aktif") + "</div>"
        + '<div class="r sm"><span class="k">Berita dan sentimen (nice-to-have)</span>' + switch(False, "Mati") + "</div>"
    )
    return phones(pc("Layar 2a. Grafik live (ponsel)", phone(inner, "Grafik")))


def g2b():
    left = (
        chips(["BTC/IDR", "ETH/IDR", "SOL/IDR"], 0)
        + sec("BTC/IDR &middot; 1h", "kandel diperbarui lewat WebSocket, data 3 dtk lalu")
        + '<div style="padding:0 14px 10px">' + candles_svg(470, 300, 52, 36, 18) + "</div>"
    )
    right = (
        sec("Penanda")
        + row("14:00 Masuk", gain("+0,4% untung"), "sm")
        + row("03:00 Keluar", gain("+0,7% untung"), "sm")
        + sec("Overlay")
        + '<div class="r sm"><span class="k">EMA 9</span>' + switch(True, "Aktif") + "</div>"
        + '<div class="r sm"><span class="k">Penanda swarm</span>' + switch(True, "Aktif") + "</div>"
        + '<div class="r sm"><span class="k">Berita dan sentimen (nice-to-have)</span>' + switch(False, "Mati") + "</div>"
        + sec("Sinyal strategi")
        + '<div class="note">Kandidat entry berikutnya dihitung saat kandel 1 jam menutup. Pratinjau sinyal di rentang waktu lain: nice-to-have.</div>'
    )
    inner = '<div class="cols"><div style="flex:1.75">' + left + "</div><div>" + right + "</div></div>"
    return '<div class="mkw">' + label("Layar 2b. Grafik live (desktop)") + desk(inner, "Grafik") + "</div>"


def feed(t, kind, msg, warn=False):
    return '<div class="f ' + ("warn" if warn else "") + '"><time>' + t + '</time><span><span class="kd">' + kind + "</span> " + msg + "</span></div>"


def g3_phone():
    inner = (
        chips(["Semua", "Order", "Swarm", "Risiko", "Sistem"], 0)
        + feed("14:02:11", "Swarm", "BTC/IDR: kuorum 6 dari 7, median 0,67, sebaran 0,08, keputusan izinkan (bayangan: hanya dicatat)")
        + feed("14:02:09", "Voter", "v7 lucif: waktu habis 30 dtk, dibuang untuk keputusan ini", True)
        + feed("14:02:08", "Strategi", "kandidat entry BTC/IDR 1h")
        + feed("13:58:40", "Order", "beli ETH/IDR terisi (dry-run)")
        + feed("13:30:00", "Risiko", "gerbang lolos: rugi harian 0,3% dari 1,0%, posisi 2 dari maks 3")
        + feed("13:00:00", "Sistem", "heartbeat bot A dan bot B normal")
        + feed("12:41:55", "Peringatan", "nutaraline membalas 429; voter v6 dibuang untuk keputusan ini", True)
        + feed("12:40:02", "Order", "keluar BTC/IDR (dry-run) " + gain("+0,7% untung"))
        + '<div class="note">Sambungan putus: tampilan menandai data basi lalu menyambung ulang dengan backoff.</div>'
    )
    return phone(inner, "Aksi", h=720)


def vtable(voters):
    rows = ""
    for vid, prov, model, ans, p in voters:
        pv = "dibuang" if p is None else ("%.2f" % p).replace(".", ",")
        rows += '<tr><td><b>' + vid + '</b></td><td class="w">' + prov + "<br><span style='color:var(--ink2)'>" + model + "</span></td><td>" + ans + '</td><td class="n">' + pv + "</td></tr>"
    return '<table class="tb"><tr><th></th><th>Provider dan model</th><th>Jawaban</th><th class="n">P(izinkan)</th></tr>' + rows + "</table>"


def g3_preview():
    inner = (
        chips(["Pratinjau", "Keputusan"], 0)
        + sec("SOL/IDR &middot; 1h", "kandidat entry 15:00, belum ada order")
        + sec("Voter A", "decision model")
        + vtable(VOTERS)
        + sec("Voter B", "prakiraan return")
        + row("Kronos mini", gain("+1,10%"), "sm")
        + row("Model dasar time series", gain("+0,95%"), "sm")
        + row("FreqAI (LightGBM)", gain("+0,40%"), "sm")
        + row("Median A &middot; selisih kuartil", "0,67 &middot; 0,08", "sm")
        + row("Kuorum", "6 dari 7 (min 5) terpenuhi", "sm")
        + '<div class="note" style="background:var(--panel);margin:6px 12px 0;padding:7px 9px;color:var(--ink)"><b>Hasil pratinjau: izinkan.</b> Mode shadow: hanya dicatat, tidak ada order. Ambang sebaran belum ditetapkan.</div>'
    )
    return phone(inner, "Swarm", h=720)


def g3():
    return phones(pc("Layar 3. Aksi live (feed waktu nyata)", g3_phone()), pc("Layar 4. Pratinjau kandidat entry beserta jawaban voter", g3_preview()))


def g4_swarm():
    q = [v for v in VOTERS]
    inner = (
        chips(["Pratinjau", "Keputusan"], 1)
        + sec("Keputusan terbaru")
        + row("14:00 BTC/IDR &middot; izinkan (bayangan)", gain("terbuka +0,4%"), "sm")
        + row("12:00 ETH/IDR &middot; lewati: sebaran besar", "bila dibuka " + loss(M + "0,6%") + "<br>lewati tepat", "sm")
        + row("09:00 SOL/IDR &middot; lewati: kuorum 4 dari 7", "bila dibuka " + gain("+0,3%") + "<br>lewati meleset", "sm")
        + row("06:00 BTC/IDR &middot; kecilkan", "belum dinilai", "sm")
        + sec("Keputusan 14:00 BTC/IDR")
        + '<div style="padding:0 12px">' + dots_svg(272, q, 0.665, 0.625, 0.705) + "</div>"
        + row("Median A &middot; selisih kuartil", "0,67 &middot; 0,08", "sm")
        + row("Kuorum", "6 dari 7 (min 5) terpenuhi", "sm")
        + row("Median B", gain("+0,95%") + " (3 dari 3 searah)", "sm")
        + row("Keputusan", "izinkan (bayangan)", "sm")
        + '<div class="note">Hasil sesudahnya dihitung dari harga: apakah entry yang dilewati ternyata rugi.</div>'
    )
    return phone(inner, "Swarm", h=770)


def g4_conf():
    inner = (
        chips(["Konfigurasi", "Provider", "Kontrol"], 0)
        + sec("Batas rugi", "turun langsung, naik dua langkah")
        + row("Harian", stp("1,0%") + ' <span class="k">Rp 20.000</span>', "sm")
        + row("Total", stp("10,0%") + ' <span class="k">Rp 200.000</span>', "sm")
        + row("Risiko per trade", stp("0,5%") + ' <span class="k">Rp 10.000</span>', "sm")
        + sec("Voter swarm", "model, adapter, aktif")
        + '<div class="r sm"><span class="k"><b>v1</b> modelrouter &middot; jev-1.13<br>systemone</span>' + switch(True, "Aktif") + "</div>"
        + '<div class="r sm"><span class="k"><b>v2</b> experientiallabs &middot; clef<br>systemone</span>' + switch(True, "Aktif") + "</div>"
        + '<div class="r sm"><span class="k"><b>v6</b> nutaraline &middot; deepseek-v4.1<br>llm_structured</span>' + switch(True, "Aktif") + "</div>"
        + '<div class="r sm"><span class="k"><b>v8</b> sub2api-claude &middot; model chat<br>llm_structured</span>' + switch(False, "Mati") + "</div>"
        + sec("Backend LLM")
        + row("Backend", "deepagents", "sm")
        + row("Agen analis", "nutaraline:deepseek-v4.1-flash-1017", "sm")
        + sec("Compute")
        + '<div class="r sm"><span class="k">Batas biaya harian</span>' + switch(False, "Mati (bawaan)") + "</div>"
        + '<div class="r sm"><span class="k">Catat biaya dan token</span>' + switch(True, "Aktif") + "</div>"
        + row("Hari ini (informasi)", "Rp 410 &middot; 540 rb token", "sm")
        + '<div class="note">Biaya hanya dicatat, bukan meter batas. Bila batas diisi dan terlampaui: lewati entry baru.</div>'
    )
    return phone(inner, "Atur", h=770)


def g4():
    return phones(pc("Layar 5. Swarm per keputusan", g4_swarm()), pc("Layar 6. Konfigurasi, batas biaya mati bawaan", g4_conf()))


PROV = [
    ("nutaraline", "openai-completions", "nutaraline.co.uk", "23", "Tersambung 1,8 dtk", "ok"),
    ("modelrouter", "openai-completions", "modelrouter.id", "23", "Tersambung 0,9 dtk", "ok"),
    ("experientiallabs", "openai-completions", "api.experientiallabs.ai", "272", "Belum diuji", "no"),
    ("tiprouter", "openai-completions", "tiprouter.my.id", "18", "Gagal: waktu habis", "bad"),
    ("xai-hm", "openai-responses", "gateway.example.com", "17", "Belum diuji", "no"),
    ("lucif", "anthropic-messages", "lucif.ai", "2", "Belum diuji", "no"),
]


def g5a():
    trs = ""
    for i, (n, t, h, c, st, k) in enumerate(PROV):
        dot = '<span class="dot"></span>' if k == "ok" else '<span class="dot hol"></span>'
        cls = "sel" if i == 0 else ""
        stt = ('<span class="loss">' + st + "</span>") if k == "bad" else st
        trs += '<tr class="' + cls + '"><td><b>' + n + "</b></td><td>" + t + "</td><td>" + h + '</td><td class="n">' + c + '</td><td style="padding-left:14px">' + dot + stt + "</td></tr>"
    table = '<table class="tb"><tr><th>Provider</th><th>Tipe API</th><th>Host</th><th class="n">Model</th><th style="padding-left:14px">Uji terakhir</th></tr>' + trs + "</table>"
    top = (
        sec("Provider", "dari omp models.yml")
        + table
        + '<div style="padding:6px 14px"><span class="btn sm">Tambah provider</span> <span class="btn sm sec">Impor dari models.yml</span></div>'
        + '<div class="note">Impor dibaca lokal oleh aplikasi di PC: nama, tipe API, base URL, model. Key hanya bila dicentang per provider.</div>'
    )
    detail = (
        sec("nutaraline", "diubah dari PC (localhost)")
        + '<div class="fld"><div class="l">Tipe API</div><div class="in">openai-completions</div></div>'
        + '<div class="fld"><div class="l">Base URL</div><div class="in">https://nutaraline.co.uk/&hellip;/v1</div></div>'
        + '<div class="fld"><div class="l">Sumber key</div><div class="rad" style="flex-direction:column;gap:3px"><span>variabel lingkungan NUTARALINE_API_KEY</span><span class="on">config.yaml lokal</span></div></div>'
        + '<div class="fld"><div class="l">Key (sekali tulis; setelah disimpan hanya 4 karakter terakhir tampil)</div><div class="in">&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;abcd <span style="color:var(--ink2)">&middot; disimpan 2026-10-25</span></div></div>'
        + '<div style="padding:6px 14px"><span class="btn sm sec">Ganti key</span> <span class="btn sm sec">Hapus key</span> <span class="btn sm">Uji koneksi</span></div>'
        + row("Hasil uji", "Tersambung &middot; 1,8 dtk", "sm")
        + '<div class="note">Tidak ada tombol lihat key dan tidak ada endpoint yang mengembalikan key utuh.</div>'
    )
    roles = (
        sec("Model per peran")
        + row("Agen analis", "nutaraline: deepseek-v4.1-flash-1017", "sm")
        + row("Voter v1", "modelrouter: jev-1.13 &middot; systemone", "sm")
        + row("Voter v2", "experientiallabs: clef &middot; systemone", "sm")
        + row("Voter v6", "nutaraline: deepseek-v4.1-flash-1017 &middot; llm_structured", "sm")
        + '<div class="note">Selama testing semua peran memakai deepseek-v4.1-flash-1017 di nutaraline.</div>'
    )
    inner = top + '<div class="cols" style="border-top:1px solid var(--rule)"><div style="flex:1.2">' + detail + "</div><div>" + roles + "</div></div>"
    return '<div class="mkw">' + label("Layar 7a. Provider dan key (di PC, localhost)") + desk(inner, "Atur", ("Ringkas", "Grafik", "Aksi", "Swarm", "Posisi dan riwayat", "Atur")) + "</div>"


def g5b():
    items = ""
    for n, t, h, c, st, k in PROV[:4]:
        dot = '<span class="dot"></span>' if k == "ok" else '<span class="dot hol"></span>'
        on = k != "no"
        stt = ('<span class="loss">' + st + "</span>") if k == "bad" else st
        items += '<div class="r sm"><span class="k"><b style="color:var(--ink)">' + n + "</b> &middot; " + t + "<br>" + dot + stt + "</span>" + switch(on, "Aktif" if on else "Nonaktif") + "</div>"
    inner = (
        chips(["Konfigurasi", "Provider", "Kontrol"], 1)
        + sec("Provider", "6 terdaftar")
        + items
        + sec("nutaraline")
        + row("Model aktif", "deepseek-v4.1-flash-1017", "sm")
        + row("Uji terakhir", "Tersambung &middot; 1,8 dtk", "sm")
        + '<span class="btn">Uji koneksi</span>'
        + '<div class="note" style="background:var(--panel);margin:4px 12px;padding:7px 9px;color:var(--ink)">Tidak ada kolom key di ponsel. Memasukkan atau mengganti key hanya dari PC; ponsel hanya melihat status, mengaktifkan atau menonaktifkan, dan menguji koneksi.</div>'
    )
    legend = (
        '<div class="legend"><p><b>Beda PC dan ponsel</b></p>'
        '<p>PC (localhost): kolom key sekali tulis, hanya 4 karakter terakhir yang tampil, tanpa tombol lihat; uji koneksi; pilih model per peran.</p>'
        '<p>Ponsel (PWA jarak jauh): kolom key tidak ada. Hanya status, aktif atau nonaktif, dan uji koneksi, supaya key tidak pernah lewat tunnel.</p>'
        '<p>Sumber: plan bagian 4.5. Nama provider dari plan bagian 4.3.</p></div>'
    )
    return '<div class="mkw"><div class="phones">' + pc("Layar 7b. Provider (ponsel, tanpa kolom key)", phone(inner, "Atur")) + legend + "</div></div>"


def g6_ctrl():
    inner = (
        chips(["Konfigurasi", "Provider", "Kontrol"], 2)
        + sec("Menurunkan risiko", "langsung, tanpa konfirmasi")
        + '<span class="btn sig">Hentikan entry baru</span>'
        + '<div class="note">Posisi terbuka tetap dijaga stop loss di sisi bot.</div>'
        + '<span class="btn sec">Jeda bot</span>'
        + sec("Tindakan berisiko", "dua langkah")
        + '<span class="btn sec">Tutup semua posisi&hellip;</span>'
        + '<span class="btn sec">Naikkan batas rugi&hellip;</span>'
        + '<span class="btn sec">Pindah ke mode live&hellip;</span>'
        + sec("Status")
        + row("Mode", "Dry-run", "sm")
        + row("Heartbeat bot", "4 dtk lalu", "sm")
        + row("Gateway", "HTTPS tunnel, API Freqtrade tetap lokal", "sm")
    )
    return phone(inner, "Atur", dark=True)


def g6_raise():
    inner = (
        chips(["Konfigurasi", "Provider", "Kontrol"], 2)
        + sec("Naikkan batas rugi harian", "langkah 2 dari 2")
        + row("Batas sekarang", "1,0% (Rp 20.000)", "sm")
        + row("Batas baru", "1,5% (Rp 30.000)", "sm")
        + row("Tambahan risiko", loss("Rp 10.000 per hari"), "sm")
        + '<div class="note">Menaikkan batas menambah risiko. Keputusan ada di tangan Zhafron.</div>'
        + '<div class="fld"><div class="l">Ketik NAIKKAN untuk melanjutkan</div><div class="in">NAIK</div></div>'
        + '<span class="btn dis">Terapkan batas baru</span>'
        + '<div class="note">Tombol aktif setelah kata cocok.</div>'
        + '<span class="btn sec">Batal</span>'
        + '<div class="note">Perubahan dicatat: siapa, kapan, nilai lama dan baru.</div>'
    )
    return phone(inner, "Atur")


def chk(text, state):
    return '<div class="r sm"><span class="k"><span class="dot hol"></span>' + text + '</span><span class="v">' + state + "</span></div>"


def g6_live():
    inner = (
        chips(["Konfigurasi", "Provider", "Kontrol"], 2)
        + sec("Pindah ke mode live", "langkah 2 dari 2")
        + row("Mode sekarang", "Dry-run", "sm")
        + row("Mode baru", loss("Live, dana nyata"), "sm")
        + row("Porsi awal (usulan tahap 3)", "Rp 500.000", "sm")
        + sec("Sebelum live")
        + chk("Ekspektasi positif setelah fee dan pajak di data out-of-sample", "belum")
        + chk("PC tanpa sleep dan tanpa restart otomatis", "belum")
        + chk("Heartbeat ke pemantau di luar PC", "belum")
        + chk("Persetujuan eksplisit Zhafron", "belum")
        + '<span class="btn dis">Pindah ke live</span>'
        + '<div class="note">Tombol aktif setelah semua syarat terpenuhi dan kata LIVE diketik.</div>'
        + '<span class="btn sec">Batal</span>'
    )
    return phone(inner, "Atur")


def g6a():
    return phones(pc("Layar 8a. Kill switch dan kontrol (tema gelap)", g6_ctrl()), pc("Layar 8b. Konfirmasi dua langkah: naikkan batas rugi", g6_raise()))


def g6b():
    legend = (
        '<div class="legend"><p><b>Konfirmasi dua langkah</b></p>'
        '<p>Menurunkan risiko (hentikan entry baru, turunkan batas) berlaku langsung. Menaikkan batas risiko dan pindah ke mode live butuh dua langkah dan menyebut akibatnya dalam rupiah.</p>'
        '<p>Batal selalu tersedia dan tombol terapkan tetap mati sampai syarat terpenuhi.</p>'
        '<p>Daftar syarat live di layar ini berasal dari plan bagian 6 dan 8: nilainya contoh, bukan status nyata.</p></div>'
    )
    return '<div class="mkw"><div class="phones">' + pc("Layar 8c. Konfirmasi dua langkah: pindah ke mode live", g6_live()) + legend + "</div></div>"


def g7():
    left = (
        '<div class="board" style="display:flex;justify-content:space-between;align-items:flex-end"><div><div class="w">Aman</div><div class="s">Rugi hari ini 0,3% dari batas 1,0%. Entry baru boleh dibuka.</div></div>'
        '<div class="s" style="text-align:right">Saldo contoh Rp 1.994.000<br>dari modal Rp 2.000.000</div></div>'
    )
    eq = (
        sec("Ekuitas hari ini", "garis penuh Bot B (swarm bayangan), putus-putus Bot A (aturan saja)")
        + '<div style="padding:0 14px">' + trace_svg(EQ_B, 450, 130, -1.2, 0.6, -1.0, "batas harian " + M + "1,0%", HOURS, EQ_A) + "</div>"
        + meter("Rugi harian", "0,3%", "1,0%", 30) + meter("Rugi total", "0,3%", "10,0%", 3)
        + sec("Posisi terbuka", "2 dari maks 3")
        + '<table class="tb"><tr><th>Pair</th><th>Bot</th><th>Masuk</th><th class="n">Untung rugi</th></tr>'
        + '<tr><td><b>BTC/IDR</b></td><td>B</td><td>14:00</td><td class="n">' + gain("+0,4% untung") + "</td></tr>"
        + '<tr><td><b>ETH/IDR</b></td><td>A</td><td>13:58</td><td class="n">' + loss(M + "0,2% rugi") + "</td></tr></table>"
    )
    right = (
        sec("Keputusan swarm terakhir", "BTC/IDR 14:02")
        + '<div style="padding:0 14px">' + dots_svg(270, VOTERS, 0.665, 0.625, 0.705) + "</div>"
        + row("Kuorum", "6 dari 7 (min 5) terpenuhi", "sm")
        + row("Keputusan", "izinkan (bayangan)", "sm")
        + sec("Kesehatan")
        + row("Loop bot", "normal", "sm")
        + row("nutaraline", "tersambung &middot; 1,8 dtk", "sm")
        + row("modelrouter", "tersambung &middot; 0,9 dtk", "sm")
        + row("tiprouter", loss("gagal: waktu habis"), "sm")
        + row("Biaya LLM hari ini (informasi)", "Rp 410 &middot; 540 rb token", "sm")
        + sec("Aksi terakhir")
        + feed("14:02", "Swarm", "izinkan (bayangan)")
        + feed("13:58", "Order", "beli ETH/IDR (dry-run)")
        + feed("12:41", "Peringatan", "nutaraline 429", True)
    )
    inner = left + '<div class="cols"><div style="flex:1.45">' + eq + "</div><div>" + right + "</div></div>"
    return '<div class="mkw">' + label("Layar 9. Dasbor desktop (lebar)") + desk(inner, "Ringkas") + "</div>"


def icon():
    return (
        '<svg viewBox="0 0 40 40" width="40" height="40" style="vertical-align:top;margin:0 6px 6px 0"><rect width="40" height="40" rx="10" fill="var(--ink)"/>'
        '<polyline points="6,26 12,26 15,13 19,30 23,19 26,24 34,24" fill="none" stroke="var(--onink)" stroke-width="2.2" stroke-linejoin="round"/></svg>'
    )


def step(n, text, screen):
    return '<div class="step ui">' + screen + '<div><span class="n">' + n + ".</span> " + text + "</div></div>"


def g8():
    s1 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span>Safari</span></div><div class="u">alamat-tunnel-contoh</div>'
        '<div class="board" style="margin:6px"><div class="w" style="font-size:22px">Aman</div><div class="s" style="font-size:10px">Dry-run</div></div>'
        '<div style="position:absolute;left:0;right:0;bottom:0;display:flex;justify-content:space-around;padding:8px 4px 10px;border-top:1px solid var(--rule);color:var(--ink2)"><span>Kembali</span><span class="hl" style="padding:0 6px;color:var(--ink);font-weight:600">Bagikan</span><span>Tab</span></div></div>'
    )
    s2 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span>Safari</span></div><div class="u">alamat-tunnel-contoh</div>'
        '<div class="sheet"><div>Salin</div><div class="hl" style="font-weight:600">Tambah ke Layar Utama (Add to Home Screen)</div><div>Cetak</div></div></div>'
    )
    s3 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span></span></div><div style="padding:14px 10px">'
        + icon() + '<span class="ico o"></span><span class="ico o"></span><span class="ico o"></span>'
        + '<div class="hl" style="display:inline-block;padding:2px 4px;font-weight:600">Bot Trading</div></div>'
        '<div class="note">Buka dari ikon ini, bukan dari Safari.</div></div>'
    )
    s4 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span>PWA</span></div><div class="top"><span class="mode">Dry-run</span></div>'
        '<div style="padding:8px 4px"><span class="btn hl">Aktifkan notifikasi</span><div class="note">Izin diminta setelah ketukan ini.</div></div>'
        '<div class="dlg"><div><b>&ldquo;Bot Trading&rdquo; ingin mengirim notifikasi</b></div><div class="bt"><span>Jangan izinkan</span><span class="p">Izinkan</span></div></div></div>'
    )
    row_ = (
        step("1", "Buka alamat PWA di Safari, lalu ketuk Bagikan.", s1)
        + step("2", "Pilih Tambah ke Layar Utama (Add to Home Screen).", s2)
        + step("3", "Buka dari ikon di Layar Utama.", s3)
        + step("4", "Ketuk tombol Aktifkan notifikasi, lalu Izinkan pada dialog iOS.", s4)
    )
    return '<div class="mkw">' + label("Layar 10. Pasang PWA di iOS 16.4 atau lebih baru") + '<div class="steps">' + row_ + "</div></div>"


SCREENS = {
    "g1": g1,
    "g2a": g2a,
    "g2b": g2b,
    "g3": g3,
    "g4": g4,
    "g5a": g5a,
    "g5b": g5b,
    "g6a": g6a,
    "g6b": g6b,
    "g7": g7,
    "g8": g8,
}
