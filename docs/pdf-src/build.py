import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.dirname(HERE)
OUT = os.path.join(HERE, "build")
FENCE = chr(96) * 3
os.makedirs(OUT, exist_ok=True)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def part(name):
    return read(os.path.join(HERE, "parts", name)).strip("\n")


def section(text, start, end=None):
    lines = []
    inside = False
    for line in text.split("\n"):
        if not inside:
            if re.match(start, line):
                inside = True
            continue
        if end and re.match(end, line):
            break
        lines.append(line)
    body = "\n".join(lines).strip("\n")
    assert body, start
    return body


def one_line(text, prefix):
    hits = [line for line in text.split("\n") if line.startswith(prefix)]
    assert len(hits) == 1, prefix
    return hits[0]


def escape_list_letters(text):
    return re.sub(r"(?m)^([AB])\. ", r"\1\\. ", text)


def demote(text):
    return re.sub(r"(?m)^### ", "## ", text)


plan = read(os.path.join(DOCS, "plan.md"))
research = read(os.path.join(DOCS, "research-swarm-pwa.md"))
assert "(revisi 8)" in plan.split("\n")[0]

top = r"^## "
p1 = section(plan, r"^## 1\. ", top)
p2 = section(plan, r"^## 2\. ", top)
p3 = section(plan, r"^## 3\. ", top)
p4 = section(plan, r"^## 4\. ", r"^### ")
p41 = section(plan, r"^### 4\.1", r"^### ")
p42 = section(plan, r"^### 4\.2", r"^### ")
p43 = section(plan, r"^### 4\.3", r"^### ")
p44 = section(plan, r"^### 4\.4", r"^### ")
p45 = section(plan, r"^### 4\.5", top)
p5 = section(plan, r"^## 5\. ", top)
p6 = section(plan, r"^## 6\. ", top)
p7 = section(plan, r"^## 7\. ", top)
p8 = section(plan, r"^## 8\. ", top)
p9 = section(plan, r"^## 9\. ", top)
p10 = section(plan, r"^## 10\. ", top)
p11 = section(plan, r"^## 11\. ", top)
p12 = section(plan, r"^## 12\. ", top)
p13 = section(plan, r"^## 13\. ", r"^## Sumber")
r5 = section(research, r"^## 5\. ", top)
r6 = section(research, r"^## 6\. ", top)
r7 = section(research, r"^## 7\. ")

pieces = p42.split(FENCE)
assert len(pieces) == 3
yaml_block = FENCE + pieces[1].rstrip("\n") + "\n" + FENCE
change_rules = pieces[2].strip("\n")
safety_note = one_line(p41, "Catatan keamanan")
p41_main = "\n".join(l for l in p41.split("\n") if not l.startswith("Catatan keamanan")).strip("\n")
adoption = one_line(p8, "Kriteria adopsi")
registry_line = one_line(p43, "7. Registri voter")
p43_main = "\n".join(l for l in p43.split("\n") if not l.startswith("7. Registri voter")).strip("\n")
test_model_note = one_line(p8, "Selama testing semua voter")
p8_main = "\n".join(l for l in p8.split("\n") if not l.startswith("Kriteria adopsi")).strip("\n")

doc = [
    part("s00.md"),
    "# 2. Angka untuk modal Rp 2 juta dan biaya\n\n## 2.1 Pernyataan jujur tentang hasil (plan bagian 1)\n\n" + p1,
    part("s02.md"),
    "# 3. Arsitektur\n\n@@MOCKarch@@\n\n" + p2 + "\n\n## 3.1 Sumber data (plan bagian 5)\n\n" + p5,
    "# 4. Swarm dan median\n\n" + part("s04a.md")
    + "\n\n## 4.2 Dua kelompok voter dan agregasi (plan bagian 3)\n\n" + escape_list_letters(p3)
    + "\n\n## 4.3 Kriteria adopsi swarm sebagai gerbang (plan bagian 8)\n\n" + adoption
    + "\n\n" + test_model_note + "\n\n" + part("s04b.md"),
    "# 5. Decision model multi-vendor dan DecisionProvider\n\n## 5.1 Adapter DecisionProvider (plan bagian 4)\n\n"
    + p4 + "\n\n" + part("s05a.md")
    + "\n\n## 5.2 Backend LLM: deepagents dan perannya (plan bagian 4.1)\n\n" + p41_main
    + "\n\n## 5.3 Provider AI milik Zhafron (plan bagian 4.3, dari omp models.yml)\n\n" + p43_main + "\n\n" + part("s05b.md")
    + "\n\n## 5.4 Model uji (plan bagian 4.4)\n\n" + p44
    + "\n\n## 5.5 Setup provider dan key (UI) dan penyimpanan aman (plan bagian 4.5)\n\n" + p45,
    "# 6. Konfigurasi\n\n" + part("s06a.md")
    + "\n\n## 6.2 Aturan perubahan konfigurasi (plan bagian 4.2)\n\n" + change_rules
    + "\n\n## 6.3 Berkas YAML default (plan bagian 4.2)\n\n" + yaml_block,
    "# 7. Keamanan dan PWA\n\n## 7.1 Keamanan\n\n- " + safety_note + "\n- " + registry_line[3:]
    + "\n- Rahasia (API key) tidak di berkas, tidak di repo, tidak di grup, dan tidak di dokumen ini; aturan penyimpanan lengkap di bab 5.5."
    + "\n- Kegagalan menutup entry baru, bukan membukanya (kuorum fail-closed, bab 4)."
    + "\n\n## 7.2 PC, semua OS, dan mobile (PWA) (plan bagian 6)\n\n" + p6
    + "\n\n## 7.3 Batasan platform PWA (dokumen riset, bagian 5)\n\n" + r5,
    "# 8. Tahap, syarat lolos, dan biaya compute\n\n## 8.1 Tahap dan syarat lolos (plan bagian 8)\n\n"
    + p8_main.replace(test_model_note + "\n\n", "")
    + "\n\n## 8.2 Biaya compute (bukan batasan) (plan bagian 7)\n\n" + p7
    + "\n\n## 8.3 Yang tidak dipakai dan alasannya (plan bagian 9)\n\n" + p9,
    "# 9. Yang belum terverifikasi dan keputusan yang ditunggu\n\n## 9.1 Belum terverifikasi (dokumen riset, bagian 6)\n\n"
    + r6 + "\n\n" + part("s09a.md") + "\n\n## 9.2 Keputusan (plan bagian 10)\n\n" + p10,
    "# 10. Proyek dan git (plan bagian 11)\n\n" + p11,
    "# 11. UI/UX unik dengan impeccable (plan bagian 12)\n\n" + p12,
    "# 12. Fitur lengkap (plan bagian 13)\n\n" + demote(p13),
]

appendix = os.path.join(HERE, "parts", "appendix.md")
if os.path.exists(appendix):
    doc.append(part("appendix.md"))

doc.append(
    "# Sumber\n\nBukti dan tautan lengkap ada di dokumen research-swarm-pwa pada issue ZHA-3760. "
    "Daftar tautan dari dokumen riset (bagian 7):\n\n" + r7
)

markdown = "\n" + "\n\n".join(doc) + "\n"
md_path = os.path.join(OUT, "doc.md")
with open(md_path, "w", encoding="utf-8") as fh:
    fh.write(markdown)

html_path = os.path.join(OUT, "r.html")
log_path = os.path.join(OUT, "pandoc.log")
command = [
    "nice", "-n", "19", "pandoc", md_path,
    "-f", "markdown+lists_without_preceding_blankline-markdown_in_html_blocks-citations+native_divs",
    "-t", "html5", "--standalone", "--embed-resources",
    "--css", os.path.join(HERE, "style.css"),
    "--metadata", "lang=id", "--metadata", "pagetitle=Plan bot trading otonom 24 jam",
    "--columns=200", "-o", html_path,
]
with open(log_path, "w") as log:
    code = subprocess.call(command, stderr=log)
print("pandoc exit", code, "log bytes", os.path.getsize(log_path))

html = read(html_path)
used = []


def inline(match):
    name = match.group(1)
    target = os.path.join(HERE, "arch.svg.html") if name == "arch" else os.path.join(HERE, "mockups", name + ".html")
    used.append(name)
    return read(target)


html = re.sub(r"<p>@@MOCK(\w+)@@</p>", inline, html)
assert "@@MOCK" not in html
with open(os.path.join(OUT, "r2.html"), "w", encoding="utf-8") as fh:
    fh.write(html)
print("inlined", used)
if "--no-pdf" in sys.argv:
    sys.exit(0)
pdf_path = os.path.join(OUT, "out.pdf")
subprocess.call([
    "nice", "-n", "19", "google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
    "--no-pdf-header-footer", "--print-to-pdf=" + pdf_path, "file://" + os.path.join(OUT, "r2.html"),
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("pdf", os.path.getsize(pdf_path))
