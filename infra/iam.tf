# ---------------------------------------------------------------------------
# Role Cognito assumes to send SMS through SNS
# ---------------------------------------------------------------------------

resource "aws_iam_role" "cognito_sms" {
  name = "${local.name}-cognito-sms"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cognito-idp.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "sts:ExternalId"    = "${local.name}-cognito-sms"
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "cognito_sms" {
  name = "sns-publish"
  role = aws_iam_role.cognito_sms.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sns:Publish"
      Resource = "*" # SMS to a phone number has no resource ARN
    }]
  })
}

# ---------------------------------------------------------------------------
# Backend identity: only what the API needs (least privilege)
#
# Access keys are the simplest option for Railway / a laptop. On AWS compute
# (EKS, ECS) replace this user with an IAM role (IRSA / task role) and delete the key.
# ---------------------------------------------------------------------------

resource "aws_iam_user" "backend" {
  name = "${local.name}-backend"
}

resource "aws_iam_user_policy" "backend" {
  name = "backend-access"
  user = aws_iam_user.backend.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoTables"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:DescribeTable",
        ]
        Resource = flatten([
          for t in [
            aws_dynamodb_table.users,
            aws_dynamodb_table.diagnoses,
            aws_dynamodb_table.stats,
            aws_dynamodb_table.rate_limits,
          ] : [t.arn, "${t.arn}/index/*"]
        ])
      },
      {
        Sid    = "CognitoAdminAuth"
        Effect = "Allow"
        Action = [
          "cognito-idp:AdminGetUser",
          "cognito-idp:AdminInitiateAuth",
          "cognito-idp:AdminRespondToAuthChallenge",
          "cognito-idp:AdminUserGlobalSignOut",
          "cognito-idp:AdminDeleteUser",
        ]
        Resource = [
          aws_cognito_user_pool.farmers.arn,
          aws_cognito_user_pool.admins.arn,
        ]
      },
    ]
  })
}

resource "aws_iam_access_key" "backend" {
  user = aws_iam_user.backend.name
}

# ---------------------------------------------------------------------------
# SNS: send OTPs as transactional SMS, with a spend cap
# ---------------------------------------------------------------------------

resource "aws_sns_sms_preferences" "this" {
  count               = var.manage_sms_preferences ? 1 : 0
  default_sms_type    = "Transactional"
  monthly_spend_limit = var.sms_monthly_spend_limit_usd
}
