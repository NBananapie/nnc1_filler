# nnc1_web/Dockerfile
FROM python:3.11-slim

# 1. 设置工作目录与环境变量
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 2. 安装系统依赖 (如有需要可扩展)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. 安装 Python 核心依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# 4. 复制前后端源码到容器中
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 5. 声明 Cloud Run 默认环境变量 PORT，并暴露它
ENV PORT=8080
EXPOSE 8080

# 6. 运行 FastAPI 服务 (动态绑定环境变量 PORT，支持 Cloud Run 自动分配端口)
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT}"]
