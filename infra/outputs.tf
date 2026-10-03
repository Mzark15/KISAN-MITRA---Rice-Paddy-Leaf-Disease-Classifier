output "farmer_user_pool_id" {
  value = aws_cognito_user_pool.farmers.id
}

output "admin_user_pool_id" {
  value = aws_cognito_user_pool.admins.id
}

output "table_prefix" {
  value = local.name
}

# Everything the backend needs, in .env format:
#   terraform output -raw backend_env > ../.env.aws
# Contains secrets — never commit it.
output "backend_env" {
  sensitive = true
  value     = <<-EOT
    AWS_REGION=${var.region}
    AWS_ACCESS_KEY_ID=${aws_iam_access_key.backend.id}
    AWS_SECRET_ACCESS_KEY=${aws_iam_access_key.backend.secret}
    DYNAMODB_TABLE_PREFIX=${local.name}
    COGNITO_FARMER_POOL_ID=${aws_cognito_user_pool.farmers.id}
    COGNITO_FARMER_CLIENT_ID=${aws_cognito_user_pool_client.farmers_backend.id}
    COGNITO_FARMER_CLIENT_SECRET=${aws_cognito_user_pool_client.farmers_backend.client_secret}
    COGNITO_ADMIN_POOL_ID=${aws_cognito_user_pool.admins.id}
    COGNITO_ADMIN_CLIENT_ID=${aws_cognito_user_pool_client.admins_backend.id}
    COGNITO_ADMIN_CLIENT_SECRET=${aws_cognito_user_pool_client.admins_backend.client_secret}
  EOT
}
