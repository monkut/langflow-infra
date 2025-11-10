# Application Deployment Guide

This guide explains how to deploy your Django application to the AWS Fargate infrastructure created by this project.

## Prerequisites

### AWS Session Manager Plugin

To use ECS Exec for running commands in containers (migrations, shell access, etc.), you must install the AWS Session Manager plugin on your local machine.

**Installation:**

```bash
# macOS (Homebrew)
brew install --cask session-manager-plugin

# Linux (Ubuntu/Debian)
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb

# Verify installation
session-manager-plugin --version
```

For other platforms, see [AWS Session Manager Plugin Installation](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)

**Note:** ECS Exec is enabled by default in the Fargate stack and includes:
- `EnableExecuteCommand: true` on the ECS service
- SSM permissions in the task role
- `InitProcessEnabled: true` for Fargate compatibility

## Overview

The deployment workflow separates **infrastructure** (this repo) from **application** code (your Django app repo):

1. **Infrastructure Repo** (this repo): Manages AWS resources (VPC, RDS, ECR, Fargate, ALB)
2. **Application Repo** (your Django app): Contains application code and deployment tasks

## Initial Infrastructure Deployment

### 1. Deploy Infrastructure Stacks

```bash
# Load environment variables
source .env.dev  # or .env.stg, .env.prd

# Deploy in order
aws-vault exec <profile> -- aws cloudformation deploy \\
  --template-file ./aws/vpc-stack.cfn.yaml \\
  --stack-name langflow-${PROJECT_ID_PREFIX}-${STAGE_NAME}-vpc-stack \\
  ...

aws-vault exec <profile> -- aws cloudformation deploy \\
  --template-file ./aws/platform-stack.cfn.yaml \\
  --stack-name langflow-${PROJECT_ID_PREFIX}-${STAGE_NAME}-platform-stack \\
  ...

aws-vault exec <profile> -- aws cloudformation deploy \\
  --template-file ./aws/rds-stack.cfn.yaml \\
  --stack-name langflow-${PROJECT_ID_PREFIX}-${STAGE_NAME}-rds-stack \\
  ...
```

### 2. Deploy Placeholder App

The infrastructure requires an initial Docker image. Deploy the included placeholder app:

```bash
# Build and deploy placeholder
cd dummy-app
docker build -t placeholder-app:latest .

# Get ECR URI from stack outputs
ECR_URI=$(aws cloudformation describe-stacks \\
  --stack-name langflow-*-platform-stack \\
  --query 'Stacks[0].Outputs[?OutputKey==`FargateECRRepositoryUri`].OutputValue' \\
  --output text)

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \\
  docker login --username AWS --password-stdin $ECR_URI

# Tag and push
docker tag placeholder-app:latest $ECR_URI:placeholder
docker push $ECR_URI:placeholder
```

### 3. Deploy Fargate Stack

```bash
aws-vault exec <profile> -- aws cloudformation deploy \\
  --template-file ./aws/apps/fargate-stack.cfn.yaml \\
  --stack-name langflow-${PROJECT_ID_PREFIX}-${STAGE_NAME}-wbskt-stack \\
  --parameter-overrides \\
    ContainerImage=$ECR_URI:placeholder \\
  ...
```

---

## Application Repository Setup

### 1. Generate Dockerfile

From your application repository, generate a Dockerfile using the infrastructure tools:

```bash
# For async Django (Daphne - default)
uvx --from langflow-infra-tools generate-dockerfile

# For sync Django (Gunicorn)
uvx --from langflow-infra-tools generate-dockerfile --type django-sync

# With environment file
uvx --from langflow-infra-tools generate-dockerfile --env .env.dev
```

The generator expects these environment variables (or will use defaults):
- `DJANGO_SETTINGS_MODULE` (default: `myapp.settings`)
- `APP_DIR` (default: `myapp`)

### 2. Add Deployment Tasks to `pyproject.toml`

Add these tasks to your application's `pyproject.toml`:

```toml
[tool.poe.tasks]

[tool.poe.tasks.build]
help = "Build Docker image and push to ECR"
shell = """
# Load environment
source .env.${STAGE_NAME:-dev}

# Get ECR URI
ECR_URI=$(aws cloudformation describe-stacks \\
  --stack-name ${PROJECT_PREFIX}-*-${STAGE_NAME}-platform-stack \\
  --region ${AWS_REGION} \\
  --query 'Stacks[0].Outputs[?OutputKey==`FargateECRRepositoryUri`].OutputValue' \\
  --output text)

# Build image
IMAGE_TAG=$(git rev-parse --short HEAD)
docker build -t ${PROJECT_PREFIX}-app:${IMAGE_TAG} .

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \\
  docker login --username AWS --password-stdin $ECR_URI

# Tag and push
docker tag ${PROJECT_PREFIX}-app:${IMAGE_TAG} $ECR_URI:${IMAGE_TAG}
docker tag ${PROJECT_PREFIX}-app:${IMAGE_TAG} $ECR_URI:latest
docker push $ECR_URI:${IMAGE_TAG}
docker push $ECR_URI:latest

echo "✅ Image pushed: $ECR_URI:${IMAGE_TAG}"
"""

[tool.poe.tasks.deploy]
help = "Deploy application to Fargate (update service with new image)"
shell = """
# Load environment
source .env.${STAGE_NAME:-dev}

# Get cluster and service names
CLUSTER_NAME="${PROJECT_PREFIX}-*-${STAGE_NAME}-wbskt-cluster"
SERVICE_NAME="${PROJECT_PREFIX}-*-${STAGE_NAME}-wbskt-service"

# Force new deployment
aws ecs update-service \\
  --cluster $CLUSTER_NAME \\
  --service $SERVICE_NAME \\
  --force-new-deployment \\
  --region ${AWS_REGION}

echo "✅ Deployment initiated. Waiting for service to stabilize..."

# Wait for service to be stable
aws ecs wait services-stable \\
  --cluster $CLUSTER_NAME \\
  --services $SERVICE_NAME \\
  --region ${AWS_REGION}

echo "✅ Service deployed successfully"
"""

[tool.poe.tasks.migrate]
help = "Run Django migrations on Fargate"
shell = """
# Load environment
source .env.${STAGE_NAME:-dev}

# Get cluster and service
CLUSTER_NAME="${PROJECT_PREFIX}-*-${STAGE_NAME}-wbskt-cluster"
SERVICE_NAME="${PROJECT_PREFIX}-*-${STAGE_NAME}-wbskt-service"

# Get running task ARN
TASK_ARN=$(aws ecs list-tasks \\
  --cluster $CLUSTER_NAME \\
  --service-name $SERVICE_NAME \\
  --region ${AWS_REGION} \\
  --query 'taskArns[0]' \\
  --output text)

if [ -z "$TASK_ARN" ] || [ "$TASK_ARN" == "None" ]; then
  echo "❌ No running tasks found"
  exit 1
fi

# Run migrations
echo "Running migrations on task: $TASK_ARN"
aws ecs execute-command \\
  --cluster $CLUSTER_NAME \\
  --task $TASK_ARN \\
  --container ${PROJECT_PREFIX}-*-${STAGE_NAME}-wbskt-container \\
  --command "uv run python manage.py migrate" \\
  --interactive \\
  --region ${AWS_REGION}

echo "✅ Migrations completed"
"""

[tool.poe.tasks.build-deploy]
help = "Build and deploy application"
sequence = ["build", "deploy"]

[tool.poe.tasks.build-deploy-migrate]
help = "Build, deploy, and run migrations"
sequence = ["build", "deploy", "migrate"]
```

### 3. Create Environment File

Create `.env.dev` (and `.env.stg`, `.env.prd`) in your application repo:

```bash
# AWS Configuration
AWS_REGION=ap-northeast-1
AWS_ACCOUNT_ID=123456789012

# Project Configuration
PROJECT_PREFIX=langflow
STAGE_NAME=dev

# Django Configuration
DJANGO_SETTINGS_MODULE=myapp.settings
APP_DIR=myapp

# Database (set via Secrets Manager in Fargate - not needed for deployment)
# DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
```

---

## Deployment Workflow

### First-Time Deployment

```bash
# 1. Generate Dockerfile
uvx --from langflow-infra-tools generate-dockerfile --env .env.dev

# 2. Build and push image
uv run poe build

# 3. Deploy to Fargate
uv run poe deploy

# 4. Run migrations
uv run poe migrate
```

### Subsequent Deployments

```bash
# Build, deploy, and migrate in one command
uv run poe build-deploy-migrate
```

---

## Environment Variables Injected by Fargate

The following environment variables are automatically injected into your containers by the Fargate stack:

### Database Credentials (from Secrets Manager)
- `DB_HOST` - RDS endpoint
- `DB_PORT` - RDS port (5432)
- `DB_NAME` - Database name
- `DB_USER` - Database username
- `DB_PASS` - Database password

### Infrastructure Metadata
- `AWS_REGION` - AWS region
- `AWS_ACCOUNT_ID` - AWS account ID
- `PROJECT_PREFIX` - Project prefix
- `PROJECT_ID` - Project ID
- `STAGE_NAME` - Stage name (dev/stg/prd)
- `CONTAINER_PORT` - Container port (8000)

---

## Troubleshooting

### Check Container Logs

```bash
# Get log group name
LOG_GROUP="/ecs/langflow-${PROJECT_ID_PREFIX}-${STAGE_NAME}-wbskt"

# Tail logs
aws logs tail $LOG_GROUP --follow --region ${AWS_REGION}
```

### Check ECS Service Status

```bash
aws ecs describe-services \\
  --cluster langflow-*-${STAGE_NAME}-wbskt-cluster \\
  --services langflow-*-${STAGE_NAME}-wbskt-service \\
  --region ${AWS_REGION}
```

### Connect to Running Container

```bash
# Get task ARN
TASK_ARN=$(aws ecs list-tasks \\
  --cluster langflow-*-${STAGE_NAME}-wbskt-cluster \\
  --service-name langflow-*-${STAGE_NAME}-wbskt-service \\
  --region ${AWS_REGION} \\
  --query 'taskArns[0]' --output text)

# Execute command
aws ecs execute-command \\
  --cluster langflow-*-${STAGE_NAME}-wbskt-cluster \\
  --task $TASK_ARN \\
  --container langflow-*-${STAGE_NAME}-wbskt-container \\
  --command "/bin/bash" \\
  --interactive \\
  --region ${AWS_REGION}
```

---

## Advanced Topics

### Custom Entrypoint Script

If you need database initialization or other startup tasks, create `entrypoint.sh` in your app repo:

```bash
#!/bin/bash
set -e

echo "Starting application..."

# Wait for database
python -c "import django; django.setup(); from django.db import connection; connection.ensure_connection()"

# Run migrations (optional - or use `poe migrate`)
# python manage.py migrate --noinput

echo "Application ready"
exec "$@"
```

Uncomment the `ENTRYPOINT` line in your generated Dockerfile.

### Multi-Stage Builds

For smaller images, modify the generated Dockerfile to use multi-stage builds.

### Private Dependencies

If you have private Python packages, use build secrets:

```dockerfile
RUN --mount=type=secret,id=github_token \\
    export GITHUB_TOKEN=$(cat /run/secrets/github_token) && \\
    uv sync --frozen --no-dev
```

---

## Summary

✅ **Infrastructure Repo**: Deploy CloudFormation stacks + placeholder app
✅ **Application Repo**: Generate Dockerfile, add poe tasks, deploy
✅ **Workflow**: `build` → `deploy` → `migrate`
✅ **Updates**: `uv run poe build-deploy-migrate`
