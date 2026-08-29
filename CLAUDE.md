# CLAUDE.md

````````````````````````````````````````text
# CLAUDE.md

```````````````````````````````````````text
# CLAUDE.md

``````````````````````````````````````text
# CLAUDE.md

`````````````````````````````````````text
# CLAUDE.md

````````````````````````````````````text
# CLAUDE.md

```````````````````````````````````text
# CLAUDE.md

``````````````````````````````````text
# CLAUDE.md

`````````````````````````````````text
# CLAUDE.md

````````````````````````````````text
# CLAUDE.md

```````````````````````````````text
# CLAUDE.md

``````````````````````````````text
# CLAUDE.md

`````````````````````````````text
# CLAUDE.md

````````````````````````````text
# CLAUDE.md

```````````````````````````text
# CLAUDE.md

``````````````````````````text
# CLAUDE.md

`````````````````````````text
# CLAUDE.md

````````````````````````text
# CLAUDE.md

```````````````````````text
# CLAUDE.md

``````````````````````text
# CLAUDE.md

`````````````````````text
# CLAUDE.md

````````````````````text
# CLAUDE.md

```````````````````text
# CLAUDE.md

``````````````````text
# CLAUDE.md

`````````````````text
# CLAUDE.md

````````````````text
# CLAUDE.md

```````````````text
# CLAUDE.md

``````````````text
# CLAUDE.md

`````````````text
# CLAUDE.md

````````````text
# CLAUDE.md

```````````text
# CLAUDE.md

``````````text
# CLAUDE.md

`````````text
# CLAUDE.md

````````text
# CLAUDE.md

```````text
# CLAUDE.md

``````text
# CLAUDE.md

`````text
# CLAUDE.md

````text
# CLAUDE.md — Project Development & Verification Protocol

---

## EXECUTION GUIDELINES & WORKFLOW STANDARDS (v5.1)

### 1. Role & Execution Guidelines

- **Role:** คุณคือ Execution Engine ทำหน้าที่คิดวิเคราะห์จุดแก้ไขและจุดเชื่อมโยงทั้งหมดอย่างรอบด้าน เพื่อแก้ไขโค้ดให้สมบูรณ์ครบจบในรอบเดียวและประหยัด Token
- **UI Standard:** งานส่วน UI ทั้งหมดต้องใช้ Modern Styling/Modern SVG Icons เท่านั้น ห้ามปล่อย Native Windows Classic Style หรือ UI แบบดั้งเดิมที่ไม่ได้ปรับแต่งเด็ดขาด
- **Discretion Boundary:** หากพบจุดผิดพลาดเชิงสถาปัตยกรรม ความเสี่ยง หรือคำสั่งที่ไม่ชัดเจน สามารถทักท้วงและเสนอแนะทางเลือกที่เหมาะสมได้ทันที

### 2. Deterministic Pipeline Execution Sequence (Step 1 ➔ Step 6)

เมื่อรับ Task พัฒนาหรือแก้ไขระบบ ให้ปฏิบัติตามลำดับ Step 1 ➔ Step 6 ดังนี้:

**Step 1 (Code Updates):** ดำเนินการแก้ไขโค้ดตามโจทย์งานให้ครบถ้วนทุกโมดูลที่เกี่ยวข้อง

**Step 2 (Cache Purge):** ล้างโฟลเดอร์แคชของโปรเจกต์ (`__pycache__`, `bin/`, `obj/`, `build/`, `dist/`, `.cache`)

**Step 3 (QA & Gatekeeper Verification):** สั่งรันคำสั่ง Terminal เพื่อตรวจสอบความถูกต้องผ่าน LocalCore CLI ดังนี้:
```powershell
powershell -ExecutionPolicy Bypass -File ./tools/verify.ps1
```

**Step 4 (Strict Re-Validation, False-Positive Check & Auto-Fix Loop):**

**Phase A: Read BOTH EXIT_CODE and Full Log Output**
- อ่าน `EXIT_CODE` จาก PowerShell ผลลัพธ์
- อ่าน **ทั้งหมด** Text Log ที่ LocalCore CLI พ่นออกมา (stdout + stderr)
- สแกน Log เพื่อหา Keywords ที่บ่งบอก Internal Validation Failure:
 - `VALIDATION FAILED`
 - `No command given`
 - `No project markers`
 - `Internal Error`
 - `Test failed`

**Phase B: Decision Logic**
- **กรณี `EXIT_CODE: 0` AND ไม่พบ Failure Keywords (TRUE PASS):** อนุญาตให้ไปดำเนินการ Step 5 ต่อได้ทันที ✅
- **กรณี `EXIT_CODE: 0` BUT พบ Failure Keywords (FALSE POSITIVE):** **HARD STOP** ห้ามลักไก่ข้ามไป Step 5 ❌ วนกลับ **Step 1**
- **กรณี `EXIT_CODE != 0` (DIRECT FAILURE):** **HARD STOP** ห้ามลักไก่ข้ามไป Step 5 ❌ วนกลับ **Step 1**

**Phase C: Auto-Fix Loop**
- วน Loop แก้ไขและส่งตรวจใหม่ Step 1 ➔ Step 2 ➔ Step 3 ➔ Step 4 จนกว่าจะได้รับ `EXIT_CODE: 0` ของจริง + ไม่มี Failure Keywords

**Step 5 (Packaging & Build):** เมื่อผ่านการอนุมัติ `EXIT_CODE: 0` ของจริงจาก LocalCore CLI แล้ว ให้ดำเนินการสร้าง Release Build (จำกัดการใช้ CPU/RAM ไม่เกิน 85%)

**Step 6 (Sync & Audit Trail):** อัปเดต `CHANGELOG.md`, `HISTORY.md` และปรับเลขเวอร์ชัน (SemVer) ให้ตรงกันทุกจุด

### 3. Anti-Bypass Rules

- ห้าม Claude เขียนสคริปต์อื่นมาสวมรอยแทนการตรวจของ LocalCore CLI
- ห้ามเชื่อถือ Exit Code ของ PowerShell เพียงอย่างเดียว ต้องสแกนอ่าน Internal Verification Status ใน Log เสมอ
- ทุกการแก้ไขโค้ดใน Step 1 บังคับต้องวนกลับมาส่งตรวจใน Step 3 ซ้ำทุกครั้ง

---

## TRI-AGENT WORKFLOW PROTOCOL (v4.7 — COMPLETE MASTER SPECIFICATION)

This document outlines the collaborative workflow between three AI agents and the gatekeeper system for ensuring code quality and automated verification with ZERO-TOLERANCE anti-simulation enforcement and mandatory Log traceability.

### 1. AI ROLES & EXPLICIT RESPONSIBILITIES

**Master Architect (Gemini)**
- หน้าที่: ออกแบบสถาปัตยกรรมระดับสูง วิเคราะห์ภาพรวม และออกคำสั่งแบบ Structured Task
- ข้อจำกัด: เป็นผู้วางแผนและสั่งการ ห้ามลงมือแก้ไขโค้ดในโปรเจกต์โดยตรง

**Execution Engine (Claude Code / OpenCode)**
- หน้าที่: รับคำสั่ง เขียนโค้ด คิดวิเคราะห์อย่างรอบด้านเพื่อให้แก้ไขจบได้ในครั้งเดียวและประหยัดโทเค็น ทำ Auto-Fix และรันคำสั่งตรวจสอบตามโปรโตคอล
- ข้อจำกัด: ห้ามแอบอ้างผลลัพธ์หรือข้ามขั้นตอน

**Gatekeeper Auditor (LocalCore CLI)**
- หน้าที่: สแกนตรวจสอบโค้ดแบบ Read-Only และพ่นค่า EXIT_CODE พร้อมบันทึก Log ลงระบบ
- ข้อจำกัด: ห้ามแก้ไขโค้ดเอง

---

### 2. PROJECT ROOT & MARKER VALIDATION RULE

ก่อนสั่งรัน LocalCore ทุกครั้ง ต้องตรวจสอบและเปลี่ยนไดเรกทอรี (`cd`) เข้าไปในโฟลเดอร์หลักของโปรเจกต์ (Project Root) ที่มีไฟล์มาร์กเกอร์ (เช่น `pyproject.toml`, `package.json`) เรียบร้อยแล้ว

**ห้ามรันจากโฟลเดอร์แม่เด็ดขาด** เพื่อป้องกันข้อผิดพลาด `no markers`
- หากพบปัญหานี้ให้ค้นหาโฟลเดอร์ Root และย้าย Working Directory ทันที

---

### 3. MANDATORY GATEKEEPER EXECUTION RULE (SILENT BACKGROUND MODE)

เพื่อป้องกันไม่ให้หน้าต่าง LocalCore เด้งซ้อนทับหน้าต่าง Log หลัก Execution Engine ต้องรันคำสั่งผ่าน PowerShell แบบซ่อนหน้าต่างทุกครั้ง:

```powershell
powershell -Command "$p = Start-Process -FilePath 'C:\Program Files\LocalCore\localcore.exe' -ArgumentList '--verify', '--model', 'Qwen-2.5-Coder-7B' -NoNewWindow -PassThru; $p.WaitForExit(); exit $p.ExitCode"
```

**หรือใช้ cmd with Delayed Expansion:**
```batch
cd /d <PROJECT_ROOT>
cmd /v:on /c "C:\PROGRA~1\LocalCore\localcore.exe --verify --model "Qwen-2.5-Coder-7B" & echo EXIT_CODE:!ERRORLEVEL!"
```

---

### 4. STRICT ANTI-SIMULATION & CLEAN COMMAND ENFORCEMENT (ZERO-TOLERANCE)

**ห้ายัดคำสั่งเทสภายนอกเข้าไปเป็น Argument ของ LocalCore เด็ดขาด**
- ❌ **PROHIBITED:** ใช้ `pytest`, `cargo test`, `npm test` เป็น Argument ของ LocalCore
- ❌ **PROHIBITED:** โครงสร้างคำสั่งต้องใช้เฉพาะ `--verify` และ `--model` เท่านั้น ห้ามดัดแปลง Syntax
- ❌ **PROHIBITED:** ใช้คำสั่งเทสภายในแล้วนำ Exit Code มาอ้างอิงแทน Gatekeeper เด็ดขาด

**บังคับให้ใช้ LocalCore จริง:**
- ✅ **REQUIRED:** ข้อมูลต้องวิ่งผ่าน LocalCore CLI จริงเท่านั้น
- ✅ **REQUIRED:** ต้องปรากฏ Log หลักฐานของการทำงาน (Log Trace) ในระบบ LocalCore
- ✅ **REQUIRED:** หากแสดง `EXIT_CODE: 0` แต่ไม่มีร่องรอย Log จะถือว่าเป็นโมฆะทันที

---

### 5. AUTOMATED RE-VERIFICATION LOOP

**INITIAL CHECK:**
- รันคำสั่งผ่าน Gatekeeper หากได้ EXIT_CODE: 0 ให้ไปขั้นตอน Release ทันที

**FAIL LOOP:**
หาก EXIT_CODE != 0 (FAIL):
- Execution Engine ห้ามหยุดหรือถามผู้ใช้
- อ่าน Error Trace จาก Log → คิดวิเคราะห์รอบด้านและทำ Auto-Fix → รันคำสั่งซ้ำใน Terminal ทันที
- ทำซ้ำจนกว่าจะได้ `EXIT_CODE: 0` เท่านั้น

---

### 6. STRICT VERSION BUMP & RELEASE PROTOCOL

**ห้ามทำ Version Bump, Build Binaries, สร้าง Git Tag หรือ Commit/Push เด็ดขาด จนกว่าจะมีหลักฐาน `EXIT_CODE: 0` จากการรัน LocalCore จริงยืนยัน**

**Version Increment (SemVer):**
- **MAJOR (X.0.0):** เปลี่ยนแปลงสถาปัตยกรรมครั้งใหญ่ หรือมี Breaking Changes
- **MINOR (0.X.0):** เพิ่มฟีเจอร์ใหม่หรือฟังก์ชันหลักที่ผ่านการตรวจแล้ว
- **PATCH (0.0.X):** แก้ไขบั๊ก ปรับปรุงโค้ดภายใน หรือทำ Auto-Fix

**Mandatory Documentation & Audit Trail Sync:**
- ก่อน Build หรือ Commit ต้องอัปเดตเอกสารครบถ้วน (`CHANGELOG.md`, `HISTORY.md` บันทึกประวัติและ Timestamp)
- อัปเดต Version Variable ในโค้ดให้ตรงกันทุกจุด (`pyproject.toml`, `__init__.py`, `setup_builder.iss`)

**Deployment Gateway:**
- Build ไฟล์ Binaries ต่อได้ทันที
- ทำ Git Commit ระบุเลขเวอร์ชัน (เช่น `"chore: release v0.3.20"`)
- Push ขึ้นรีโมทรีโปเป็นขั้นตอนสุดท้าย

---

### 7. PROJECT-SPECIFIC GATEKEEPER COMMANDS

**For doc2md v0.2.1:**

```bash
# Full verification with coverage
pytest tests/ --cov=doc2md --cov-fail-under=90 -v

# Via LocalCore (recommended)
cmd /v:on /c "localcore --verify "pytest tests/ --cov=doc2md --cov-fail-under=90 -v" --model "Qwen-2.5-Coder-7B" & echo EXIT_CODE:!ERRORLEVEL!"

# Quick sanity check
pytest tests/ -x --timeout=10

# Coverage report only
coverage run -m pytest tests/ && coverage report --include=doc2md/*
```

**Expected Metrics:**
- Test Count: ≥252
- Coverage: ≥90%
- Exit Code: 0
- Build Time: <30 seconds

---

### 8. RELEASE CHECKLIST (Post-Verification)

Only proceed after EXIT_CODE: 0 confirmed:

- [ ] All 252+ tests passing
- [ ] Coverage ≥90%
- [ ] CHANGELOG.md updated with [0.2.1] entry
- [ ] HISTORY.md updated with audit trail
- [ ] Version bumped in: `pyproject.toml`, `doc2md/__init__.py`, `setup_builder.iss`
- [ ] Standalone binary built: `dist/doc2md.exe`
- [ ] Windows Installer built: `dist/doc2md_Setup_v0.2.1.exe`
- [ ] Git commit created with release message
- [ ] Git tag v0.2.1 created and pushed
- [ ] GitHub Actions workflows triggered (ci.yml, release.yml)

---

### 9. DOCUMENTATION & AUDIT TRAIL

**HISTORY.md Format:**
```markdown
## [0.2.1] - 2026-08-26

- **Verification timestamp:** 2026-08-26, Gatekeeper Protocol v3.4
- **Result:** `EXIT_CODE:0` — VALIDATION PASSED; Total coverage: 94.08%; `252 passed in 20.40s`
- **Loop iterations:** 1 (no fixes needed)
- **Artifacts:** doc2md.exe (111.8 MB), doc2md_Setup_v0.2.1.exe (112.9 MB)
- **GitHub:** https://github.com/passagain-loui/doc2md/releases/tag/v0.2.1
```

---

### 10. COMMUNICATION PROTOCOL

**Execution Engine to Master Architect:**
- Report EXIT_CODE immediately after gatekeeper run
- Provide clear root-cause analysis for any FAIL
- Request architecture guidance if fixes are unclear

**Master Architect to Execution Engine:**
- Confirm proceeding with release only on EXIT_CODE: 0
- Escalate if loop exceeds 3 iterations
- Approve or reject architecture changes to fix failures

**All to Gatekeeper:**
- Respect exit codes as the source of truth
- No manual overrides without written justification
- All verification runs logged in HISTORY.md

---

### 11. PROJECT CONTEXT

**Repository:** https://github.com/passagain-loui/doc2md
**Current Version:** 1.0.7 (ffprobe-less Duration Probing, Windows No-Console Subprocess Hardening)
**Python:** 3.9+ (tested on 3.10, 3.11, 3.14)
**Platform:** Windows (primary), Linux/macOS (supported)
**Test Framework:** pytest 8.0+ with coverage (pytest-cov)
**Build Tools:** PyInstaller 6.10+, Inno Setup 6

**Key Files:**
- `pyproject.toml` — Package metadata & dependencies
- `tests/` — 28+ test files, 307 tests, 93.45% coverage
- `doc2md/` — 14 core modules, 1,756 statements
- `.github/workflows/` — CI/CD automation (ci.yml, release.yml)
- `CHANGELOG.md` — User-facing release notes
- `HISTORY.md` — Verification audit trail
- `CLAUDE.md` — TRI-AGENT WORKFLOW PROTOCOL v4.4

---

### 12. ESCALATION & FAILURE SCENARIOS

**Scenario: EXIT_CODE 101 (Missing dependencies)**
1. Analyze: Check which module/package is missing
2. Fix: Update `pyproject.toml` or install via pip
3. Re-Verify: Confirm dependency resolution

**Scenario: EXIT_CODE 102 (Test timeout)**
1. Analyze: Identify which test timed out
2. Fix: Increase timeout in `conftest.py` or optimize test
3. Re-Verify: Confirm test completes within time limit

**Scenario: EXIT_CODE 103 (Coverage below 90%)**
1. Analyze: Identify untested code paths
2. Fix: Add tests in `tests/test_*.py`
3. Re-Verify: Confirm coverage ≥90%

**Escalation Trigger:** If loop exceeds 5 iterations → Contact Master Architect for guidance

---

### 12. VERSION HISTORY & COMPLIANCE

| Version | Protocol | Status | Notes |
|---------|----------|--------|-------|
| 4.7 | Complete Master Specification | Active | Current (This Document) - Project Root, Silent Mode, Clean Commands |
| 4.4 | Tri-Agent + Mandated Roles & Traceability | Deprecated | Replaced by v4.7 |
| 4.3 | Tri-Agent + Strict Anti-Simulation | Deprecated | Replaced by v4.4 |
| 4.2 | Tri-Agent + Responsibility Matrix | Deprecated | Replaced by v4.3 |
| 4.1 | Tri-Agent + Re-Verification | Deprecated | Replaced by v4.2 |
| 4.0 | Tri-Agent | Deprecated | Replaced by v4.1 |
| 3.4 | Gatekeeper v3 | Deprecated | Original protocol |

**Compliance:** All releases ≥0.3.2 must follow Protocol v4.7

---

**Recent Releases (Protocol v4.7):**
- v1.0.7 (2026-08-29): ffprobe-less duration probing (fixes progress bar stuck at 0%), Windows no-console subprocess hardening, bounded exit cleanup
- v1.0.6 (2026-08-29): Decoupled main-thread queue polling architecture (task_queue/result_queue)
- v1.0.5 (2026-08-29): Hard Exit Protocol, grid geometry fix, combobox/progress label styling
- v1.0.4 (2026-08-29): Numeric percentage progress bar, removed static "Processing..." overlay
- v1.0.3 (2026-08-29): Force-embedded FFmpeg binary into standalone executable
- v1.0.0 (2026-08-29): Major production release - thread-safe race condition prevention, bulletproof audio crash guard
- v0.3.20 (2026-08-27): Clean build pipeline, High-DPI crisp text, stop conversion button
- v0.3.19 (2026-08-27): Force kill process before setup extraction
- v0.3.18 (2026-08-27): Automatic application termination during setup
- v0.3.17 (2026-08-27): Modern dark UI overhaul, extended audio timeout (1800s), spinner animation

**Last Updated:** 2026-08-29 (Protocol v4.7 - Complete Master Specification, v1.0.7)
**Next Review:** After v1.1.0 release
**Maintainer:** doc2md Development Team
````
`````
``````
```````
````````
`````````
``````````
```````````
````````````
`````````````
``````````````
```````````````
````````````````
`````````````````
``````````````````
```````````````````
````````````````````
`````````````````````
``````````````````````
```````````````````````
````````````````````````
`````````````````````````
``````````````````````````
```````````````````````````
````````````````````````````
`````````````````````````````
``````````````````````````````
```````````````````````````````
````````````````````````````````
`````````````````````````````````
``````````````````````````````````
```````````````````````````````````
````````````````````````````````````
`````````````````````````````````````
``````````````````````````````````````
```````````````````````````````````````
````````````````````````````````````````
