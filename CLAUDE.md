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

## TRI-AGENT WORKFLOW PROTOCOL (v4.4 — MANDATED ROLES & TRACEABILITY)

This document outlines the collaborative workflow between three AI agents and the gatekeeper system for ensuring code quality and automated verification with ZERO-TOLERANCE anti-simulation enforcement and mandatory Log traceability.

### 1. AI ROLES & EXPLICIT RESPONSIBILITIES

**Master Architect (Gemini)**
- หน้าที่: ออกแบบสถาปัตยกรรมระดับสูง วิเคราะห์ภาพรวม และออกคำสั่งแบบ Structured Task
- ข้อจำกัด: เป็นผู้วางแผนและสั่งการ ห้ามลงมือแก้ไขโค้ดในโปรเจกต์โดยตรง

**Execution Engine (Claude Code / OpenCode)**
- หน้าที่: รับคำสั่งจาก Master Architect, เขียนโค้ด, ทำ Auto-Fix, และรันคำสั่งผ่าน Terminal จริงตามโปรโตคอล
- ข้อจำกัด: ห้ามแอบอ้างผลลัพธ์ (No Simulation) และห้ามข้ามขั้นตอนการตรวจสอบ

**Gatekeeper Auditor (LocalCore CLI)**
- หน้าที่: สแกนตรวจสอบโค้ดแบบ Read-Only และพ่นค่า EXIT_CODE ออกมาทาง stdout พร้อมบันทึก Log ลงระบบ
- ข้อจำกัด: เป็นผู้ตรวจทานความถูกต้องเด็ดขาด ไม่ทำการแก้ไขโค้ดเอง

---

### 2. MANDATORY GATEKEEPER EXECUTION RULE

Execution Engine ต้องรันคำสั่งผ่าน Windows PATH และ Delayed Expansion (/v:on) ใน Terminal จริงเท่านั้น:

```batch
cmd /v:on /c "localcore --verify --model "<MODEL_NAME>" & echo EXIT_CODE:!ERRORLEVEL!"
```

**หมายเหตุ:** แทนที่ `<MODEL_NAME>` ด้วยโมเดลจริง เช่น `Qwen-2.5-Coder-14B`, `claude-opus`, หรือ `claude-sonnet` (หากมีการติดตั้ง)

---

### 3. STRICT ANTI-SIMULATION & LOG TRACEABILITY (ZERO-TOLERANCE)

**ห้ามใช้คำสั่งเทสภายใน:**
- ❌ **PROHIBITED:** ใช้ pytest, cargo test, npm test เดี่ยวๆ แล้วนำ Exit Code มาอ้างอิงแทน LocalCore เด็ดขาด
- ❌ **PROHIBITED:** การจำลอง (Simulate) หรือแอบอ้างผลลัพธ์ LocalCore ออกมาแบบไม่จริง
- ❌ **PROHIBITED:** ข้ามขั้นตอนการตรวจสอบและลงมือทำ Version Bump, Build, หรือ Git Commit

**บังคับให้ใช้ LocalCore จริง:**
- ✅ **REQUIRED:** บังคับให้ข้อมูลและ Request ต้องวิ่งเข้าประมวลผลผ่าน LocalCore CLI จริงเท่านั้น
- ✅ **REQUIRED:** ต้องปรากฏ Log หลักฐานของการทำงาน (Log Trace) ในระบบ LocalCore
- ✅ **REQUIRED:** หากผลลัพธ์แสดง EXIT_CODE: 0 แต่ไม่มีร่องรอยการทำงานหรือ Log วิ่งผ่าน LocalCore จะถือว่า "เป็นโมฆะทันที" (Invalid Execution)

**VIOLATION CONSEQUENCES:**
- Protocol non-compliance ถ้าใช้ exit code ที่เดาหรือจำลอง ไม่ได้จากการรัน LocalCore จริง
- ห้ามทำ Version Bump, Build, Commit ได้เลย หากไม่มีหลักฐาน EXIT_CODE: 0 จาก LocalCore จริง
- หากไม่ได้ EXIT_CODE จาก LocalCore จริง ต้อง HALT และบันทึกการเบี่ยงเบนโปรโตคอล

---

### 4. AUTOMATED RE-VERIFICATION LOOP

**INITIAL CHECK:**
- รันคำสั่งผ่าน Gatekeeper หากได้ EXIT_CODE: 0 ให้ไปขั้นตอน Release ทันที

**FAIL LOOP:**
หาก EXIT_CODE != 0 (FAIL):
- Execution Engine ห้ามหยุดทำงานและห้ามถามผู้ใช้
- อ่าน Error Trace จาก Log ของ LocalCore → ทำการแก้ไขโค้ด (Auto-Fix) → สั่งรันคำสั่ง Gatekeeper ซ้ำใน Terminal จริงทันที
- ทำซ้ำจนกว่า LocalCore จะพ่นค่า EXIT_CODE: 0 ออกมาจริงๆ เท่านั้น

**[STEP 1] TASK CREATION & ARCHITECTURE (เจ้าของ: Gemini)**
- Gemini ทำการวิเคราะห์ปัญหา วางโครงสร้างการแก้ไข และออกคำสั่ง [TASK] ให้ Execution Engine

**[STEP 2] CODE IMPLEMENTATION (เจ้าของ: Claude / OpenCode)**
- Claude / OpenCode ทำการแก้ไขโค้ดใน Codebase ให้เรียบร้อยตามคำสั่ง

**[STEP 3] GATEKEEPER VERIFICATION (เจ้าของ: LocalCore CLI)**
- Claude / OpenCode รันคำสั่ง Gatekeeper ผ่าน Terminal จริง
- LocalCore ประมวลผล แล้วพ่น EXIT_CODE ออกมา พร้อมบันทึก Log ลงระบบ

**[STEP 4] RELEASE DEPLOYMENT (เจ้าของร่วม: Claude / OpenCode & LocalCore)**
- ห้ามทำการ Bump Version, Build Binaries, หรือ Git Commit ได้เลย หากไม่มีหลักฐาน EXIT_CODE: 0 จาก LocalCore จริง

### 5. STRICT EXIT & DEPLOYMENT CONDITION

งานจะเสร็จสมบูรณ์และอนุญาตให้ทำ Version Bump, Build Binaries, รวมถึง Git Commit/Push ได้ ก็ต่อเมื่อมีหลักฐาน Log และ EXIT_CODE: 0 จากการรัน LocalCore จริงยืนยันเท่านั้น!

---

### 6. PROJECT-SPECIFIC GATEKEEPER COMMANDS

**For doc2md v0.2.1:**

```bash
# Full verification with coverage
pytest tests/ --cov=doc2md --cov-fail-under=90 -v

# Via LocalCore (recommended)
cmd /v:on /c "localcore --verify "pytest tests/ --cov=doc2md --cov-fail-under=90 -v" --model "Qwen-2.5-Coder-14B" & echo EXIT_CODE:!ERRORLEVEL!"

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

### 7. RELEASE CHECKLIST (Post-Verification)

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

### 8. DOCUMENTATION & AUDIT TRAIL

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

### 9. COMMUNICATION PROTOCOL

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

### 10. PROJECT CONTEXT

**Repository:** https://github.com/passagain-loui/doc2md
**Current Version:** 0.3.2 (Auto-Launch GUI Fix)
**Python:** 3.9+ (tested on 3.10, 3.11, 3.14)
**Platform:** Windows (primary), Linux/macOS (supported)
**Test Framework:** pytest 8.0+ with coverage (pytest-cov)
**Build Tools:** PyInstaller 6.10+, Inno Setup 6

**Key Files:**
- `pyproject.toml` — Package metadata & dependencies
- `tests/` — 28+ test files, 303 tests, 93.68% coverage
- `doc2md/` — 14 core modules, 1,710 statements
- `.github/workflows/` — CI/CD automation (ci.yml, release.yml)
- `CHANGELOG.md` — User-facing release notes
- `HISTORY.md` — Verification audit trail
- `CLAUDE.md` — TRI-AGENT WORKFLOW PROTOCOL v4.4

---

### 11. ESCALATION & FAILURE SCENARIOS

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
| 4.4 | Tri-Agent + Mandated Roles & Traceability | Active | Current (This Document) |
| 4.3 | Tri-Agent + Strict Anti-Simulation | Deprecated | Replaced by v4.4 |
| 4.2 | Tri-Agent + Responsibility Matrix | Deprecated | Replaced by v4.3 |
| 4.1 | Tri-Agent + Re-Verification | Deprecated | Replaced by v4.2 |
| 4.0 | Tri-Agent | Deprecated | Replaced by v4.1 |
| 3.4 | Gatekeeper v3 | Deprecated | Original protocol |

**Compliance:** All releases ≥0.3.2 must follow Protocol v4.4

---

**Last Updated:** 2026-08-27 (Protocol v4.4)
**Next Review:** After v0.4.0 release
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
