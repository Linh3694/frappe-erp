# Report Card Approval Flow - Test Checklist

## Cách chạy Automated Tests

```bash
# Unit Tests (không cần database) - Bao gồm tests cho refactored modules
bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.run_all_tests

# Chạy từng test riêng lẻ:
bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_module_imports
bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_constants_module
bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_helpers_module
bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_validators_module
bench --site [sitename] execute erp.api.erp_sis.report_card.test_approval.test_utils_new_helpers

# Integration Tests (cần database có data)
bench --site [sitename] execute erp.api.erp_sis.report_card.test_integration.run_all_tests
```

## Module Structure After Refactoring

```
report_card/
├── __init__.py
├── approval.py              # API endpoints (giữ nguyên interface)
├── approval_helpers/        # Helper functions (NEW)
│   ├── __init__.py
│   └── helpers.py
├── constants.py             # Centralized constants (NEW)
├── utils.py                 # Utilities (extended)
├── validators.py            # Validators (extended)
├── test_approval.py         # Unit tests (updated)
├── test_integration.py
└── TEST_CHECKLIST.md
```

---

## Manual Test Checklist

### 1. Submit Flow

#### VN Program (scores)
- [ ] Tạo template VN với scores_enabled
- [ ] Nhập điểm cho 1 môn
- [ ] Click Submit → Kiểm tra toast success
- [ ] Refresh → Kiểm tra trạng thái "Đã gửi"
- [ ] Submit lại môn đã submit → Kiểm tra toast "Đã được gửi trước đó"

#### VN Program (subject_eval)
- [ ] Tạo template VN với subject_eval_enabled
- [ ] Nhập đánh giá cho 1 môn
- [ ] Click Submit → Kiểm tra toast success

#### INTL Program (main_scores)
- [ ] Tạo template INTL
- [ ] Nhập điểm main_scores cho 1 môn
- [ ] Click Submit → Kiểm tra toast success "Điểm INTL"

#### INTL Program (ielts)
- [ ] Enable IELTS cho môn học
- [ ] Nhập điểm IELTS
- [ ] Click Submit → Kiểm tra toast success "IELTS"

#### INTL Program (comments)
- [ ] Enable comments
- [ ] Nhập nhận xét
- [ ] Click Submit → Kiểm tra toast success "Nhận xét INTL"

#### Homeroom
- [ ] Enable homeroom trong template
- [ ] Nhập nhận xét GVCN
- [ ] Click Submit → Kiểm tra toast success

---

### 2. Approval List

#### Hiển thị pending items
- [ ] Truy cập trang Approval List
- [ ] Kiểm tra hiển thị đúng số lượng pending theo level
- [ ] Filter theo Level 1 → Chỉ hiện homeroom
- [ ] Filter theo Level 2 → Hiện subjects (bao gồm IELTS nếu có)
- [ ] Kiểm tra `board_type` hiển thị đúng trong URL khi click vào item

---

### 3. Approve Flow

#### Level 1 (Khối trưởng - Homeroom)
- [ ] Click vào pending homeroom item
- [ ] Kiểm tra hiển thị đúng data
- [ ] Click Approve → Toast success
- [ ] Kiểm tra chuyển sang Level 2

#### Level 2 (Subject Manager - Scores/IELTS)
- [ ] Click vào pending scores item
- [ ] Kiểm tra hiển thị đúng data theo `board_type`
- [ ] Click Approve → Toast success
- [ ] Kiểm tra approval lưu vào data_json per-subject

#### Level 2 - IELTS specific
- [ ] Submit IELTS cho 1 môn
- [ ] Kiểm tra pending list hiện `board_type: "ielts"`
- [ ] Click Approve
- [ ] Kiểm tra CHỈ IELTS được approve, không affect main_scores/comments

---

### 4. Reject Flow (Per-Subject)

#### Reject scores subject
- [ ] Có 2 môn đã submit: Math và English
- [ ] Reject Math
- [ ] Kiểm tra Math → "rejected", English vẫn → "submitted"
- [ ] Kiểm tra message hiển thị đúng lý do

#### Reject IELTS subject
- [ ] Có môn với main_scores và ielts đều submitted
- [ ] Reject chỉ IELTS
- [ ] Kiểm tra IELTS → "rejected", main_scores vẫn → "submitted"

#### Reject homeroom
- [ ] Submit homeroom và scores
- [ ] Reject homeroom
- [ ] Kiểm tra homeroom → "rejected", scores không bị affect

#### Re-submit sau reject
- [ ] Sau khi bị reject, sửa và submit lại
- [ ] Kiểm tra trạng thái chuyển từ "rejected" → "submitted"
- [ ] Kiểm tra rejection_reason bị clear

---

### 5. Level 3 & 4 (Review & Publish)

#### Điều kiện Level 3
- [ ] Kiểm tra chỉ hiển thị khi tất cả sections đã Level 2 approved
- [ ] Nếu chưa đủ → Alert hiển thị progress

#### Approve Level 3
- [ ] Click Approve → Chuyển sang "reviewed"
- [ ] Kiểm tra tất cả subjects trong data_json đều updated

#### Publish Level 4
- [ ] Click Publish → Chuyển sang "published"
- [ ] Kiểm tra `is_approved = 1`
- [ ] Kiểm tra notification được gửi

---

### 6. Counters & Progress

- [ ] Kiểm tra `homeroom_l2_approved` đúng (0 hoặc 1)
- [ ] Kiểm tra `scores_l2_approved_count` đếm đúng
- [ ] Kiểm tra `intl_l2_approved_count` đếm đúng (bao gồm main_scores + ielts + comments)
- [ ] Kiểm tra `all_sections_l2_approved` đúng

---

### 7. Edge Cases

#### Empty sections
- [ ] Template có homeroom nhưng chưa nhập → Không block submit scores
- [ ] Template không có IELTS → Tab IELTS không hiện

#### Mixed programs
- [ ] Subject có cả VN scores và INTL scores → Kiểm tra không conflict

#### Concurrent edits
- [ ] 2 users cùng approve 1 subject → Kiểm tra không lỗi

---

## Database Verification Queries

```sql
-- Kiểm tra approval trong data_json
SELECT 
    name,
    JSON_EXTRACT(data_json, '$.scores.SUBJECT_ID.approval.status') as scores_status,
    JSON_EXTRACT(data_json, '$.intl.ielts.SUBJECT_ID.approval.status') as ielts_status,
    JSON_EXTRACT(data_json, '$.homeroom.approval.status') as homeroom_status
FROM `tabSIS Student Report Card`
WHERE template_id = 'TEMPLATE_ID'
LIMIT 10;

-- Kiểm tra counters
SELECT 
    name,
    homeroom_l2_approved,
    scores_l2_approved_count,
    scores_total_count,
    intl_l2_approved_count,
    intl_total_count
FROM `tabSIS Student Report Card`
WHERE template_id = 'TEMPLATE_ID'
LIMIT 10;
```

---

## Expected Results Summary

| Action | Board Type | Affected | Not Affected |
|--------|------------|----------|--------------|
| Submit scores | scores | scores.{subj}.approval | Tất cả khác |
| Submit ielts | ielts | intl.ielts.{subj}.approval | main_scores, comments |
| Approve scores | scores | scores.{subj}.approval | Tất cả khác |
| Approve ielts | ielts | intl.ielts.{subj}.approval | main_scores, comments |
| Reject scores | scores | CHỈ scores.{subj}.approval | Tất cả khác |
| Reject ielts | ielts | CHỈ intl.ielts.{subj}.approval | main_scores, comments, VN scores |
| Reject homeroom | homeroom | CHỈ homeroom.approval | Tất cả scores sections |
