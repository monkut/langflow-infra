# langflow-infra

CloudFormation infrastructure for multi-tenant Langflow deployment on AWS.

## Infrastructure Overview

This repository provides a production-ready containerized application infrastructure using:
- VPC with public and private subnets
- RDS Aurora PostgreSQL Serverless v2
- ECS Fargate for container orchestration
- Application Load Balancer (ALB) for traffic distribution
- NAT Gateway for private subnet internet access (optional)
## Prerequisites

- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- AWS Account with appropriate permissions
- AWS Profile configured locally

## Infrastructure Components

This repository provides CloudFormation templates for:

### Core Infrastructure
- **VPC Stack** (`aws/vpc-stack.cfn.yaml`)
  - VPC with public and private subnets across 2 availability zones
  - Optional NAT Gateway for private subnet internet access
  - Internet Gateway for public subnets
  - Network ACLs
  - RDS Subnet Group

- **RDS Stack** (`aws/rds-stack.cfn.yaml`)
  - Aurora PostgreSQL Serverless v2 cluster
  - Multi-AZ deployment with auto-scaling (0.5-4 ACU)
  - Secrets Manager integration for credentials
  - Enhanced monitoring
  - Automated backups

### Application Infrastructure
- **ECR Stack** (`aws/ecr-stack.cfn.yaml`)
  - ECR repository for Fargate container images
  - Image lifecycle policies

- **Fargate Application Stack** (`aws/apps/fargate-stack.cfn.yaml`)
  - ECS Fargate cluster for containerized applications
  - Application Load Balancer with HTTPS support (HTTP redirects to HTTPS)
  - S3 bucket for multi-tenant file storage
  - Auto-scaling based on CPU and memory
  - Container Insights and CloudWatch Logs
  - ECS Exec for interactive container access
  - VPC integration with RDS access

## Deployment Guide

### 1. Deploy VPC Stack

The VPC stack contains:
- VPC with configurable CIDR block
- Public and private subnets in 2 AZs
- Route tables and Network ACLs
- NAT Gateways for private subnet internet access
- RDS Subnet Group for database deployment

> **Important**: The stack name follows the pattern: `<ProjectPrefix>-<ProjectId-Prefix>-<StageName>-vpc-stack`
> This naming convention is required for cross-stack references.

```bash
export AWS_PROFILE={profile-name}
export PROJECT_PREFIX=mufglf
export PROJECT_ID=be1bbb25-e068-4e72-8392-a297feb9469c
export PROJECT_ID_PREFIX=$(echo $PROJECT_ID | cut -d'-' -f1)
export STAGE=dev # (prd|stg|dev)
export AWS_REGION=ap-northeast-1

# OR Deploy VPC with NAT Gateway (enables private subnet internet access)
# -- need for external access, and user access
aws cloudformation deploy \
    --template-file ./aws/vpc-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-vpc-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        ClassBNetwork=10 \
        UseNATGateway=true \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}
```

### 2. Deploy RDS Stack

The RDS stack creates:
- Aurora PostgreSQL Serverless v2 cluster
- Multi-AZ deployment with auto-scaling capacity (0.5-4 ACU)
- Secrets Manager secret for credentials
- Customer-managed KMS encryption key
- Security group for database access

```bash
export DB_NAME=langflow
export VPC_STACK_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-vpc-stack

# Development deployment (lower cost, auto-pause disabled)
aws cloudformation deploy \
    --template-file ./aws/rds-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-rds-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        DeploymentMode=Serverless \
        DBName=${DB_NAME} \
        DBMasterUsername=postgres \
        MinCapacity=0.5 \
        MaxCapacity=2 \
        AutoPause=false \
        EnableDeletionProtection=false \
        EnablePerformanceInsights=false \
    --capabilities CAPABILITY_IAM \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}


### 3. Deploy Fargate Application (Multi-Tenant Langflow)

The Fargate stack creates:
- ECS Fargate cluster for long-running application
- Application Load Balancer (ALB) with HTTPS support (HTTP redirects to HTTPS)
- S3 bucket for multi-tenant file storage (encrypted, versioned, with lifecycle policies)
- Auto-scaling based on CPU and memory
- CloudWatch Logs and Container Insights
- ECS Exec enabled for interactive container access

> **Important**: This deployment requires building and pushing a container image to ECR first.

#### Step 1: Deploy ECR Stack

The ECR stack creates an ECR repository for your Fargate container images:

```bash
aws cloudformation deploy \
    --template-file ./aws/ecr-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-ecr-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        CreateFargateECR=true \
        ECRImageRetentionCount=10 \
    --capabilities CAPABILITY_IAM \
    --region ${AWS_REGION}
```

#### Step 2: Build and Push Container Image

Get the ECR repository URI and build/push your application image:

```bash
# Get ECR repository URI from ECR stack
export ECR_URI=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-ecr-stack \
    --query 'Stacks[0].Outputs[?OutputKey==`FargateECRRepositoryUri`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

echo "ECR URI: ${ECR_URI}"

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${ECR_URI}

# Build Docker image using custom multi-tenant Dockerfile
# This Dockerfile is located in the langflow-kiconia repository at:
#   deploy/multi-tenant/Dockerfile
# It contains:
#   - Langflow application (from official build_and_push.Dockerfile)
#   - tenantmgr.py helper script for tenant schema management
#   - Production health checks and data directory setup
# Build from langflow repository root:
cd /path/to/langflow-kiconia
docker build -f deploy/multi-tenant/Dockerfile -t langflow-multi-tenant:latest .

# Tag and push image
docker tag langflow-multi-tenant:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest
```

#### Step 3: Get RDS Connection Details

Retrieve database credentials from Secrets Manager:

```bash
# Get RDS cluster endpoint
export DB_HOST=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-rds-stack \
    --query 'Stacks[0].Outputs[?OutputKey==`DBClusterEndpoint`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

# Get secret ARN
export SECRET_ARN=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-rds-stack \
    --query 'Stacks[0].Outputs[?OutputKey==`DBSecretArn`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

# Get credentials from Secrets Manager
aws secretsmanager get-secret-value \
    --secret-id ${SECRET_ARN} \
    --query 'SecretString' \
    --output text \
    --region ${AWS_REGION} | jq -r '.username, .password'

# Store values for deployment
export DB_USER=postgres  # From secret
export DB_PASSWORD=<password-from-secret>  # From secret
export DB_NAME=langflow  # Database name used in RDS stack
```

#### Step 4: Deploy Fargate Stack (Development - Single Task)

```bash
# Set stack names
export VPC_STACK_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-vpc-stack
export RDS_STACK_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-rds-stack

# Deploy Fargate stack
aws cloudformation deploy \
    --template-file ./aws/apps/fargate-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-fargate-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        RdsStackName=${RDS_STACK_NAME} \
        ContainerImage=${ECR_URI}:latest \
        ContainerPort=7860 \
        HealthCheckPath=/health \
        TaskCpu=2048 \
        TaskMemory=4096 \
        DesiredCount=1 \
        EnableAutoScaling=false \
        DBHost=${DB_HOST} \
        DBPort=5432 \
        DBName=${DB_NAME} \
        DBUser=${DB_USER} \
        DBPassword=${DB_PASSWORD} \
    --capabilities CAPABILITY_NAMED_IAM \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}
```

#### Step 5: Deploy Fargate Stack (Production - Auto-scaling with HTTPS)

> **Note**: You need an ACM certificate for HTTPS support. Create one in AWS Certificate Manager first.

```bash
# Export ACM certificate ARN
export CERTIFICATE_ARN=arn:aws:acm:${AWS_REGION}:${AWS_ACCOUNT_ID}:certificate/{certificate-id}

# Deploy with auto-scaling and HTTPS
aws cloudformation deploy \
    --template-file ./aws/apps/fargate-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-fargate-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        RdsStackName=${RDS_STACK_NAME} \
        ContainerImage=${ECR_URI}:latest \
        ContainerPort=7860 \
        HealthCheckPath=/health \
        TaskCpu=2048 \
        TaskMemory=4096 \
        DesiredCount=2 \
        CertificateArn=${CERTIFICATE_ARN} \
        EnableAutoScaling=true \
        MinTaskCount=2 \
        MaxTaskCount=10 \
        DBHost=${DB_HOST} \
        DBPort=5432 \
        DBName=${DB_NAME} \
        DBUser=${DB_USER} \
        DBPassword=${DB_PASSWORD} \
    --capabilities CAPABILITY_NAMED_IAM \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}
```

#### Step 6: Initialize Multi-Tenant Database

**Understanding Multi-Tenant Database Architecture:**

This deployment uses PostgreSQL schema-based isolation for multi-tenancy:
- **`public` schema**: Template only - created by migrations, never used by the application at runtime
- **Tenant schemas** (e.g., `testcorp-abc123`): Working databases - used by the application to store actual tenant data

**Why Two Steps?**
1. **Migrations** create the table structures in `public` schema (the template)
2. **`tenantmgr.py`** copies these structures to new tenant schemas (the working databases)

This approach ensures:
- Consistent schema structure across all tenants
- Complete data isolation between tenants
- Efficient schema creation (copy structure, not data)

**Step 6a: Connect to ECS Container**

```bash
# Get ECS cluster and service names
export CLUSTER_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-app-cluster
export SERVICE_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-app-service
export CONTAINER_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-app-container

# Get running task ID
export TASK_ID=$(aws ecs list-tasks \
    --cluster ${CLUSTER_NAME} \
    --service-name ${SERVICE_NAME} \
    --region ${AWS_REGION} \
    --query 'taskArns[0]' \
    --output text | rev | cut -d'/' -f1 | rev)

echo "Task ID: ${TASK_ID}"

# Start interactive session (requires AWS Session Manager plugin)
aws ecs execute-command \
    --cluster ${CLUSTER_NAME} \
    --task ${TASK_ID} \
    --container ${CONTAINER_NAME} \
    --command "/bin/bash" \
    --interactive \
    --region ${AWS_REGION}
```

**Step 6b: Run Migrations (Inside Container)**

This creates the template table structures in the `public` schema:

```bash
# enter the env
cd /app
source .venv/bin/activate

# Change to the directory containing alembic.ini
cd /app/src/backend/base/langflow

# Run migrations using alembic from the venv
# Note: Use direct alembic command, not 'uv run alembic'
alembic upgrade head
```

> **Note**: The `alembic` command uses the Python and libraries from `/app/.venv` which is already in the container's PATH.

**Step 6c: Create First Tenant Schema (Inside Container)**

This copies the template from `public` to a new tenant-specific schema:

```bash
# Activate the virtual environment first
source /app/.venv/bin/activate

# OR use the venv Python directly without activation
# /app/.venv/bin/python /app/tenantmgr.py schema-add --prefix testcorp

# Create tenant schema (copies table structure from public)
python /app/tenantmgr.py `schema-add --prefix` testcorp

# Output example:
#    Creating new tenant schema: testcorp -> testcorp-a1b2c3
#    ✓ Created PostgreSQL schema: testcorp-a1b2c3
#    ✓ Initialized schema with 9 tables
# ✅ Successfully created tenant schema:
#    Prefix: testcorp
#    Schema ID: testcorp-a1b2c3

# Create admin user for the tenant (password auto-generated if not provided)
python /app/tenantmgr.py user-add --schema testcorp-a1b2c3 --username admin@testcorp.com

# Output example:
# ✅ Successfully created user:
#    Schema: testcorp-a1b2c3
#    Username: admin@testcorp.com
#    Password: Xy9kL2mP3qR4sT5v (auto-generated)
#    User ID: 1

# Exit the container
exit
```

> **Important**:
> - Activate the venv with `source /app/.venv/bin/activate` before running `tenantmgr.py`, or use the full path `/app/.venv/bin/python`
> - Save the auto-generated password securely. It cannot be retrieved later, only reset using `user-reset`.
> - The `tenantmgr.py` script uses synchronous database operations and requires `psycopg` (installed via the `postgresql` extra)
> - The `public` schema is never accessed by the application at runtime. All application data is stored in tenant-specific schemas like `testcorp-a1b2c3`.

#### Step 7: Get ALB DNS Name and Test

```bash
# Get the ALB DNS name
export ALB_DNS=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-fargate-stack \
    --query 'Stacks[0].Outputs[?OutputKey==`ApplicationLoadBalancerDNSName`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

echo "ALB DNS: ${ALB_DNS}"

# Test health endpoint
curl http://${ALB_DNS}/health
```

Connect to your application using:
- HTTP: `http://{ALB-DNS-NAME}/`
- HTTPS: `https://{ALB-DNS-NAME}/` (if certificate configured)
- Multi-tenant access: `http://{ALB-DNS-NAME}/tenant/{prefix}/`

## Stack Naming Convention

All stacks follow this naming pattern for cross-stack references:
```
<ProjectPrefix>-<ProjectId-Prefix>-<StageName>-<stack-type>-stack
```

Example:
```
myapp-317523a7-dev-vpc-stack
myapp-317523a7-dev-rds-stack
```

## GROUP(SCHEMA)/USER Setup

For multi-tenant Langflow deployments, use `tenantmgr.py` to manage tenant schemas and users. This utility is included in the Langflow multi-tenant Docker image.

### Prerequisites

**AWS Session Manager Plugin** (required for ECS exec):

```bash
# macOS (Homebrew)
brew install --cask session-manager-plugin

# Linux (64-bit)
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb

# Verify installation
session-manager-plugin --version
```

For other platforms, see: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

### Multi-Tenant Architecture

The multi-tenant setup uses PostgreSQL schema-based isolation:
- Each tenant gets a dedicated PostgreSQL schema (format: `{prefix}-{hash}`)
- Users are scoped to their tenant schema
- Complete data isolation between tenants
- Access via tenant-specific URLs: `/tenant/{prefix}/`

### Using tenantmgr.py Locally

When using docker-compose for local development:

```bash
# Schema management
docker exec langflow-multi-tenant python /app/tenantmgr.py schema-add --prefix <tenant-prefix>
docker exec langflow-multi-tenant python /app/tenantmgr.py schema-list

# User management
docker exec langflow-multi-tenant python /app/tenantmgr.py user-add --schema <schema-id> --username <username> [--password <password>]
docker exec langflow-multi-tenant python /app/tenantmgr.py user-reset --schema <schema-id> --username <username> [--password <password>]
docker exec langflow-multi-tenant python /app/tenantmgr.py user-list --schema <schema-id>
```

### Using tenantmgr.py on AWS Fargate

For AWS deployments, use ECS exec to run tenantmgr.py commands inside the Fargate container:

#### Step 1: Get ECS Task ID

```bash
# Set ECS resource names (should match your Fargate stack naming)
export CLUSTER_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-app-cluster
export SERVICE_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-app-service
export CONTAINER_NAME=${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE}-app-container

# Get running task ID
export TASK_ID=$(aws ecs list-tasks \
    --cluster ${CLUSTER_NAME} \
    --service-name ${SERVICE_NAME} \
    --region ${AWS_REGION} \
    --query 'taskArns[0]' \
    --output text | rev | cut -d'/' -f1 | rev)

echo "Task ID: ${TASK_ID}"
```

#### Step 2: Start Interactive Session

```bash
# Start interactive ECS exec session (requires AWS Session Manager plugin)
aws ecs execute-command \
    --cluster ${CLUSTER_NAME} \
    --task ${TASK_ID} \
    --container ${CONTAINER_NAME} \
    --command "/bin/bash" \
    --interactive \
    --region ${AWS_REGION}
```

#### Step 3: Run tenantmgr.py Commands

Inside the ECS exec session:

```bash
# Create tenant schemas
python /app/tenantmgr.py schema-add --prefix acmecorp
python /app/tenantmgr.py schema-add --prefix widgetco

# List all schemas
python /app/tenantmgr.py schema-list

# Add users (password auto-generated if not provided)
python /app/tenantmgr.py user-add --schema acmecorp-a1b2c3 --username admin@acmecorp.com
python /app/tenantmgr.py user-add --schema acmecorp-a1b2c3 --username user@acmecorp.com --password MySecurePassword123

# List users in a schema
python /app/tenantmgr.py user-list --schema acmecorp-a1b2c3

# Reset user password
python /app/tenantmgr.py user-reset --schema acmecorp-a1b2c3 --username admin@acmecorp.com

# Exit the session
exit
```

### Tenant Access URLs

After creating schemas and users, tenants can access their isolated environment using:

**Local Development:**
```
http://localhost/tenant/{prefix}/
```

**AWS Deployment:**
```
http://{ALB-DNS-NAME}/tenant/{prefix}/
```

Example:
- Schema prefix: `acmecorp`
- Access URL: `http://langflow-alb-123456.ap-northeast-1.elb.amazonaws.com/tenant/acmecorp/`
- Username: `admin@acmecorp.com`
- Password: `<auto-generated or specified>`

### tenantmgr.py Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| `schema-add --prefix <prefix>` | Create new tenant schema | `schema-add --prefix acmecorp` |
| `schema-list` | List all tenant schemas | `schema-list` |
| `user-add --schema <id> --username <user> [--password <pwd>]` | Add user to schema | `user-add --schema acmecorp-a1b2c3 --username admin@acmecorp.com` |
| `user-reset --schema <id> --username <user> [--password <pwd>]` | Reset user password | `user-reset --schema acmecorp-a1b2c3 --username admin@acmecorp.com` |
| `user-list --schema <id>` | List users in schema | `user-list --schema acmecorp-a1b2c3` |

**Notes:**
- Schema ID format: `{prefix}-{6-char-hash}` (e.g., `acmecorp-a1b2c3`)
- Passwords are auto-generated (16 characters) if not provided
- Auto-generated passwords are displayed only once during user creation
- Schema prefixes must be 1-50 characters, alphanumeric with underscores/hyphens

## Cost Optimization

### Development Environment
- Use `UseNATGateway=false` to avoid NAT Gateway costs
- Use smaller RDS capacity: `MinCapacity=0.5, MaxCapacity=1`
- Disable Performance Insights

### Production Environment
- Enable NAT Gateway for security
- Use appropriate RDS capacity based on load
- Enable Performance Insights for monitoring
- Enable deletion protection
