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

## TRI-AGENT WORKFLOW PROTOCOL (v4.2 — RESPONSIBILITY & RE-VERIFICATION)

This document outlines the collaborative workflow between three AI agents and the gatekeeper system for ensuring code quality and automated verification.

### 1. AI ROLES & RESPONSIBILITY MATRIX

**Master Architect (Gemini)**
- หน้าที่: ออกแบบสถาปัตยกรรม, วิเคราะห์ Root Cause ระดับภาพรวม, กำหนดเป้าหมาย และออกคำสั่งแบบ Structured Task
- ขอบเขต: เป็นผู้สั่งการหลัก ไม่เขียนโค้ดลงไฟล์โดยตรง

**Execution Engine (Claude Code / OpenCode)**
- หน้าที่: อ่านคำสั่งจาก Gemini, เขียน/แก้ไขโค้ดในระบบ, รันระบบ Auto-Fix และยิงคำสั่งตรวจทานซ้ำ
- ขอบเขต: เป็นผู้ลงมือปฏิบัติการ รับผิดชอบการวิ่ง Loop จนกว่างานจะสำเร็จ 100%

**Gatekeeper Auditor (LocalCore CLI)**
- หน้าที่: สแกนโค้ดแบบ Read-Only, รัน Automated Test (Cargo/NPM/Pytest) และส่งคืนค่า Exit Code
- ขอบเขต: เป็นผู้ตรวจข้อสอบ ไม่แก้ไขโค้ด และไม่รันซ้ำเองจนกว่าจะได้รับคำสั่งยิง Verify ใหม่

---

### 2. GATEKEEPER EXECUTION RULE

**ALWAYS use global Windows PATH and Delayed Expansion (/v:on) to capture accurate exit codes:**

```batch
cmd /v:on /c "localcore --verify --model "<MODEL_NAME>" & echo EXIT_CODE:!ERRORLEVEL!"
```

**Note:** Execution Engine must replace `<MODEL_NAME>` with the active local LLM:
- Default: `Qwen-2.5-Coder-14B`
- Alternative: `claude-opus`, `claude-sonnet` (if available)

---

### 3. STEP-BY-STEP WORKFLOW & ACTION OWNERSHIP

**[STEP 1] TASK CREATION & ARCHITECTURE (เจ้าของ: Gemini)**
- Gemini ทำการวิเคราะห์ปัญหา วางโครงสร้างการแก้ไข และออกคำสั่ง [TASK] ให้ Execution Engine

**[STEP 2] CODE IMPLEMENTATION (เจ้าของ: Claude / OpenCode)**
- Claude / OpenCode ทำการแก้ไขโค้ดใน Codebase แบบ One-Shot ให้เรียบร้อยตามคำสั่ง

**[STEP 3] INITIAL GATEKEEPER AUDIT (เจ้าของ: LocalCore CLI)**
- Claude / OpenCode รันคำสั่ง Gatekeeper Execution Rule
- LocalCore ประมวลผลและคืนค่า EXIT_CODE (0=PASS, 101/102/103=FAIL)

**[STEP 4] EVALUATION & AUTO-RETRY LOOP (เจ้าของร่วม: Claude / OpenCode & LocalCore)**

* กรณี EXIT_CODE เป็น 0 (PASS):
 - Claude / OpenCode ทำการ Bump Version, บันทึกประวัติใน CHANGELOG/HISTORY และสรุปจบงานส่ง Gemini
* กรณี EXIT_CODE ไม่เท่ากับ 0 (FAIL: 101, 102, 103):
 - Claude / OpenCode ห้ามหยุดทำงานและห้ามถามผู้ใช้
 - Claude / OpenCode อ่าน Log Error จาก LocalCore → แก้ไขโค้ดทันที → สั่งรัน Step 3 ซ้ำอีกรอบ
 - LocalCore ทำการตรวจซ้ำ (Re-Verify) และส่งค่า EXIT_CODE ใหม่อีกครั้ง
 - วนลูป Step 3 และ Step 4 ซ้ำจนกว่า LocalCore จะส่งคืนค่า EXIT_CODE: 0 เท่านั้น

### 4. STRICT COMPLETION RULE

งานจะถูกตัดสินว่าเสร็จสิ้นสมบูรณ์ (Complete) ก็ต่อเมื่อ LocalCore คืนค่า EXIT_CODE: 0 ในการตรวจครั้งล่าสุดเท่านั้น!

---

### 5. PROJECT-SPECIFIC GATEKEEPER COMMANDS

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

### 6. RELEASE CHECKLIST (Post-Verification)

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

### 7. DOCUMENTATION & AUDIT TRAIL

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

### 8. COMMUNICATION PROTOCOL

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

### 9. PROJECT CONTEXT

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
- `CLAUDE.md` — TRI-AGENT WORKFLOW PROTOCOL v4.2

---

### 10. ESCALATION & FAILURE SCENARIOS

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

### 11. VERSION HISTORY & COMPLIANCE

| Version | Protocol | Status | Notes |
|---------|----------|--------|-------|
| 4.2 | Tri-Agent + Responsibility Matrix | Active | Current (This Document) |
| 4.1 | Tri-Agent + Re-Verification | Deprecated | Replaced by v4.2 |
| 4.0 | Tri-Agent | Deprecated | Replaced by v4.1 |
| 3.4 | Gatekeeper v3 | Deprecated | Original protocol |

**Compliance:** All releases ≥0.3.2 must follow Protocol v4.2

---

**Last Updated:** 2026-08-26
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
