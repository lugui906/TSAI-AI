# web-ai-server 部署镜像（示例）
# 说明：aim CLI 需作为可执行文件提供（挂载或放入镜像），否则 /api 接口无法工作。
FROM python:3.12-slim

WORKDIR /app

COPY requirements.in .
# 生产环境建议用 pip-compile 生成的锁文件；此处直接安装高层依赖
RUN pip install --no-cache-dir flask rapidocr-onnxruntime && \
    pip install --no-cache-dir -r requirements.in

COPY server.py .
COPY templates/ templates/
COPY data/ data/

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
# 局域网部署：监听所有网卡
EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5001/', timeout=3)" || exit 1

CMD ["python", "server.py", "0.0.0.0", "5001"]
