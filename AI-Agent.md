# AI Agent Architecture for SIS & Parent Portal (Final Design)

## 1. Mục tiêu tổng thể

Xây dựng hệ thống AI Agent on‑premise để:

- Truy vấn dữ liệu SIS (MariaDB) theo thời gian thực.
- Đọc & hiểu tài liệu nội bộ qua RAG.
- Kết hợp reasoning đa bước (hybrid agent).
- Đảm bảo bảo mật dữ liệu học sinh, phụ huynh.
- Dễ mở rộng, dễ triển khai trên cloud nội bộ (CMC).

---

## 2. Kiến trúc tổng thể hệ thống

Hệ thống chia thành 3 nhóm máy chủ:

### **A. GPU LLM Inference Node**

Chỉ chạy mô hình LLM:

- Model: Qwen 2.5 72B hoặc Llama 3.1 70B (quantized Q4_K_M).
- Framework: vLLM hoặc SGLang.
- Expose API chuẩn OpenAI:
  - `/v1/chat/completions`
  - `/v1/completions`
  - `/v1/embeddings` (tùy chọn)

**Yêu cầu phần cứng (CMC Cloud EC2 GPU):**

- 1× NVIDIA A100 40GB
- 16 vCPU (khuyến nghị 24–32 vCPU để mạnh hơn)
- 64GB RAM (khuyến nghị 96–128GB để mượt)
- 1TB NVMe SSD
- Ubuntu 22.04 + Docker + NVIDIA Container Toolkit

---

### **B. AI Backend (EC2 thường, không GPU)**

Chứa toàn bộ logic “agent”:

- FastAPI
- LangChain / LlamaIndex
- SQL Agent (MariaDB)
- RAG Router
- Document Router (policy vs dynamic DB)
- Auth + RBAC mapping (phụ huynh → student_id)

Chức năng:

- Nhận câu hỏi từ Portal/Mobile.
- Phân tích loại câu hỏi → chọn nguồn dữ liệu:
  - SQL Agent → SIS Database
  - RAG → Vector DB
  - Hybrid → cả hai
- Gọi LLM tại GPU Node → tổng hợp câu trả lời.
- Bảo mật & chuẩn hoá output theo văn phong nhà trường.

---

### **C. Vector DB Server (EC2 thường)**

- Qdrant (khuyên dùng) hoặc Valkey+RediSearch.
- Lưu embedding của tất cả tài liệu PDF/DOCX/HTML.
- Tìm kiếm ngữ nghĩa (semantic search).
- Mỗi chunk có metadata:
  - page
  - filename
  - document type
  - permission flags (RBAC)
  - created_at / versioning

---

## 3. Pipeline 1 – Document Ingestion → Vector DB (RAG)

Quy trình:

### **Step 1: Load tài liệu**

Nguồn tài liệu:

- PDF text‑based
- DOCX có heading
- Markdown
- HTML từ intranet
- Không dùng PDF scan (nếu có → OCR trước)

Thư viện:

- PyMuPDF
- docx2txt
- BeautifulSoup
- unstructured

---

### **Step 2: Chunking**

- 300–800 token/chunk
- 50–150 token overlap
- Chunk theo heading nếu có → độ chính xác tối đa.

---

### **Step 3: Embedding**

Model embedding:

- `bge-m3` (recommended)
- e5-large-v2
- Qwen embeddings (nếu muốn nội bộ hoàn toàn)

---

### **Step 4: Lưu vào Vector DB**

Format payload:

```
{
  "id": "hocphi_2024_p3_c1",
  "vector": [...],
  "payload": {
    "source": "hocphi_2024.pdf",
    "doctype": "hocphi",
    "page": 3,
    "grade": "THCS",
    "text": "Phụ huynh đóng học phí trước ngày 05 hàng tháng..."
  }
}
```

---

## 4. Pipeline 2 – Dataset Generation → Fine‑tuning

Dùng để huấn luyện LLM hiểu đặc thù nhà trường.

### **Step 1: Tải tài liệu vào Easy Dataset**

- Quy chế học vụ
- Học phí
- Quy trình bus
- Quy định nghỉ phép
- FAQ phụ huynh
- SOP nội bộ

Easy Dataset:

- Trích xuất text
- Chunk thông minh
- Gợi ý câu hỏi tự động

---

### **Step 2: Tạo Q&A (Instruction Dataset)**

Ví dụ:

```
{"instruction": "Hạn nộp học phí THCS?", "output": "Trước ngày 05 hàng tháng."}
```

Người dùng có thể duyệt, sửa, lọc.

---

### **Step 3: Export JSONL**

Chuẩn đầu vào của LLaMA Factory:

```
{"instruction": "...", "output": "..."}
```

---

### **Step 4: Fine‑tune (LoRA / QLoRA)**

Ví dụ:

```
llamafactory train \
  --model_name_or_path qwen-2.5-32b \
  --data_path dataset.jsonl \
  --output_dir ./models/ft-sis \
  --training_type lora \
  --num_train_epochs 3 \
  --lora_rank 16
```

Xuất ra:

- `adapter_model.bin` (LoRA)
- hoặc full merged model.

---

### **Step 5: Deploy model lên LLM GPU Node**

Chạy với vLLM:

```
docker run --gpus all --ipc=host --network host \
  -v /opt/models:/models \
  vllm/vllm-openai:latest \
  --model /models/llama-3.1-70b-q4_k_m \
  --port 8000
```

AI Backend → gọi API:

```
POST http://llm-node:8000/v1/chat/completions
```

---

## 5. Cách RAG + SQL Agent + Fine‑tune phối hợp

### Khi user hỏi:

> "Con tôi còn bao nhiêu học phí tháng này và hạn đóng?"

AI Backend thực hiện:

1. **Intent detection**

   - Học phí → cần SQL + RAG.

2. **SQL Agent**

   - Sinh SQL đúng schema:

   ```
   SELECT amount_due FROM tuition
   WHERE student_id=? AND month=?
   ```

3. **RAG Search**

   - Query Vector DB → lấy quy định hạn đóng tiền.

4. **LLM reasoning**
   - Kết hợp live DB + tài liệu nội bộ.
   - Trả lời theo văn phong nhà trường.

→ Đây là “Triple Hybrid Agent”.

---

## 6. Chuẩn tài liệu nội bộ (sample chuẩn)

Tài liệu nên dạng:

### DOCX (ưu tiên)

```
# 1. Quy định học phí 2024–2025
## 1.1 Phạm vi
Áp dụng cho lớp 1–12.

## 1.2 Hạn nộp học phí
Phụ huynh nộp trước ngày 05 hàng tháng.
```

### Markdown

```
## Quy định đi lại bằng xe bus
- Học sinh có thẻ bus hợp lệ.
- Giờ đón: 6:30–6:55.
```

### Tránh:

- PDF scan
- Ảnh chụp
- File mất heading

---

## 7. Tóm tắt kiến trúc 1 GPU Node + nhiều EC2

```
Parent Portal / SIS
       ↓
AI Backend (Agent) — EC2 thường
       ↓
Vector DB (Qdrant) — EC2 thường
       ↓
LLM Node (A100 40GB) — inference only
       ↓
MariaDB SIS — EC2/Managed DB
```

---

## 8. Trạng thái final của kiến trúc

- Chỉ **1** máy GPU chạy model.
- Các service khác chạy EC2 thường.
- Pipeline ingest + fine‑tune đầy đủ.
- Agent reasoning đa tầng (SQL + RAG + Fine‑tune).
- Đáp ứng chuẩn SIS/Parent Portal enterprise.

```

```
