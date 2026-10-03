# ---------------------------------------------------------------------------
# CI/CD identity: GitHub Actions assumes this role through OIDC (no stored AWS keys).
# It can push images and roll the ECS service, nothing else.
# ---------------------------------------------------------------------------

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/name (e.g. rajratangm/KISAN-MITRA). Empty disables the CI role."
  type        = string
  default     = ""
}

variable "github_deploy_branch" {
  description = "Only workflows running on this branch can assume the deploy role."
  type        = string
  default     = "phase-1-mvp"
}

locals {
  cicd = var.enable_compute && var.github_repo != "" ? 1 : 0
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = local.cicd
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "deploy" {
  count = local.cicd
  name  = "${local.name}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github[0].arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/${var.github_deploy_branch}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy" {
  count = local.cicd
  name  = "deploy"
  role  = aws_iam_role.deploy[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
        ]
        Resource = aws_ecr_repository.api[0].arn
      },
      {
        Sid    = "EcsDeploy"
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService",
        ]
        Resource = "*"
      },
      {
        Sid      = "PassTaskRoles"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.task[0].arn, aws_iam_role.task_execution[0].arn]
      },
    ]
  })
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable in GitHub."
  value       = local.cicd == 1 ? aws_iam_role.deploy[0].arn : null
}
