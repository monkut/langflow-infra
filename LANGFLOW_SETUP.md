# Langflow Multi-Tenant Infrastructure Setup

**Project:** langflow-infra
**Pattern:** vpc-rds-alb-fargate
**Created:** November 9, 2025
**Status:** ✅ Infrastructure Project Created

---

## Overview

This infrastructure project provides AWS CloudFormation templates for deploying Langflow with multi-tenant support using:
- **VPC** with public and private subnets
- **RDS Aurora PostgreSQL Serverless v2** for tenant schema isolation
- **ECS Fargate** for containerized Langflow application
- **Application Load Balancer** for path-based tenant routing
- **AWS WAF** for application protection
- **NAT Gateway** for private subnet internet access

---

## Project Structure

```
langflow-infra/
├── aws/
│   ├── vpc-stack.cfn.yaml           # VPC, subnets, NAT Gateway
│   ├── rds-stack.cfn.yaml           # Aurora Serverless PostgreSQL
│   ├── platform-stack.cfn.yaml      # ALB, ECR, S3, WAF
│   └── apps/
│       └── fargate-stack.cfn.yaml   # ECS Fargate service
├── dummy-app/                       # Example application (replace with Langflow)
├── infra_tools/                     # Deployment utilities
├── README.md                        # Full deployment guide
├── APPDEPLOYMENT.md                 # Application-specific deployment
└── pyproject.toml                   # Python dependencies
```

---

## Configuration for Langflow

### Container Settings

The Fargate stack needs to be configured for Langflow:

```yaml
# In aws/apps/fargate-stack.cfn.yaml
Parameters:
  ContainerImage: langflow-multi-tenant:latest  # Built from deploy/multi-tenant/Dockerfile
  ContainerPort: 7860                            # Langflow default port
  HealthCheckPath: /health                       # Langflow health endpoint

  # Resource allocation
  TaskCpu: '2048'      # 2 vCPU recommended for Langflow
  TaskMemory: '4096'   # 4 GB RAM recommended

  # Scaling
  DesiredCount: 2      # Start with 2 tasks for HA
  EnableAutoScaling: 'true'
  MinTaskCount: 2
  MaxTaskCount: 10
```

### Environment Variables for Container

The following environment variables will be passed to the Langflow container:

```yaml
# Database connection (from RDS stack)
LANGFLOW_DATABASE_URL: !Sub "postgresql://{{resolve:secretsmanager:${DBSecret}:SecretString:username}}:{{resolve:secretsmanager:${DBSecret}:SecretString:password}}@${DBHost}:${DBPort}/${DBName}"

# Authentication
LANGFLOW_AUTO_LOGIN: false
LANGFLOW_SUPERUSER: admin
LANGFLOW_SUPERUSER_PASSWORD: {{from-secrets-manager}}

# Performance
LANGFLOW_WORKERS: 4
LANGFLOW_POOL_SIZE: 20
LANGFLOW_MAX_OVERFLOW: 30

# CORS (configure for your domain)
LANGFLOW_CORS_ORIGINS: https://your-domain.com
LANGFLOW_CORS_ALLOW_CREDENTIALS: true

# Logging
LANGFLOW_LOG_LEVEL: info
```

---

## Deployment Steps

### Prerequisites

```bash
# Set AWS credentials
export AWS_PROFILE=your-profile-name
export AWS_REGION=ap-northeast-1

# Set project variables
export PROJECT_PREFIX=langflow
export PROJECT_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')  # Generate UUID
export STAGE=dev  # or stg, prd
```

### Step 1: Deploy VPC Stack

```bash
aws cloudformation deploy \
    --template-file ./aws/vpc-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        ClassBNetwork=10 \
        UseNATGateway=true \
    --capabilities CAPABILITY_IAM \
    --region ${AWS_REGION}
```

**Expected Output:**
- VPC with CIDR 10.10.0.0/16
- Public subnets in 2 AZs
- Private subnets in 2 AZs
- NAT Gateway (for RDS access from Fargate)
- ECR repository for Langflow images
- S3 bucket for artifacts

---

### Step 2: Deploy RDS Aurora Serverless Stack

```bash
aws cloudformation deploy \
    --template-file ./aws/rds-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack \
        DBName=langflow \
        MinCapacity=0.5 \
        MaxCapacity=2 \
        AutoPause=false \
    --capabilities CAPABILITY_IAM \
    --region ${AWS_REGION}
```

**Expected Output:**
- Aurora PostgreSQL Serverless v2 cluster
- Multi-AZ with auto-scaling (0.5-2 ACUs)
- Secrets Manager secret for credentials
- Security groups for database access
- Performance Insights enabled

**Configuration Notes:**
- `AutoPause=false` - Keep database available for multi-tenant
- `MinCapacity=0.5` - Start small, scale based on load
- `MaxCapacity=2` - Adjust based on expected tenant count

---

### Step 3: Deploy Platform Stack (ALB, WAF)

```bash
aws cloudformation deploy \
    --template-file ./aws/platform-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-platform-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack \
        DomainName=langflow.your-domain.com \
        Route53HostedZoneId=Z0123456789ABC \
        EnableWAF=true \
    --capabilities CAPABILITY_IAM \
    --region ${AWS_REGION}
```

**Expected Output:**
- Application Load Balancer (ALB)
- ACM Certificate (auto-validated via Route53)
- Route53 DNS record
- AWS WAF Web ACL
- CloudWatch alarms

**Configuration Notes:**
- `DomainName` - Your Langflow domain
- `Route53HostedZoneId` - Your Route53 hosted zone
- `EnableWAF=true` - Protect against common web attacks

---

### Step 4: Build and Push Langflow Docker Image

```bash
# Navigate to Langflow multi-tenant deployment
cd /home/shane/PycharmProjects/langflow/deploy/multi-tenant

# Get ECR repository URL from VPC stack
ECR_REPO=$(aws cloudformation describe-stacks \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack \
    --query 'Stacks[0].Outputs[?OutputKey==`ECRRepositoryUri`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${ECR_REPO}

# Build Docker image
docker build -t langflow-multi-tenant:latest -f Dockerfile ../..

# Tag and push to ECR
docker tag langflow-multi-tenant:latest ${ECR_REPO}:latest
docker tag langflow-multi-tenant:latest ${ECR_REPO}:v1.0
docker push ${ECR_REPO}:latest
docker push ${ECR_REPO}:v1.0
```

---

### Step 5: Deploy Fargate Application Stack

```bash
# Get outputs from previous stacks
VPC_STACK=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-vpc-stack
PLATFORM_STACK=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-platform-stack
RDS_STACK=${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-rds-stack

# Get RDS endpoint
DB_HOST=$(aws cloudformation describe-stacks \
    --stack-name ${RDS_STACK} \
    --query 'Stacks[0].Outputs[?OutputKey==`DBClusterEndpoint`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

# Deploy Fargate stack
aws cloudformation deploy \
    --template-file ./aws/apps/fargate-stack.cfn.yaml \
    --stack-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-fargate-stack \
    --parameter-overrides \
        ProjectPrefix=${PROJECT_PREFIX} \
        ProjectId=${PROJECT_ID} \
        StageName=${STAGE} \
        VpcStackName=${VPC_STACK} \
        PlatformStackName=${PLATFORM_STACK} \
        RdsStackName=${RDS_STACK} \
        ContainerImage=${ECR_REPO}:latest \
        ContainerPort=7860 \
        HealthCheckPath=/health \
        TaskCpu=2048 \
        TaskMemory=4096 \
        DesiredCount=2 \
        EnableAutoScaling=true \
        MinTaskCount=2 \
        MaxTaskCount=10 \
        DBHost=${DB_HOST} \
        DBPort=5432 \
        DBName=langflow \
    --capabilities CAPABILITY_IAM \
    --region ${AWS_REGION}
```

**Expected Output:**
- ECS Fargate cluster
- ECS service with 2 tasks
- Auto-scaling policies (CPU/Memory based)
- CloudWatch Logs group
- Task execution role with RDS and Secrets Manager access

---

## Multi-Tenant URL Routing

### ALB Path-Based Routing Configuration

The ALB needs to be configured for tenant-specific routing:

```yaml
# In platform-stack.cfn.yaml or fargate-stack.cfn.yaml
ListenerRules:
  - Priority: 1
    PathPattern: /tenant/*
    TargetGroupArn: !Ref FargateTargetGroup

  - Priority: 2
    PathPattern: /health
    TargetGroupArn: !Ref FargateTargetGroup

  - Priority: 3
    PathPattern: /api/v1/*
    TargetGroupArn: !Ref FargateTargetGroup
```

### URL Examples

```
# Public/Admin endpoints
https://langflow.your-domain.com/health
https://langflow.your-domain.com/api/v1/login

# Tenant-specific endpoints
https://langflow.your-domain.com/tenant/company-a/api/v1/flows
https://langflow.your-domain.com/tenant/company-b/api/v1/users
```

---

## Post-Deployment: Tenant Management

### Create First Tenant Schema

```bash
# Get Fargate task ID
TASK_ARN=$(aws ecs list-tasks \
    --cluster ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-cluster \
    --service-name ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-service \
    --query 'taskArns[0]' \
    --output text \
    --region ${AWS_REGION})

# Execute command in Fargate task
aws ecs execute-command \
    --cluster ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-cluster \
    --task ${TASK_ARN} \
    --container ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-container \
    --interactive \
    --command "python lfhelper.py schema-add --prefix company-a"
```

### Add Users to Tenant

```bash
aws ecs execute-command \
    --cluster ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-cluster \
    --task ${TASK_ARN} \
    --container ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-container \
    --interactive \
    --command "python lfhelper.py user-add --schema company-a-XXXXXX --username admin@company-a.com"
```

---

## Monitoring and Logging

### CloudWatch Metrics

Available in AWS Console:
- **ECS Service Metrics**: CPU, Memory, Task count
- **ALB Metrics**: Request count, latency, errors
- **RDS Metrics**: ACU usage, connections, query performance

### CloudWatch Logs

```bash
# View Langflow application logs
aws logs tail /ecs/${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt \
    --follow \
    --region ${AWS_REGION}
```

### Database Monitoring

```bash
# Connect to RDS via Session Manager (requires bastion or VPN)
# OR use RDS Query Editor in AWS Console

# View tenant schemas
SELECT prefix, schema_name, created_at
FROM public.tenant_schemas
ORDER BY created_at DESC;

# View schema sizes
SELECT * FROM public.get_schema_sizes();
```

---

## Cost Optimization

### Estimated Monthly Costs (us-east-1)

```
VPC:
  - NAT Gateway (2 AZs):        ~$64/month
  - VPC Endpoints (optional):   ~$14/month each

RDS Aurora Serverless v2:
  - 0.5-2 ACUs auto-scaling:    ~$43-$172/month
  - Storage (100GB):            ~$10/month

ECS Fargate:
  - 2 tasks (2 vCPU, 4GB):      ~$120/month
  - Auto-scaling up to 10:      Up to $600/month

ALB:
  - Load Balancer:              ~$22/month
  - LCU (traffic based):        Variable

WAF:
  - Web ACL:                    ~$5/month
  - Rules:                      ~$1/rule/month

TOTAL (baseline):               ~$264/month
TOTAL (with auto-scaling):      Up to $900/month
```

### Cost Reduction Options

1. **Disable NAT Gateway** (if not needed):
   - Saves ~$64/month
   - Use VPC Endpoints instead (~$14/month each)

2. **Reduce RDS capacity**:
   - MinCapacity=0.5, MaxCapacity=1
   - Enable AutoPause for dev/test

3. **Reduce Fargate tasks**:
   - Start with 1 task for dev
   - Enable auto-scaling only in production

4. **Use Spot instances** (if available):
   - Not currently supported for Fargate
   - Consider EC2 with ECS for cost savings

---

## Security Considerations

### Network Security
✅ Private subnets for Fargate tasks
✅ Security groups restrict RDS access
✅ NAT Gateway for outbound internet
✅ AWS WAF for application protection

### Database Security
✅ RDS in private subnets only
✅ Credentials in Secrets Manager
✅ SSL/TLS encryption in transit
✅ Encryption at rest enabled
✅ Schema-level tenant isolation

### Application Security
✅ HTTPS only (via ACM certificate)
✅ API key authentication
✅ Password hashing (bcrypt)
✅ CORS configured
✅ Rate limiting (via WAF)

---

## Troubleshooting

### Fargate Tasks Not Starting

```bash
# Check service events
aws ecs describe-services \
    --cluster ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-cluster \
    --services ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-service \
    --region ${AWS_REGION}

# Check task failures
aws ecs describe-tasks \
    --cluster ${PROJECT_PREFIX}-$(echo $PROJECT_ID | cut -d'-' -f1)-${STAGE}-wbskt-cluster \
    --tasks ${TASK_ARN} \
    --region ${AWS_REGION}
```

**Common Issues:**
- ECR image pull failure → Check IAM permissions
- Container health check failing → Verify `/health` endpoint
- Database connection timeout → Check security groups

### RDS Connection Issues

```bash
# Verify RDS is accessible from Fargate
# Check security group rules allow Fargate → RDS on port 5432
```

### ALB Health Check Failing

```bash
# Check target health
aws elbv2 describe-target-health \
    --target-group-arn $(aws cloudformation describe-stacks \
        --stack-name ${PLATFORM_STACK} \
        --query 'Stacks[0].Outputs[?OutputKey==`TargetGroupArn`].OutputValue' \
        --output text \
        --region ${AWS_REGION})
```

---

## Next Steps

1. ✅ Infrastructure project created
2. ⏭️ Deploy VPC stack
3. ⏭️ Deploy RDS stack
4. ⏭️ Deploy Platform stack
5. ⏭️ Build and push Docker image
6. ⏭️ Deploy Fargate stack
7. ⏭️ Create tenant schemas using lfhelper.py
8. ⏭️ Test multi-tenant isolation
9. ⏭️ Configure monitoring and alerts
10. ⏭️ Set up CI/CD pipeline

---

## References

- **Infrastructure Code**: `/home/shane/PycharmProjects/langflow-infra/`
- **Application Code**: `/home/shane/PycharmProjects/langflow/`
- **Deployment Guide**: `README.md` in this repository
- **Multi-Tenant Tests**: `/home/shane/PycharmProjects/langflow/MULTI_TENANT_TEST_RESULTS.md`
- **Helper Script**: `/home/shane/PycharmProjects/langflow/lfhelper.py`

---

**Status**: ✅ Ready for deployment
**Created By**: Claude Code
**Date**: November 9, 2025