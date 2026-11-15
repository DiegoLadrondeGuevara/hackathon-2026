FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY analisis/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY analisis/*.py ./
USER nobody
EXPOSE 8080
CMD ["functions-framework", "--target=api", "--source=main.py", "--port=8080"]
