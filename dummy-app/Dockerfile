# Minimal placeholder Dockerfile for AWS Fargate initial deployment
# Uses only Python standard library - no external dependencies

FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Copy application
COPY app.py .

# Expose port
EXPOSE 8000

# Health check for AWS Fargate ALB
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')" || exit 1

# Run the application
CMD ["python", "app.py"]
