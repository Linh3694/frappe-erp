# AI Agent Implementation Guide (Step-by-Step)

Tài liệu này hướng dẫn triển khai toàn bộ hệ thống AI Agent cho SIS + Parent Portal theo đúng kiến trúc đã thiết kế trong `AI-Agent.md`.

---

# 1. Chuẩn bị hạ tầng

## 1.1. GPU LLM Node (CMC Cloud)

- EC2 GPU:
  - 1× NVIDIA A100 40GB
  - 16–32 vCPU
  - 64–128GB RAM
  - 1TB NVMe SSD
- OS: Ubuntu 22.04
- Cài đặt:
  ```
  sudo apt update && sudo apt upgrade -y
  sudo apt install docker.io docker-compose -y
  sudo apt install nvidia-driver-535
  sudo apt install nvidia-container-toolkit
  ```

## 1.2. Backend + RAG Servers (EC2 thường)

- 4–8 vCPU
- 16–32GB RAM
- Services chạy:
  - FastAPI (AI backend & agent)
  - Qdrant (Vector DB)
  - Embedding service (tùy chọn)
  - MariaDB client + connector

---

# 2. Triển khai LLM Node (GPU)

## 2.1. Tải model 70B (quantized)

Upload vào thư mục `/opt/models`:

Ví dụ:

```
/opt/models/llama-3.1-70b-q4_k_m
```

## 2.2. Chạy vLLM server

```
docker run --gpus all --ipc=host --network host \
  -v /opt/models:/models \
  vllm/vllm-openai:latest \
  --model /models/llama-3.1-70b-q4_k_m \
  --port 8000 \
  --max-model-len 8192
```

LLM API mở tại:

```
POST http://<gpu-node-ip>:8000/v1/chat/completions
```

---

# 3. Triển khai Vector DB (Qdrant)

## 3.1. Docker Compose

```
version: "3.9"
services:
  qdrant:
    image: qdrant/qdrant
    restart: always
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant-data:/qdrant/storage
```

## 3.2. Khởi động

```
docker compose up -d
```

---

# 4. Pipeline Ingest Tài liệu → Vector DB

## 4.1. Chuẩn bị thư mục tài liệu

```
/data/documents/raw
/data/documents/processed
```

## 4.2. Script Python load PDF/DOCX

```
import fitz
import docx
from unstructured.partition.auto import partition

def load_document(path):
    return partition(filename=path)
```

## 4.3. Chunking

```
def chunk_text(text, chunk_size=500, overlap=100):
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunks.append(text[i:i+chunk_size])
    return chunks
```

## 4.4. Embedding

```
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("BAAI/bge-large-en-v1.5")

emb = model.encode(chunk_text)
```

## 4.5. Upsert vào Qdrant

```
from qdrant_client import QdrantClient

client = QdrantClient("http://vector-db-ip:6333")

client.upsert(
    collection_name="school_docs",
    points=[{
        "id": chunk_id,
        "vector": emb.tolist(),
        "payload": {"text": chunk, "source": filename}
    }]
)
```

---

# 5. Triển khai AI Backend (Agent + RAG + SQL)

## 5.1. Cấu trúc thư mục

```
/ai-backend
   main.py
   rag.py
   sql_agent.py
   llm.py
   config.py
```

## 5.2. Kết nối đến LLM

```
import openai
openai.api_base = "http://llm-node:8000/v1"
openai.api_key = "none"
```

## 5.3. SQL Agent (MariaDB)

```
import mysql.connector

db = mysql.connector.connect(
  host="db-host",
  user="user",
  password="pwd",
  database="sis"
)
```

## 5.4. Query builder từ LLM

```
prompt = f"""
Bạn là SQL expert. Sinh câu query MariaDB dựa trên câu hỏi:
{user_question}
Schema:
students(id, full_name, class_id, dob)
tuition(id, student_id, month, amount_due)
"""
```

## 5.5. RAG search

```
results = qdrant_client.search(
    collection_name="school_docs",
    query_vector=query_emb,
    limit=5
)
```

## 5.6. Agent Logic

```
if "học phí" in question:
    sql_data = query_db(...)
    rag_context = search_rag(...)
    final_answer = ask_llm(sql_data, rag_context)
```

---

# 6. Pipeline Fine-tune

## 6.1. Tạo dataset bằng Easy Dataset

Export dạng JSONL:

```
{"instruction": "...", "output": "..."}
```

## 6.2. Fine-tune bằng LLaMA Factory

```
llamafactory train \
  --model qwen-2.5-32b \
  --data dataset.jsonl \
  --output_dir ./ft-model \
  --training_type lora \
  --num_train_epochs 3
```

## 6.3. Deploy model đã fine-tuned

Upload lại vào `/opt/models` rồi chạy vLLM như bình thường.

---

# 7. Kết nối với Parent Portal / SIS

## 7.1. API gọi đến AI Backend

```
POST /api/ai/chat
{
  "user_id": "parent123",
  "question": "Học phí tháng này của con tôi là bao nhiêu?"
}
```

## 7.2. AI Backend gọi LLM và trả về kết quả

```
{
  "answer": "Số tiền học phí tháng này là 2.400.000đ. Hạn nộp: ngày 05 hàng tháng."
}
```

---

# 8. Checklist hoàn thành

- [ ] GPU Node chạy vLLM với model 70B
- [ ] Vector DB chạy Qdrant
- [ ] Ingest tài liệu vào RAG
- [ ] AI Backend kết nối LLM + SQL + RAG
- [ ] Pipeline fine-tune hoạt động
- [ ] Parent Portal gọi AI Agent OK

---

# 9. Next Steps

- Thêm RBAC để giới hạn phụ huynh xem đúng dữ liệu học sinh.
- Thêm logging + monitoring (Prometheus/Grafana).
- Thêm autoscaling backend.
- Thêm offline backup cho Qdrant + model.
