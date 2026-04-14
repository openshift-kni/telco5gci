terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile to use"
  type        = string
  default     = "telco-ci"
}

variable "user_name" {
  description = "Name of the IAM user for running the cleanup Lambda"
  type        = string
  default     = "telco-ci-cleanup"
}

variable "lambda_role_name" {
  description = "Name of the IAM role for the Lambda execution"
  type        = string
  default     = "telco-ci-cleanup-lambda-role"
}

variable "schedule_expression" {
  description = "EventBridge schedule expression for the cleanup Lambda"
  type        = string
  default     = "rate(7 days)"
}

variable "mail_recipient" {
  description = "Email recipient for the Lambda cleanup report"
  type        = string
  default     = "cnf-devel@redhat.com"
}

# ---------------------------------------------------------------------------
# IAM user that can deploy and invoke the Lambda
# ---------------------------------------------------------------------------

resource "aws_iam_user" "cleanup_user" {
  name = var.user_name
}

resource "aws_iam_access_key" "cleanup_user_key" {
  user = aws_iam_user.cleanup_user.name
}

resource "aws_iam_user_policy" "cleanup_user_lambda_deploy" {
  name = "${var.user_name}-lambda-deploy"
  user = aws_iam_user.cleanup_user.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaDeploy"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:GetFunction",
          "lambda:InvokeFunction",
          "lambda:DeleteFunction",
          "lambda:ListFunctions",
          "lambda:AddPermission",
          "lambda:RemovePermission",
        ]
        Resource = "*"
      },
      {
        Sid      = "PassRoleToLambda"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.lambda_role.arn
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
        ]
        Resource = "*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Lambda execution role — carries all permissions the cleanup script needs
# ---------------------------------------------------------------------------

resource "aws_iam_role" "lambda_role" {
  name = var.lambda_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "cleanup_ec2" {
  name = "cleanup-ec2"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2Describe"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVpcs",
          "ec2:DescribeInstances",
          "ec2:DescribeNatGateways",
          "ec2:DescribeInternetGateways",
          "ec2:DescribeVpcEndpoints",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeRouteTables",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeAddresses",
          "ec2:DescribeVolumes",
          "ec2:DescribeDhcpOptions",
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2Delete"
        Effect = "Allow"
        Action = [
          "ec2:TerminateInstances",
          "ec2:DeleteNatGateway",
          "ec2:DetachInternetGateway",
          "ec2:DeleteInternetGateway",
          "ec2:DeleteVpcEndpoints",
          "ec2:DeleteNetworkInterface",
          "ec2:DeleteRouteTable",
          "ec2:DeleteSecurityGroup",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:DeleteSubnet",
          "ec2:ReleaseAddress",
          "ec2:DeleteVolume",
          "ec2:DeleteDhcpOptions",
          "ec2:DeleteVpc",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "cleanup_elb" {
  name = "cleanup-elb"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ELB"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DeleteTargetGroup",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "cleanup_s3" {
  name = "cleanup-s3"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3"
        Effect = "Allow"
        Action = [
          "s3:ListAllMyBuckets",
          "s3:ListBucket",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:DeleteBucket",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "cleanup_iam" {
  name = "cleanup-iam"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IAM"
        Effect = "Allow"
        Action = [
          "iam:ListUsers",
          "iam:ListUserPolicies",
          "iam:DeleteUserPolicy",
          "iam:ListAccessKeys",
          "iam:DeleteAccessKey",
          "iam:DeleteUser",
          "iam:ListInstanceProfiles",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:ListRoles",
          "iam:ListAttachedRolePolicies",
          "iam:DetachRolePolicy",
          "iam:DeletePolicy",
          "iam:ListRolePolicies",
          "iam:DeleteRolePolicy",
          "iam:DeleteRole",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "cleanup_pricing" {
  name = "cleanup-pricing"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Pricing"
        Effect = "Allow"
        Action = [
          "pricing:GetProducts",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "cleanup_ses" {
  name = "cleanup-ses"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SES"
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail",
        ]
        Resource = "*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Lambda function
# ---------------------------------------------------------------------------

data "archive_file" "cleanup_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../aws_delete.py"
  output_path = "${path.module}/lambda_package.zip"
}

resource "aws_lambda_function" "cleanup" {
  function_name    = "telco-ci-aws-cleanup"
  role             = aws_iam_role.lambda_role.arn
  handler          = "aws_delete.lambda_handler"
  runtime          = "python3.13"
  timeout          = 900
  memory_size      = 256
  filename         = data.archive_file.cleanup_lambda_zip.output_path
  source_code_hash = data.archive_file.cleanup_lambda_zip.output_base64sha256
}

# ---------------------------------------------------------------------------
# EventBridge weekly schedule
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "weekly_cleanup" {
  name                = "telco-ci-weekly-cleanup"
  description         = "Trigger AWS cleanup Lambda weekly"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "cleanup_target" {
  rule = aws_cloudwatch_event_rule.weekly_cleanup.name
  arn  = aws_lambda_function.cleanup.arn

  input = jsonencode({
    tag       = "ci-op-"
    dry_run   = false
    send_mail = true
    to        = var.mail_recipient
  })
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cleanup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_cleanup.arn
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "user_name" {
  value = aws_iam_user.cleanup_user.name
}

output "user_access_key_id" {
  value = aws_iam_access_key.cleanup_user_key.id
}

output "user_secret_access_key" {
  value     = aws_iam_access_key.cleanup_user_key.secret
  sensitive = true
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda_role.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.cleanup.function_name
}
