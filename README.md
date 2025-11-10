# langflow-infra

Contains all the boilerplate you need to create an AWS CloudFormation (CFN) infrastructure repository.

## Infrastructure Pattern

This repository was configured for: **vpc-rds-alb-fargate**

### Pattern 2: VPC/RDS/ALB/Fargate

This pattern provides a containerized application infrastructure using:
- VPC with public and private subnets
- RDS Aurora PostgreSQL (serverless)
- ECS Fargate for container orchestration
- Application Load Balancer (ALB) for traffic distribution
- NAT Gateway for private subnet internet access
- AWS WAF for application protection
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
  - S3 Bucket for Lambda source code
  - ECR Repository for Lambda container images

- **RDS Stack** (`aws/rds-stack.cfn.yaml`)
  - Aurora PostgreSQL Serverless v2 cluster
  - Multi-AZ deployment with 2 instances
  - Secrets Manager integration for credentials
  - Performance Insights (optional)
  - Enhanced monitoring
  - Automated backups

### Application Infrastructure
- **Platform Stack** (`aws/platform-stack.cfn.yaml`)
  - ECR repository for container images
  - Image lifecycle policies
  - Optional Lambda source S3 bucket (not used for Langflow)

- **Fargate Application Stack** (`aws/apps/fargate-stack.cfn.yaml`)
  - ECS Fargate cluster for containerized applications
  - Application Load Balancer with HTTP/HTTPS support
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
- Optional NAT Gateways for private subnet internet access
- RDS Subnet Group for database deployment

> **Important**: The stack name follows the pattern: `<ProjectPrefix>-<ProjectId-Prefix>-<StageName>-vpc-stack`
> This naming convention is required for cross-stack references.

```bash
export AWS_PROFILE={profile-name}
export PROJECT_PREFIX=infra
export PROJECT_ID={UUID} # e.g., 317523a7-9837-41a5-9757-f83c7987e1c7
export STAGE=dev # (prd|stg|dev)
export AWS_REGION=ap-northeast-1

# Deploy VPC without NAT Gateway (lower cost)
aws cloudformation deploy \
    --template-file ./aws/vpc-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        ClassBNetwork=10 \
        UseNATGateway=false \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}

# OR Deploy VPC with NAT Gateway (enables private subnet internet access)
aws cloudformation deploy \
    --template-file ./aws/vpc-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack \
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
- Aurora PostgreSQL cluster (Serverless v2 or Provisioned)
- DB instances for high availability
- Secrets Manager secret for credentials
- Customer-managed KMS encryption key
- Security group for database access

#### Option A: Serverless v2 (Variable Workloads)

```bash
export DB_NAME=myappdb
export VPC_STACK_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack

# Deploy RDS Serverless (Development)
aws cloudformation deploy \
    --template-file ./aws/rds-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        DeploymentMode=Serverless \
        DBName=${DB_NAME} \
        DBMasterUsername=postgres \
        MinCapacity=0.5 \
        MaxCapacity=1 \
        EnableDeletionProtection=false \
        EnablePerformanceInsights=false \
    --capabilities CAPABILITY_IAM \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}

# Deploy RDS Serverless (Production)
aws cloudformation deploy \
    --template-file ./aws/rds-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        DeploymentMode=Serverless \
        DBName=${DB_NAME} \
        DBMasterUsername=postgres \
        MinCapacity=1 \
        MaxCapacity=4 \
        EnableDeletionProtection=true \
        EnablePerformanceInsights=true \
    --capabilities CAPABILITY_IAM \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}
```

#### Option B: Provisioned (Steady Workloads)

```bash
export DB_NAME=myappdb
export VPC_STACK_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack

# Deploy RDS Provisioned (Development - Single Instance)
aws cloudformation deploy \
    --template-file ./aws/rds-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        DeploymentMode=Provisioned \
        DBName=${DB_NAME} \
        DBMasterUsername=postgres \
        DBInstanceClass=db.t4g.medium \
        NumberOfInstances=1 \
        EnableDeletionProtection=false \
        EnablePerformanceInsights=false \
    --capabilities CAPABILITY_IAM \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}

# Deploy RDS Provisioned (Production - Multi-AZ with 2 instances)
aws cloudformation deploy \
    --template-file ./aws/rds-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        DeploymentMode=Provisioned \
        DBName=${DB_NAME} \
        DBMasterUsername=postgres \
        DBInstanceClass=db.r6g.large \
        NumberOfInstances=2 \
        EnableDeletionProtection=true \
        EnablePerformanceInsights=true \
    --capabilities CAPABILITY_IAM \
    --tags \
        ProjectId=${PROJECT_ID} \
    --region ${AWS_REGION}
```

### 3. Deploy Fargate Application (Multi-Tenant Langflow)

The Fargate stack creates:
- ECS Fargate cluster for long-running application
- Application Load Balancer (ALB) for internet-facing access
- Auto-scaling based on CPU and memory
- CloudWatch Logs and Container Insights
- ECS Exec enabled for interactive container access

> **Important**: This deployment requires building and pushing a container image to ECR first.

#### Step 1: Deploy Platform Stack (ECR Repository)

The platform stack creates ECR repositories for your container images:

```bash
aws cloudformation deploy \
    --template-file ./aws/platform-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-platform-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        CreateFargateECR=true \
        CreateLambdaECR=false \
        CreateLambdaSourceBucket=false \
        ECRImageRetentionCount=10 \
    --capabilities CAPABILITY_IAM \
    --region ${AWS_REGION}
```

#### Step 2: Build and Push Container Image

Get the ECR repository URI and build/push your application image:

```bash
# Get ECR repository URI from platform stack
export ECR_URI=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-platform-stack \
    --query 'Stacks[0].Outputs[?OutputKey==`FargateECRRepositoryUri`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

echo "ECR URI: ${ECR_URI}"

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${ECR_URI}

# Build Docker image (adjust path to your Dockerfile location)
# For Langflow multi-tenant: cd to langflow repository root
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
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack \
    --query 'Stacks[0].Outputs[?OutputKey==`DBClusterEndpoint`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

# Get secret ARN
export SECRET_ARN=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack \
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
export VPC_STACK_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack
export PLATFORM_STACK_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-platform-stack
export RDS_STACK_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack

# Deploy Fargate stack
aws cloudformation deploy \
    --template-file ./aws/apps/fargate-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=$(echo $PROJECT_ID | cut -d'-' -f1) \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        PlatformStackName=${PLATFORM_STACK_NAME} \
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
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=$(echo $PROJECT_ID | cut -d'-' -f1) \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK_NAME} \
        PlatformStackName=${PLATFORM_STACK_NAME} \
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

#### Step 6: Run Database Migrations

After deploying the Fargate stack, run database migrations to initialize the database schema:

```bash
# Get ECS cluster and service names
export CLUSTER_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-cluster
export SERVICE_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-service
export CONTAINER_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-container

# Get running task ID
export TASK_ID=$(aws ecs list-tasks \
    --cluster ${CLUSTER_NAME} \
    --service-name ${SERVICE_NAME} \
    --region ${AWS_REGION} \
    --query 'taskArns[0]' \
    --output text | rev | cut -d'/' -f1 | rev)

echo "Task ID: ${TASK_ID}"

# Start interactive session
aws ecs execute-command \
    --cluster ${CLUSTER_NAME} \
    --task ${TASK_ID} \
    --container ${CONTAINER_NAME} \
    --command "/bin/bash" \
    --interactive \
    --region ${AWS_REGION}

# Inside the container, run migrations
cd /app
LANGFLOW_DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:5432/${DB_NAME}" \
    uv run alembic upgrade head
```

> **Note**: For multi-tenant deployments, migrations create tables in the `public` schema. Tenant-specific schemas are created on-demand using `lfhelper.py` (see GROUP(SCHEMA)/USER Setup section).

#### Step 7: Get ALB DNS Name and Test

```bash
# Get the ALB DNS name
export ALB_DNS=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-stack \
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

For multi-tenant Langflow deployments, use `lfhelper.py` to manage tenant schemas and users. This utility is included in the Langflow multi-tenant Docker image.

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

### Using lfhelper.py Locally

When using docker-compose for local development:

```bash
# Schema management
docker exec langflow-multi-tenant python /app/lfhelper.py schema-add --prefix <tenant-prefix>
docker exec langflow-multi-tenant python /app/lfhelper.py schema-list

# User management
docker exec langflow-multi-tenant python /app/lfhelper.py user-add --schema <schema-id> --username <username> [--password <password>]
docker exec langflow-multi-tenant python /app/lfhelper.py user-reset --schema <schema-id> --username <username> [--password <password>]
docker exec langflow-multi-tenant python /app/lfhelper.py user-list --schema <schema-id>
```

### Using lfhelper.py on AWS Fargate

For AWS deployments, use ECS exec to run lfhelper.py commands inside the Fargate container:

#### Step 1: Get ECS Task ID

```bash
# Set ECS resource names (should match your Fargate stack naming)
export CLUSTER_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-cluster
export SERVICE_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-service
export CONTAINER_NAME=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-container

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

#### Step 3: Run lfhelper.py Commands

Inside the ECS exec session:

```bash
# Create tenant schemas
python /app/lfhelper.py schema-add --prefix acmecorp
python /app/lfhelper.py schema-add --prefix widgetco

# List all schemas
python /app/lfhelper.py schema-list

# Add users (password auto-generated if not provided)
python /app/lfhelper.py user-add --schema acmecorp-a1b2c3 --username admin@acmecorp.com
python /app/lfhelper.py user-add --schema acmecorp-a1b2c3 --username user@acmecorp.com --password MySecurePassword123

# List users in a schema
python /app/lfhelper.py user-list --schema acmecorp-a1b2c3

# Reset user password
python /app/lfhelper.py user-reset --schema acmecorp-a1b2c3 --username admin@acmecorp.com

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

### lfhelper.py Command Reference

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
