# trading-bot

Bot trading otonom 24 jam (crypto spot, dry-run dulu) dengan swarm voter dan median sebagai penyaring entry, plus panel kontrol PWA.

Status: tahap 0 (setup). Belum ada akun atau uang yang terhubung. Profit tidak dijamin.

## Isi

- vendor/freqtrade: engine Freqtrade sebagai git submodule, terkunci di tag 2026.9
- docs/plan.md: plan final
- docs/research-swarm-pwa.md: riset dan sumber
- config/config.example.yaml: contoh konfigurasi
- .env.example: nama variabel lingkungan

## Setelah clone

    git clone --recurse-submodules <url>
    git config core.hooksPath .githooks
    mkdir -p .agents/skills && ln -s ~/.agents/skills/impeccable .agents/skills/impeccable

Bila sudah clone tanpa --recurse-submodules: git submodule update --init

## Memperbarui Freqtrade

    git -C vendor/freqtrade fetch --depth 1 origin tag <tag>
    git -C vendor/freqtrade checkout <tag>
    git add vendor/freqtrade
    git commit -m "build(vendor): bump freqtrade to <tag>"

Strategi dan data pengguna ada di luar vendor/freqtrade (--strategy-path dan --userdir), jadi isi vendor tidak diubah. Bila suatu saat perlu memodifikasi engine, fork Freqtrade lalu arahkan url di .gitmodules ke fork itu.

## Rahasia

API key boleh lewat variabel lingkungan (salin .env.example ke .env) atau langsung di config/config.yaml. Kedua berkas itu ada di .gitignore dan tidak boleh di-commit.

## Aturan repo

- Commit memakai Conventional Commits berbahasa Inggris, subject di bawah 72 karakter, tanpa trailer Co-Authored-By.
- Tidak ada komentar di kode kita. Isi vendor/freqtrade adalah kode pihak ketiga dan tidak diubah.
- Belum ada remote dan belum ada berkas LICENSE (Freqtrade berlisensi GPL-3.0).
