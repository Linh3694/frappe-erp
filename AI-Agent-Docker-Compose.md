# AI Agent Docker Compose Setup

Tài liệu này cung cấp cấu hình Docker Compose đầy đủ cho hệ thống AI Agent:

- LLM GPU Node (vLLM server)
- Qdrant Vector DB
- AI Backend (FastAPI + Agent)
- Embedding Service (tuỳ chọn)

> Lưu ý:
>
> - LLM Node chỉ chạy trên máy EC2 có GPU A100 40GB.
> - Các service khác chạy trên EC2 thường.

---

# 1. Cấu trúc thư mục

```
/ai-agent/
   docker-compose.yml
   backend/
      Dockerfile
      main.py
      requirements.txt
   models/
      llama-3.1-70b-q4_k_m/
   qdrant-data/
```

---

# 2. Docker Compose – Full System

```
version: "3.9"

services:

  ##############################
  # 1. LLM SERVER (GPU NODE)
  ##############################
  llm-server:
    image: vllm/vllm-openai:latest
    container_name: llm-server
    restart: always
    network_mode: host
    ipc: host
    environment:
      - VLLM_WORKER_MULTIPROCESS=true
    volumes:
      - ./models:/models
    command: >
      --model /models/llama-3.1-70b-q4_k_m
      --port 8000
      --max-model-len 8192
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

  ##############################
  # 2. VECTOR DB SERVER
  ##############################
  qdrant:
    image: qdrant/qdrant
    container_name: qdrant
    restart: always
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant-data:/qdrant/storage

  ##############################
  # 3. AI BACKEND (FastAPI)
  ##############################
  ai-backend:
    build: ./backend
    container_name: ai-backend
    restart: always
    depends_on:
      - qdrant
    environment:
      LLM_API_BASE: "http://llm-server:8000/v1"
      QDRANT_HOST: "qdrant"
      QDRANT_PORT: 6333
      DB_HOST: "mariadb"
      DB_USER: "sisuser"
      DB_PASSWORD: "password"
      DB_NAME: "sis"
    ports:
      - "9000:9000"

  ##############################
  # 4. (OPTIONAL) EMBEDDING SERVICE
  ##############################
  embeddings:
    image: ghcr.io/huggingface/text-embeddings-inference:latest
    container_name: embeddings
    restart: always
    ports:
      - "8080:80"
    environment:
      - MODEL_ID=BAAI/bge-large-en-v1.5
```

---

# 3. Dockerfile cho AI Backend

Tạo file: `/ai-agent/backend/Dockerfile`

```
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

---

# 4. requirements.txt

```
fastapi
uvicorn
openai
qdrant-client
pymysql
langchain
sentence-transformers
```

---

# 5. Backend bootstrap (main.py)

```
from fastapi import FastAPI
import openai

app = FastAPI()

@app.get("/")
def ping():
    return {"status": "ok"}

@app.post("/chat")
def chat(payload: dict):
    question = payload["question"]

    response = openai.ChatCompletion.create(
        model="llama-70b",
        messages=[{"role": "user", "content": question}]
    )

    return {"answer": response["choices"][0]["message"]["content"]}
```

---

# 6. Chạy toàn bộ hệ thống

## 6.1. Nếu trên GPU node:

Chỉ chạy service `llm-server`:

```
docker compose up -d llm-server
```

## 6.2. Nếu trên backend node:

Chạy:

```
docker compose up -d qdrant ai-backend embeddings
```

---

# 7. Kết nối hệ thống

Backend gọi LLM qua:

```
POST http://<gpu-node-ip>:8000/v1/chat/completions
```

Portal/Mobile gọi Backend qua:

```
POST http://<backend-ip>:9000/chat
```

---

# 8. Checklist triển khai

- [ ] GPU node chạy vLLM ổn định
- [ ] Model 70B được mount vào `/models`
- [ ] Backend kết nối tới LLM API OK
- [ ] Backend kết nối Qdrant OK
- [ ] Embedding service hoạt động
- [ ] Portal gọi backend OK

---

# 9. Next Steps

- Thêm HTTPS qua nginx reverse proxy
- Thêm load balancing backend
- Thêm monitoring (Grafana + Prometheus)
- Tối ưu batching vLLM
