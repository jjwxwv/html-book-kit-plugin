# Claude HTML Book Kit v10.0 — Plugin Edition (คู่มือภาษาไทย)

Plugin สำหรับ Claude Code: แปลงเอกสารประกอบการเรียน (PDF / PPTX / DOCX / Markdown) ใน `sources/` เป็น **หนังสือ/เลกเชอร์ HTML สรุปภาษาไทย** ที่ถูกต้อง อ่านง่าย อัปเดตได้ และประหยัด token

หลักการ: *อ่านต้นฉบับให้ครบ เข้าใจให้หมด แล้วค่อยสรุปอย่างเลือกสรร — ทุกการตัด/รวมต้องตรวจสอบย้อนกลับได้*

ต่างจากรุ่น v9.x ตรงที่ **ติดตั้ง kit ครั้งเดียว** แล้วใช้กับโฟลเดอร์หนังสือกี่โปรเจกต์ก็ได้ — โฟลเดอร์หนังสือมีแค่ `sources/`, `book.config.json`, `.book-state/`, `book/` (ไม่ต้องคัดลอก agent/script/template ไปทุกโปรเจกต์อีก)

## ติดตั้ง (เลือก 1 วิธี)

| วิธี | ทำอย่างไร | มีผล |
|---|---|---|
| **ใช้ทุก session ไม่ต้องมี marketplace** (แนะนำสำหรับใช้คนเดียว) | คัดลอกโฟลเดอร์ `book-kit` ไปไว้ที่ `~/.claude/skills/book-kit/` | โหลดอัตโนมัติทุก session (ชื่อ `book-kit@skills-dir`) |
| **ลองใช้ 1 session** | `claude --plugin-dir /path/to/book-kit` (ใส่ไฟล์ `.zip` ของโฟลเดอร์แทนก็ได้) | เฉพาะ session นั้น |
| **ผ่าน marketplace** (อัปเดตตามได้) | `claude plugin marketplace add /path/to/repo` (หรือ `owner/repo` บน GitHub) แล้ว `claude plugin install book-kit@html-book-kit` | ตาม scope ที่เลือก (user / project / local) |

ตรวจว่าโหลดแล้ว: พิมพ์ `/` ใน Claude Code ควรเห็น `/book-kit:build-book` หรือดูใน `/plugin` → Installed; จากเชลล์ใช้ `claude plugin validate /path/to/book-kit` ตรวจโครงสร้างได้

ต้องมี Python 3; ถ้ามีต้นฉบับ `.pptx`/`.docx` ให้ `pip install python-pptx python-docx` (บน Windows ถ้าไม่มีคำสั่ง `python3` ระบบจะใช้ `python` แทนได้)

## เริ่มใช้งาน (4 ขั้น)

1. สร้างโฟลเดอร์หนังสือ เปิด terminal ในโฟลเดอร์นั้น รัน `claude` แล้วพิมพ์ `/book-kit:init "ชื่อหนังสือ"` — ได้ `sources/`, `book.config.json`, `.book-state/`, `book/`, กติกา permission ใน `.claude/settings.json`, และ `CLAUDE.md` สั้นๆ (ไม่ทับไฟล์ที่มีอยู่แล้ว)
2. วางไฟล์ต้นฉบับใน `sources/` ตามรูปแบบใน `sources/README.md` (เลขนำหน้า = โครงสร้างบท) และตรวจชื่อหนังสือใน `book.config.json`
3. พิมพ์ `/book-kit:build-book` → เสร็จแล้วเปิด `book/index.html` ในเบราว์เซอร์
4. ถ้า audit พบประเด็น ระบบจะ **รายงาน → ถาม → หยุด** — ตอบยืนยัน หรือสั่ง `/book-kit:apply-fixes` เพื่อแก้ทีละรอบ

> ครั้งแรกหลัง `init` กติกา permission จะมีผลเมื่อเริ่ม session ใหม่ (หรือหลังยอมรับ trust dialog ของโฟลเดอร์) — ถ้า Claude Code ถามสิทธิ์ระหว่าง build ครั้งแรก ให้กดอนุญาตได้ตามปกติ

## คำสั่งทั้งหมด

| คำสั่ง | ใช้เมื่อ |
|---|---|
| `/book-kit:init [ชื่อหนังสือ]` | ตั้งค่าโฟลเดอร์ปัจจุบันเป็นโปรเจกต์หนังสือ (รันซ้ำได้ ไม่ทับไฟล์เดิม) |
| `/book-kit:build-book` | สร้างหนังสือครั้งแรก (หรือ rebuild ทั้งเล่ม) |
| `/book-kit:update-book` | แก้ไข/เพิ่ม/ลบไฟล์ต้นฉบับแล้ว — ทำเฉพาะส่วนที่กระทบ |
| `/book-kit:audit-book [เลขบท]` | ตรวจคุณภาพอย่างเดียว ไม่แก้อะไร |
| `/book-kit:apply-fixes [F-id หรือ severity]` | อนุมัติให้แก้ตามรายงาน audit ล่าสุด (1 อนุมัติ = 1 รอบแก้) |

พิมพ์แบบสั้น `/build-book` ก็ใช้ได้ตราบใดที่ไม่มีคำสั่งอื่นชื่อซ้ำ

ทุก workflow จบด้วย **audit → รายงาน → ถาม → หยุด**: ระบบจะไม่แก้อะไรเองจนกว่าคุณจะสั่ง `/book-kit:apply-fixes` หรือยืนยันชัดเจน และแก้ครั้งละหนึ่งรอบเท่านั้น (กัน infinite loop) — คำสั่ง build/update/audit/init เป็นคำสั่งที่ **ผู้ใช้เท่านั้น** เรียกได้ (Claude เริ่ม pipeline เองไม่ได้) ส่วน `apply-fixes` Claude เรียกให้ได้เฉพาะหลังคุณตอบยืนยันชัดเจน

## Pipeline ภายใน

```text
sources/ ── scan (SHA-256, เฉพาะที่เปลี่ยน)
   ↓
book-kit:source-analyst   อ่านต้นฉบับ 1 ครั้ง/เวอร์ชัน → extraction (ground truth)
   ↓
book-kit:book-architect   วางโครงบท/ลำดับ/รวมซ้ำ/priority/coverage
   ↓
book-kit:chapter-writer   เขียนเนื้อหาไทยราย chapter (ขนานกันได้)
   ↓
book-kit:book-builder     ประกอบ HTML จาก template ของ plugin + validate เชิงกล
   ↓
book-kit:book-auditor     ตรวจความถูกต้อง/ครบถ้วน/ความชัดเจน (report-only)
   ↓
รายงาน → ถามคุณ → หยุด   (แก้ผ่าน /book-kit:apply-fixes เท่านั้น)
```

Agent ปลายน้ำทุกตัวทำงานจาก extraction ที่บันทึกไว้ ไม่เปิดต้นฉบับเอง (ยกเว้น auditor spot-check ได้ไม่เกินค่า `audit.max_source_spot_checks` ใน config — ค่าเริ่มต้น 10 จุด/รอบ — พร้อม log) — ต้นฉบับแต่ละเวอร์ชันจึงถูกอ่านเชิงความหมายแค่ครั้งเดียว

กติกากลาง (เดิมคือ `CLAUDE.md`) อยู่ใน skill `book-kit:rules`: ทุกคำสั่งจะโหลดครั้งเดียวต่อบทสนทนา และถูก preload เข้า agent ที่ต้องใช้วิจารณญาณ (architect / writer / auditor) เหมือนที่เคยได้รับ `CLAUDE.md` ในรุ่นก่อน ส่วน analyst / builder ทำงานได้จากกติกาในตัวเองจึงไม่ต้องรับข้อความส่วนนี้ (ประหยัดราว 2.4k token ต่อการเรียกหนึ่งครั้ง)

## การตอบโจทย์ requirement ทั้ง 8 ข้อ (ไม่เปลี่ยนจาก v9.8)

1. **หัวข้อย่อยหลายระดับ** — id แบบจุดลึกได้ไม่จำกัด (`2`, `2.1`, `2.2.1`) จากเลขนำหน้าไฟล์/โฟลเดอร์ + เนื้อหา; anchor เสถียร `#sec-2-2-1`; validator ตรวจว่า parent ครบ
2. **กระชับ ชัดเจน อ่านง่าย เข้าใจง่าย แต่คงความครบถ้วนสมบูรณ์** — กติกาการเขียนใน `chapter-writer`: ใช้ถ้อยคำสั้นที่สุดที่ยังคงความหมายครบ, อธิบายจาก intuition → นิยาม → ตัวอย่าง, ศัพท์อังกฤษวงเล็บครั้งแรก, callout นิยาม/ตัวอย่าง/สรุปท้ายบท; **กติกาตัดสินเมื่อขัดกัน: ความครบถ้วนชนะความสั้น** — ห้ามละเนื้อหาด้วยเหตุผล "เพื่อความกระชับ" (`validate_book.py` เตือน `coverage.brevity_reason` และ auditor ตรวจทุกกรณี)
3. **เสริมเนื้อหา/รูปภาพเฉพาะจำเป็น** — architect อนุมัติ supplement พร้อมเหตุผลใน plan, writer ติด `data-supplement`, รูป = inline SVG เท่านั้น, auditor ตรวจว่าจำเป็นจริง
4. **แก้ไข/เพิ่มบทภายหลัง** — manifest SHA-256 ตรวจจับ added/changed/removed/renamed; `/book-kit:update-book` ทำเฉพาะส่วนกระทบ; id หัวข้อเดิมคงที่
5. **UI สีสันสวยงาม + ถูกหลักการออกแบบ** — ธีมพื้นฐาน (template ใน plugin) มีสีสัน gradient accent, callout แยกสีตามชนิด, ทุกคู่สีผ่าน WCAG AA ทั้งโหมดสว่างและมืด; ขั้นต่ำครบ: TOC/agenda + ค้นหา + scrollspy, progress bar รายหน้า + ทั้งเล่ม, light/dark/auto, prev/next, responsive, print CSS
6. **กัน infinite loop จาก audit** — REPORT → ASK → STOP เขียนตายตัวใน rules และทุกคำสั่ง; auditor เป็น report-only; การแก้ต้องผ่าน `/book-kit:apply-fixes`; 1 อนุมัติ = 1 batch แล้ว recheck เฉพาะ finding ที่แก้
7. **ครบถ้วน ถูกต้อง แม่นยำ** — ทุก extraction unit ต้องมีสถานะใน `coverage.json`; `validate_book.py` fail ทันทีถ้ามี unit ตกหล่น; auditor เทียบ draft กับ extraction ราย unit
8. **ใช้ token เหมาะสม** — อ่านต้นฉบับ 1 ครั้ง/เวอร์ชัน, ไม่แปะเนื้อหาลงบทสนทนา, UI boilerplate มาจาก template, รายงาน audit เป็น JSON + สรุปสั้น, update แบบ delta; **เพิ่มในรุ่น plugin**: description ของคำสั่ง build/update/audit/init ไม่กินบริบทเลยจนกว่าจะเรียก และ rules โหลดครั้งเดียว/ถูก dedupe เมื่อเรียกซ้ำ

## โครงสร้าง

```text
plugin (ติดตั้งครั้งเดียว)                    โปรเจกต์หนังสือ (ต่อเล่ม)
├── skills/rules/        กติกากลาง             ├── book.config.json   ชื่อหนังสือ/ตัวเลือก
├── skills/<คำสั่ง>/     init/build/update/... ├── sources/           ต้นฉบับของคุณ (kit ห้ามแก้ — deny ไว้ใน settings)
├── agents/              5 subagents           ├── .book-state/       extraction / plan / coverage / drafts / audits
├── scripts/             python scripts        ├── book/              ผลลัพธ์ — เปิด index.html ได้เลย
├── templates/           HTML shells + assets  ├── .claude/settings.json  permission ที่ init เพิ่มให้
└── scaffold/            ไฟล์ตั้งต้นสำหรับ init  ├── CLAUDE.md          5 บรรทัด (init สร้างให้ถ้ายังไม่มี)
                                               └── templates/         (ไม่บังคับ) สำเนา template ที่ปรับดีไซน์แล้ว — override ของ plugin
```

Script ทุกตัวถือว่าโปรเจกต์คือ **โฟลเดอร์ปัจจุบัน** (ส่ง `--root <dir>` ได้) และจะปฏิเสธถ้าโฟลเดอร์ไม่ใช่โปรเจกต์หนังสือ; plugin ไม่เขียนไฟล์ลงในตัวเองเด็ดขาด (ถูกแทนที่ทุกครั้งที่อัปเดต)

## ย้ายจากโปรเจกต์ v9.x (โฟลเดอร์ kit เดิม)

รัน `/book-kit:init` ในโฟลเดอร์เดิม — `.book-state/`, `book/`, `book.config.json` ใช้ต่อได้ทันที (schema ไม่เปลี่ยน) และกติกา permission ใหม่จะถูกรวมเข้า `.claude/settings.json` (กติกา `Write(...)` เดิมไม่มีผลใน Claude Code อยู่แล้ว ลบทิ้งได้) จากนั้นลบ `CLAUDE.md`, `.claude/agents/`, `.claude/commands/`, `scripts/` ที่ซ้ำกับ plugin (init จะรายงานรายการที่พบ) — `templates/` เก็บไว้เฉพาะถ้าเคยปรับดีไซน์ (จะกลายเป็น override) แล้วใช้ `/book-kit:update-book` ต่อได้เลย

## คำถามที่พบบ่อย

**แก้ PDF บทเดิมไปหนึ่งไฟล์ ต้องทำอะไร** — วางไฟล์ทับแล้ว `/book-kit:update-book` ระบบจะ re-extract เฉพาะไฟล์นั้นและเขียนใหม่เฉพาะหัวข้อที่อ้างถึงมัน

**ลบไฟล์/บทออกจากหนังสือ ต้องทำอะไร** — ลบไฟล์ใน `sources/` แล้วสั่ง `/book-kit:update-book` ระบบจะลบ state ที่ค้างด้วย `prune_state.py` แล้วให้ architect ตัด/รวมหัวข้อที่กระทบให้เอง

**audit เจอปัญหาแต่ยังไม่อยากแก้** — ตอบปฏิเสธได้เลย รายงานจะถูกตั้งเป็น `declined` และหนังสือไม่ถูกแตะ; เปลี่ยนใจทีหลังพิมพ์ "apply audit A<n>" ได้

**อยากเปลี่ยนโทนสี/ดีไซน์** — บอกใน chat ได้ตรงๆ builder จะแก้ `book/assets/style.css` โดยยังคงหลักการออกแบบ; ถ้าอยากให้ดีไซน์นั้นใช้กับ build ครั้งต่อไปด้วย ให้บอกว่า "persist" builder จะคัดลอก template ของ plugin มาเป็น `templates/` ในโปรเจกต์แล้วแก้ที่สำเนานั้น; หรือแก้ `accent` / `accent2` ใน `book.config.json`

**อัปเดต plugin แล้วหนังสือเดิมพัง?** — ไม่ควร: state ทั้งหมดอยู่ในโปรเจกต์ ไม่มีอะไรอยู่ใน plugin; ถ้ามี `templates/` override ในโปรเจกต์ มันจะยังใช้ต่อ (ไม่โดนอัปเดตทับ)

**พิมพ์ "สร้างหนังสือให้หน่อย" แล้ว Claude ไม่ทำ** — ตั้งใจ: คำสั่ง build/update/audit ต้องพิมพ์เอง (`/book-kit:build-book`) เพื่อไม่ให้ pipeline ที่กิน token เริ่มโดยไม่ตั้งใจ Claude จะบอกคำสั่งให้

**มีสูตรคณิตศาสตร์เยอะ** — ตั้ง `"math_katex_cdn": true` ใน config (ต้องออนไลน์ตอนเปิดอ่าน) แล้ว rebuild

**อยากใช้ mermaid diagram** — ตั้ง `"mermaid_cdn": true` แล้ว writer จะใช้ `<pre class="mermaid">` แทน SVG วาดมือได้สำหรับ flow/graph (ต้องออนไลน์ตอนเปิดอ่านเช่นกัน)

**ความคืบหน้า "อ่านแล้ว X หัวข้อ" เก็บที่ไหน** — localStorage ของเบราว์เซอร์ผู้อ่านแต่ละคน ไม่กระทบไฟล์หนังสือ
