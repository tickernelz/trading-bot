# trading-bot

Bot trading otonom 24 jam (crypto spot, dry-run dulu) dengan swarm voter dan median sebagai penyaring entry, plus panel kontrol PWA.

Status: perencanaan. Belum ada kode produk, belum ada akun atau uang yang terhubung. Profit tidak dijamin.

## Isi

- docs/plan.md: plan final
- docs/research-swarm-pwa.md: riset dan sumber
- config/config.example.yaml: contoh konfigurasi, belum dibaca kode apa pun

## Setelah clone

    git config core.hooksPath .githooks
    mkdir -p .agents/skills && ln -s ~/.agents/skills/impeccable .agents/skills/impeccable

## Aturan repo

- Commit memakai Conventional Commits berbahasa Inggris, subject di bawah 72 karakter, tanpa trailer Co-Authored-By.
- Tidak ada komentar di kode.
- API key tidak masuk repo, berkas konfigurasi, basis data, atau log. Key disimpan di penyimpanan kredensial OS (lihat bagian 4.5 di docs/plan.md).
- Belum ada remote dan belum ada berkas LICENSE.
