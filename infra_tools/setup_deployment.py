#!/usr/bin/env python3
"""
Setup Deployment Tasks for Django Applications.

Injects AWS Fargate deployment poe tasks into an existing pyproject.toml file.
"""

import argparse
import sys
from pathlib import Path


# Deployment tasks template
DEPLOYMENT_TASKS_TEMPLATE = '''
[tool.poe.tasks.build]
help = "Build Docker image and push to ECR"
interpreter = "bash"
shell = """
# Load environment
source .env.${STAGE_NAME:-dev}

# Get ECR URI
ECR_URI=$(aws cloudformation describe-stacks \\
  --stack-name ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE_NAME}-platform-stack \\
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
interpreter = "bash"
shell = """
# Load environment
source .env.${STAGE_NAME:-dev}

# Get cluster and service names
CLUSTER_NAME="${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE_NAME}-wbskt-cluster"
SERVICE_NAME="${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE_NAME}-wbskt-service"

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
interpreter = "bash"
shell = """
# Load environment
source .env.${STAGE_NAME:-dev}

# Get cluster and service
CLUSTER_NAME="${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE_NAME}-wbskt-cluster"
SERVICE_NAME="${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE_NAME}-wbskt-service"

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
  --container ${PROJECT_PREFIX}-${PROJECT_ID_PREFIX}-${STAGE_NAME}-wbskt-container \\
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


def inject_deployment_tasks(pyproject_path: Path, env_file: Path | None = None, dry_run: bool = False) -> None:
    """Inject deployment tasks into pyproject.toml."""
    if not pyproject_path.exists():
        print(f"❌ Error: {pyproject_path} not found", file=sys.stderr)
        sys.exit(1)

    # Read existing pyproject.toml
    content = pyproject_path.read_text()

    # Check if deployment tasks already exist
    if '[tool.poe.tasks.build]' in content and 'Build Docker image and push to ECR' in content:
        print("⚠️  Deployment tasks already exist in pyproject.toml")
        print("   Tasks: build, deploy, migrate, build-deploy, build-deploy-migrate")
        return

    # Load environment variables for validation
    env_vars = load_env_file(env_file) if env_file else {}

    # Validate required environment variables
    required_vars = ['AWS_REGION', 'PROJECT_PREFIX', 'PROJECT_ID_PREFIX', 'STAGE_NAME']
    missing_vars = [var for var in required_vars if var not in env_vars]

    if missing_vars and env_file:
        print(f"⚠️  Warning: Missing environment variables in {env_file}: {', '.join(missing_vars)}")
        print("   Make sure to add these to your .env file:")
        for var in missing_vars:
            print(f"     {var}=<value>")

    # Append deployment tasks to the end of the file
    if dry_run:
        print("🔍 Dry run - would append the following to pyproject.toml:")
        print(DEPLOYMENT_TASKS_TEMPLATE)
        return

    with pyproject_path.open('a') as f:
        f.write('\n')
        f.write('# AWS Fargate Deployment Tasks\n')
        f.write('# Generated by infra-tools setup-deployment-tasks\n')
        f.write(DEPLOYMENT_TASKS_TEMPLATE)

    print(f"✅ Deployment tasks added to {pyproject_path}")
    print("\nAdded tasks:")
    print("  • build              - Build Docker image and push to ECR")
    print("  • deploy             - Deploy application to Fargate")
    print("  • migrate            - Run Django migrations on Fargate")
    print("  • build-deploy       - Build and deploy")
    print("  • build-deploy-migrate - Build, deploy, and migrate")

    if env_file:
        print(f"\nConfiguration loaded from: {env_file}")
        if env_vars:
            print("Environment variables:")
            for key in required_vars:
                if key in env_vars:
                    print(f"  {key}: {env_vars[key]}")

    print("\nUsage:")
    print("  uv run poe build              # Build and push to ECR")
    print("  uv run poe deploy             # Deploy to Fargate")
    print("  uv run poe migrate            # Run migrations")
    print("  uv run poe build-deploy-migrate  # Complete deployment workflow")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Inject AWS Fargate deployment tasks into pyproject.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add deployment tasks to current directory
  uvx --from langflow-infra-tools setup-deployment-tasks

  # Add deployment tasks with environment file
  uvx --from langflow-infra-tools setup-deployment-tasks --env .env.dev

  # Dry run to preview changes
  uvx --from langflow-infra-tools setup-deployment-tasks --dry-run

  # Specify custom pyproject.toml path
  uvx --from langflow-infra-tools setup-deployment-tasks --pyproject /path/to/pyproject.toml
        """,
    )

    parser.add_argument(
        '--env',
        '-e',
        type=Path,
        help='Path to .env file for configuration validation (optional)',
    )

    parser.add_argument(
        '--pyproject',
        '-p',
        type=Path,
        default=Path('pyproject.toml'),
        help='Path to pyproject.toml file (default: ./pyproject.toml)',
    )

    parser.add_argument(
        '--dry-run',
        '-d',
        action='store_true',
        help='Preview changes without modifying files',
    )

    args = parser.parse_args()

    # Inject deployment tasks
    inject_deployment_tasks(
        pyproject_path=args.pyproject,
        env_file=args.env,
        dry_run=args.dry_run,
    )


if __name__ == '__main__':
    main()
