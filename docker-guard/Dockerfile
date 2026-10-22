FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.150.0 starlette==1.9.0 uvicorn==0.34.0
COPY guard.py .
USER 0:0
CMD ["uvicorn","guard:app","--host","0.0.0.0","--port","2375","--no-proxy-headers"]
