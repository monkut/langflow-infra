#!/usr/bin/env python3
"""
Dockerfile Generator for Django Applications.

Generates Dockerfiles for Django applications targeting AWS Fargate deployment.
Supports both synchronous (Gunicorn) and asynchronous (Daphne) Django applications.
"""

import argparse
import os
import sys
from pathlib import Path


# Dockerfile templates
DJANGO_ASYNC_TEMPLATE = '''# Production Dockerfile for Django/Daphne on AWS Fargate
# Async Django application with Daphne ASGI server

FROM python:3.13-slim

# Build arguments (customize these in .env files)
ARG DJANGO_SETTINGS_MODULE={django_settings_module}
ARG APP_DIR={app_dir}

# Set environment variables
ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE

# Install system dependencies (runtime only - using binary wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \\
    libpq5 \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user with UID > 10000 for security
RUN groupadd -g 10001 appuser && \\
    useradd -r -u 10001 -g appuser appuser

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv (as root, before user switch)
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p $APP_DIR/staticfiles $APP_DIR/static /app/.cache/uv && \\
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set UV cache to writable location
ENV UV_CACHE_DIR=/app/.cache/uv

# Collect static files
WORKDIR /app/$APP_DIR
RUN uv run python manage.py collectstatic --noinput --clear

# Expose port
EXPOSE 8000

# Health check for AWS Fargate ALB
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \\
    CMD curl -f http://localhost:8000/health/ || curl -f http://localhost:8000/admin/login/ || exit 1

# Set entrypoint (optional - customize if you have an entrypoint.sh)
# ENTRYPOINT ["/app/entrypoint.sh"]

# Run Daphne ASGI server
CMD ["uv", "run", "daphne", "-b", "0.0.0.0", "-p", "8000", "-v", "2", "--access-log", "-", "{asgi_module}"]
'''

DJANGO_SYNC_TEMPLATE = '''# Production Dockerfile for Django/Gunicorn on AWS Fargate
# Synchronous Django application with Gunicorn WSGI server

FROM python:3.13-slim

# Build arguments (customize these in .env files)
ARG DJANGO_SETTINGS_MODULE={django_settings_module}
ARG APP_DIR={app_dir}

# Set environment variables
ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE

# Install system dependencies (runtime only - using binary wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \\
    libpq5 \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user with UID > 10000 for security
RUN groupadd -g 10001 appuser && \\
    useradd -r -u 10001 -g appuser appuser

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv (as root, before user switch)
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p $APP_DIR/staticfiles $APP_DIR/static /app/.cache/uv && \\
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set UV cache to writable location
ENV UV_CACHE_DIR=/app/.cache/uv

# Collect static files
WORKDIR /app/$APP_DIR
RUN uv run python manage.py collectstatic --noinput --clear

# Expose port
EXPOSE 8000

# Health check for AWS Fargate ALB
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \\
    CMD curl -f http://localhost:8000/health/ || curl -f http://localhost:8000/admin/login/ || exit 1

# Set entrypoint (optional - customize if you have an entrypoint.sh)
# ENTRYPOINT ["/app/entrypoint.sh"]

# Run Gunicorn WSGI server
CMD ["uv", "run", "gunicorn", "{wsgi_module}", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
'''


def load_env_file(env_file: Path) -> dict[str, str]:
    """Load environment variables from .env file."""
    env_vars = {}
    if not env_file.exists():
        return env_vars

    with env_file.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")

    return env_vars


def generate_dockerfile(template_type: str, output_file: Path, env_file: Path | None = None) -> None:
    """Generate Dockerfile from template."""
    # Load environment variables
    env_vars = load_env_file(env_file) if env_file else {}

    # Get template variables with defaults
    django_settings_module = env_vars.get('DJANGO_SETTINGS_MODULE', 'myapp.settings')
    app_dir = env_vars.get('APP_DIR', 'myapp')

    # Infer module names from settings module
    project_name = django_settings_module.split('.')[0]
    asgi_module = f"{project_name}.asgi:application"
    wsgi_module = f"{project_name}.wsgi:application"

    # Select template
    if template_type == 'django-async':
        template = DJANGO_ASYNC_TEMPLATE
        variables = {
            'django_settings_module': django_settings_module,
            'app_dir': app_dir,
            'asgi_module': asgi_module,
        }
    elif template_type == 'django-sync':
        template = DJANGO_SYNC_TEMPLATE
        variables = {
            'django_settings_module': django_settings_module,
            'app_dir': app_dir,
            'wsgi_module': wsgi_module,
        }
    else:
        print(f"Error: Unknown template type '{template_type}'", file=sys.stderr)
        print("Available types: django-async, django-sync", file=sys.stderr)
        sys.exit(1)

    # Generate Dockerfile content
    dockerfile_content = template.format(**variables)

    # Write to file
    output_file.write_text(dockerfile_content)
    print(f"✅ Generated {template_type} Dockerfile: {output_file}")
    print(f"\nUsing configuration:")
    for key, value in variables.items():
        print(f"  {key}: {value}")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate Dockerfile for Django applications targeting AWS Fargate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate async Django Dockerfile (default)
  uvx --from langflow-infra-tools generate-dockerfile

  # Generate sync Django Dockerfile
  uvx --from langflow-infra-tools generate-dockerfile --type django-sync

  # Use environment file
  uvx --from langflow-infra-tools generate-dockerfile --env .env.dev

  # Custom output path
  uvx --from langflow-infra-tools generate-dockerfile --output custom/Dockerfile
        """
    )

    parser.add_argument(
        '--type',
        '-t',
        choices=['django-async', 'django-sync'],
        default='django-async',
        help='Dockerfile template type (default: django-async)',
    )

    parser.add_argument(
        '--env',
        '-e',
        type=Path,
        help='Path to .env file for configuration (optional)',
    )

    parser.add_argument(
        '--output',
        '-o',
        type=Path,
        default=Path('Dockerfile'),
        help='Output file path (default: ./Dockerfile)',
    )

    args = parser.parse_args()

    # Generate Dockerfile
    generate_dockerfile(
        template_type=args.type,
        output_file=args.output,
        env_file=args.env,
    )


if __name__ == '__main__':
    main()
