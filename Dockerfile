FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY public ./public
ENV PORT=3000 DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 3000
CMD ["python", "server.py"]
