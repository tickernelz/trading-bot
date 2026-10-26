import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mockups

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
assert "(revision 10)" in plan.split("\n")[0]

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
p13 = section(plan, r"^## 13\. ", r"^## Sources")
r5 = section(research, r"^## 5\. ", top)
r6 = section(research, r"^## 6\. ", top)
r7 = section(research, r"^## 7\. ")

pieces = p42.split(FENCE)
assert len(pieces) == 3
yaml_block = FENCE + pieces[1].rstrip("\n") + "\n" + FENCE
change_rules = pieces[2].strip("\n")
safety_note = one_line(p41, "Security note")
p41_main = "\n".join(l for l in p41.split("\n") if not l.startswith("Security note")).strip("\n")
adoption = one_line(p8, "Swarm adoption criteria")
registry_line = one_line(p43, "7. The voter registry")
p43_main = "\n".join(l for l in p43.split("\n") if not l.startswith("7. The voter registry")).strip("\n")
test_model_note = one_line(p8, "During testing all voters")
p8_main = "\n".join(l for l in p8.split("\n") if not l.startswith("Swarm adoption criteria")).strip("\n")

doc = [
    part("s00.md"),
    "# 2. Figures for Rp 2 million capital and costs\n\n## 2.1 Honest statement about results (plan section 1)\n\n" + p1,
    part("s02.md"),
    "# 3. Architecture\n\n@@MOCKarch@@\n\n" + p2 + "\n\n## 3.1 Data sources (plan section 5)\n\n" + p5,
    "# 4. Swarm and median\n\n" + part("s04a.md")
    + "\n\n## 4.2 Two voter groups and aggregation (plan section 3)\n\n" + escape_list_letters(p3)
    + "\n\n## 4.3 Swarm adoption criteria as a gate (plan section 8)\n\n" + adoption
    + "\n\n" + test_model_note + "\n\n" + part("s04b.md"),
    "# 5. Multi-vendor decision model and DecisionProvider\n\n## 5.1 DecisionProvider adapter (plan section 4)\n\n"
    + p4 + "\n\n" + part("s05a.md")
    + "\n\n## 5.2 LLM backend: deepagents and its role (plan section 4.1)\n\n" + p41_main
    + "\n\n## 5.3 AI providers owned by the owner (plan section 4.3, from omp models.yml)\n\n" + p43_main + "\n\n" + part("s05b.md")
    + "\n\n## 5.4 Test model (plan section 4.4)\n\n" + p44
    + "\n\n## 5.5 Provider and key setup (UI) and storage (plan section 4.5)\n\n" + p45,
    "# 6. Configuration\n\n" + part("s06a.md")
    + "\n\n## 6.2 Configuration change rules (plan section 4.2)\n\n" + change_rules
    + "\n\n## 6.3 Default YAML file (plan section 4.2)\n\n" + yaml_block,
    "# 7. Security and PWA\n\n## 7.1 Security\n\n- " + safety_note + "\n- " + registry_line[3:]
    + "\n- API keys do not go into the repo (config/config.yaml and .env are in .gitignore), not in the group, and not in this document; keys in config.yaml are stored as plain text on the PC disk, a consequence accepted by the owner (chapter 5.5)."
    + "\n- Failure closes new entries, it does not open them (fail-closed quorum, chapter 4)."
    + "\n\n## 7.2 PC, all OSes, and mobile (PWA) (plan section 6)\n\n" + p6
    + "\n\n## 7.3 PWA platform limitations (research document, section 5)\n\n" + r5,
    "# 8. Stages, pass criteria, and compute cost\n\n## 8.1 Stages and pass criteria (plan section 8)\n\n"
    + p8_main.replace(test_model_note + "\n\n", "")
    + "\n\n## 8.2 Compute cost (not a limit) (plan section 7)\n\n" + p7
    + "\n\n## 8.3 What is not used and why (plan section 9)\n\n" + p9,
    "# 9. What is unverified and decisions pending\n\n## 9.1 Unverified (research document, section 6)\n\n"
    + r6 + "\n\n" + part("s09a.md") + "\n\n## 9.2 Decisions (plan section 10)\n\n" + p10,
    "# 10. Project and git (plan section 11)\n\n" + p11,
    "# 11. Unique UI/UX with impeccable (plan section 12)\n\n" + p12,
    "# 12. Full features (plan section 13)\n\n" + demote(p13),
]

appendix = os.path.join(HERE, "parts", "appendix.md")
if os.path.exists(appendix):
    doc.append(part("appendix.md"))

doc.append(
    "# Sources\n\nFull evidence and links are in the research-swarm-pwa document. "
    "List of links from the research document (section 7):\n\n" + r7
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
    "--css", os.path.join(HERE, "mockups.css"),
    "--metadata", "lang=en", "--metadata", "pagetitle=Plan for a 24-hour autonomous trading bot",
    "--columns=200", "-o", html_path,
]
with open(log_path, "w") as log:
    code = subprocess.call(command, stderr=log)
print("pandoc exit", code, "log bytes", os.path.getsize(log_path))

html = read(html_path)
used = []


def inline(match):
    name = match.group(1)
    used.append(name)
    if name == "arch":
        return read(os.path.join(HERE, "arch.svg.html"))
    return mockups.SCREENS[name]()


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
