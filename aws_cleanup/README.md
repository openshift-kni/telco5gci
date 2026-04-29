# AWS Cleanup

Automated cleanup of orphaned AWS resources left behind by CI jobs (OpenShift Prow). CI jobs create infrastructure (VPCs, EC2 instances, load balancers, etc.) tagged with a `ci-op-` prefix. When jobs fail or time out, these resources remain and accumulate cost. This tooling finds and deletes them.

## Components

| File | Description |
| --- | --- |
| `aws_delete.py` | Main cleanup script. Runs standalone (CLI) or as an AWS Lambda function. |
| `tf/main.tf` | Terraform configuration that provisions the Lambda, IAM roles, S3 bucket, and EventBridge schedule. |

## Prerequisites

- Python 3.10+
- `boto3` (`pip install boto3`)
- An AWS CLI profile (default: `telco-ci`) with sufficient permissions

## CLI Usage

```bash
# Dry run across all regions (us-east-1, us-east-2, us-west-1, us-west-2)
python aws_cleanup/aws_delete.py --dry-run

# Real deletion in a specific region
python aws_cleanup/aws_delete.py --profile telco-ci --region us-east-2

# Custom tag prefix (default: ci-op-)
python aws_cleanup/aws_delete.py --tag ci-op- --profile telco-ci

# With email report
python aws_cleanup/aws_delete.py --profile telco-ci --send-email
python aws_cleanup/aws_delete.py --profile telco-ci --send-email --to someone@redhat.com
```

### CLI Options

| Flag | Default | Description |
|---|---|---|
| `--tag` | `ci-op-` | Tag prefix that identifies CI-created resources |
| `--profile` | `telco-ci` | AWS CLI profile name |
| `--region` | all 4 US regions | Limit to a single region (`us-east-1`, `us-east-2`, `us-west-1`, `us-west-2`) |
| `--dry-run` | off | Print what would be deleted without making changes |
| `--send-email` | off | Send a cost-savings summary email after cleanup |
| `--to` | `sshnaidm@redhat.com` | Email recipient (used with `--send-email`) |

## How It Works

### Expiration Logic

A resource is eligible for deletion if any of these apply:

1. **`expirationDate` tag** exists and is more than 6 hours past due (format: `YYYY-MM-DDTHH:MM+00:00`).
2. **`CreateDate`/`CreateTime`** is older than 6 hours AND the resource is tagged with the `ci-op-` prefix (via Name tag, `kubernetes.io/cluster/` tag, UserName, RoleName, or InstanceProfileName).
3. **Unattached Elastic IPs** with no associated instance or network interface.

### Deletion Order

VPC sub-resources are deleted in dependency order:

1. Load Balancers (Classic and v2)
2. EC2 Instances
3. NAT Gateways
4. Elastic IPs (tagged + unattached)
5. Internet Gateways (detach, then delete)
6. Network Interfaces (skips `in-use`)
7. Route Tables
8. Security Groups (revokes all rules if blocked by dependencies)
9. Subnets
10. VPC Endpoints
11. VPC

After VPC cleanup, associated S3 buckets and EBS volumes are deleted by tag. Finally, `AWSExpiredResources.eliminate()` sweeps all resource types globally (EC2, LB, NAT, IGW, VPC endpoints, target groups, ENIs, route tables, security groups, subnets, DHCP options, VPCs, EIPs, volumes, S3, IAM users/roles/instance profiles).

Each VPC deletion cycle retries up to 10 times (with 60-second waits) until all sub-resources are removed.

### Cost Estimation

The `Price` class estimates hourly cost savings for each deleted resource using the AWS Pricing API (us-east-1). Prices are cached per resource type. Fallback defaults:

| Resource | Default Price |
|---|---|
| EC2 instance | `$0.17/hr` (looked up by instance type) |
| Classic LB | `$0.025/hr` |
| NLB/ALB | `$0.0225/hr` |
| NAT Gateway | `$0.045/hr` |
| Elastic IP | `$0.005/hr` |
| EBS Volume | price-per-GB-month / 720 |
| S3 Bucket | price-per-GB-month / 720 (calculates actual size) |

## AWS Lambda

The script doubles as a Lambda function via the `lambda_handler` entry point. The Lambda is triggered weekly by an EventBridge rule and writes its report to an S3 bucket.

### Lambda Event Payload

```json
{
  "tag": "ci-op-",
  "dry_run": false,
  "report_bucket": "telco-ci-cleanup-reports",
  "region": null
}
```

All fields are optional and fall back to the defaults shown above. When `region` is null, all four US regions are processed.

### Reports

Lambda writes reports to `s3://telco-ci-cleanup-reports/reports/YYYY-MM-DD.txt`. Reports are automatically expired after 90 days via an S3 lifecycle rule.

## Terraform (`tf/`)

The `tf/` directory contains a Terraform configuration that provisions all the AWS infrastructure for the Lambda-based cleanup:

### Resources Created

- **IAM user** (`telco-ci-cleanup`) with policies for Lambda deployment, CloudWatch Logs, and S3 report bucket access
- **IAM role** (`telco-ci-cleanup-lambda-role`) with policies for EC2, ELB, S3, IAM, and Pricing API access
- **Lambda function** (`telco-ci-aws-cleanup`) running Python 3.13, 256 MB memory, 15-minute timeout
- **EventBridge rule** triggering the Lambda every Monday at 10:00 AM UTC
- **S3 bucket** (`telco-ci-cleanup-reports`) with a 90-day lifecycle policy on `reports/`

### Terraform Variables

| Variable | Default | Description |
|---|---|---|
| `aws_region` | `us-east-1` | Region for Terraform provider |
| `aws_profile` | `telco-ci` | AWS CLI profile |
| `user_name` | `telco-ci-cleanup` | IAM user name |
| `lambda_role_name` | `telco-ci-cleanup-lambda-role` | Lambda execution role name |
| `schedule_expression` | `cron(0 10 ? * MON *)` | EventBridge schedule (Monday 10:00 UTC) |
| `report_bucket_name` | `telco-ci-cleanup-reports` | S3 bucket for reports |

### Usage

```bash
cd aws_cleanup/tf
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### Outputs

| Output | Description |
|---|---|
| `user_name` | IAM user name |
| `user_access_key_id` | Access key ID for the IAM user |
| `user_secret_access_key` | Secret access key (sensitive) |
| `lambda_role_arn` | ARN of the Lambda execution role |
| `lambda_function_name` | Name of the Lambda function |
| `report_bucket` | S3 bucket name for reports |

## CI / CD

Two GitHub Actions workflows:

- **aws-cleanup-check.yml** -- Runs on pushes to `master` and PRs touching `aws_cleanup/**`. Checks syntax (`py_compile`), lint (`pyflakes`, `flake8`), import verification, and CLI help.
- **aws-cleanup-deploy.yml** -- Runs on pushes to `master` when `aws_cleanup/aws_delete.py` changes. Packages and deploys the updated code to the Lambda function. Requires `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` repository secrets.
