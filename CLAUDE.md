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
# CLAUDE.md

```text
# doc2md v1.0.13

## 1. Role & Execution Guidelines
- **Role:** คุณคือ Execution Engine ทำหน้าที่คิดวิเคราะห์จุดแก้ไขและจุดเชื่อมโยงทั้งหมดอย่างรอบด้าน เพื่อแก้ไขโค้ดให้สมบูรณ์ครบจบในรอบเดียวและประหยัด Token
- **UI Standard:** งานส่วน UI ทั้งหมดต้องใช้ Modern Styling/Modern SVG Icons เท่านั้น ห้ามปล่อย Native Windows Classic Style หรือ UI แบบดั้งเดิมที่ไม่ได้ปรับแต่งเด็ดขาด
- **Discretion Boundary:** หากพบจุดผิดพลาดเชิงสถาปัตยกรรม ความเสี่ยง หรือคำสั่งที่ไม่ชัดเจน สามารถทักท้วงและเสนอแนะทางเลือกที่เหมาะสมได้ทันที

## 2. Deterministic Pipeline Execution Sequence
เมื่อรับ Task พัฒนาหรือแก้ไขระบบ ให้ปฏิบัติตามลำดับ Step 1 ➔ Step 6 ดังนี้:

1. **Step 1 (Code Updates):** ดำเนินการแก้ไขโค้ดตามโจทย์งานให้ครบถ้วนทุกโมดูลที่เกี่ยวข้อง
2. **Step 2 (Cache Purge):** ล้างโฟลเดอร์แคชของโปรเจกต์ (`__pycache__`, `bin/`, `obj/`, `build/`, `dist/`, `.cache`)
3. **Step 3 (QA & Gatekeeper Verification):** สั่งรันคำสั่ง Terminal เพื่อตรวจสอบความถูกต้องผ่าน LocalCore CLI ดังนี้:
 `powershell -ExecutionPolicy Bypass -File ./tools/verify.ps1`
4. **Step 4 (Strict Re-Validation, Zero-Assumption & Auto-Fix Loop):**
 - อ่านทั้ง `EXIT_CODE` และ Text Log สดๆ จาก Terminal ใน Step 3
 - **กรณี `EXIT_CODE: 0` (PASS):** ตรวจสอบใน Log ต้องไม่มีคำว่า `VALIDATION FAILED`, `No command given`, `is not recognized` หรือ `Background task failed` หากสะอาด 100% จึงจะอนุญาตให้ไป Step 5 (Packaging & Build)
 - **กรณี `EXIT_CODE != 0` หรือพบ Failure Log / Terminal Execution Failure (FAIL/ERROR):**
 - **STRICT HARD STOP:** ห้ามลักไก่ข้ามไป Step 5 (Build) เด็ดขาด
 - **NO SANDBOX EXCUSES:** ห้ามอ้างคำว่า "Known limitation", "Sandbox restriction" หรือเอาผล pytest ในอดีตมาสวมรอยเพื่อข้ามกระบวนการเด็ดขาด หาก Terminal รันพัง ให้แก้ไขวิธีสั่งรันคำสั่งจนกว่าสคริปต์จะทำงานและส่งคืนผลลัพธ์สดๆ ได้สำเร็จ
 - **ดำเนินการอัตโนมัติทันที:** วนกลับไป **Step 1** เพื่อแก้ไขโค้ด/สคริปต์/คำสั่ง ➔ **Step 2** (Purge Cache) ➔ **Step 3** (รัน `./tools/verify.ps1` ตรวจซ้ำให้อัตโนมัติ)
 - **ต้องส่งตรวจใหม่ซ้ำไปเรื่อยๆ จนกว่าจะได้รับ `EXIT_CODE: 0` ของจริงจากการรันรอบปัจจุบันเท่านั้น**
5. **Step 5 (Packaging & Build):** เมื่อผ่านการอนุมัติ `EXIT_CODE: 0` ของจริงจาก LocalCore CLI ในรอบปัจจุบันแล้ว ให้ดำเนินการสร้าง Release Build (จำกัดการใช้ CPU/RAM ไม่เกิน 85%)
6. **Step 6 (Sync & Audit Trail):** อัปเดต `CHANGELOG.md`, `HISTORY.md` และปรับเลขเวอร์ชัน (SemVer) ให้ตรงกันทุกจุด

## 3. Anti-Bypass Rules
- ห้าม Claude เขียนสคริปต์อื่นมาสวมรอยแทนการตรวจของ LocalCore CLI
- ห้ามอ้างเหตุผลด้าน Environment/Sandbox เพื่อข้ามไป Step 5 โดยไม่มีผล `EXIT_CODE: 0` ของจริง
- ทุกการแก้ไขโค้ดใน Step 1 บังคับต้องวนกลับมาสั่งรัน Step 3 ตรวจซ้ำให้อัตโนมัติทันที
```
````
`````
``````
```````
````````
