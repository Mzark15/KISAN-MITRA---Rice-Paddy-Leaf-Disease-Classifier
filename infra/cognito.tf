locals {
  name = "${var.project}-${var.environment}"
}

# ---------------------------------------------------------------------------
# Farmers: passwordless sign-in with an SMS one-time code, phone number as login
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool" "farmers" {
  name                = "${local.name}-farmers"
  user_pool_tier      = "ESSENTIALS" # required for passwordless (choice-based) sign-in
  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  username_attributes      = ["phone_number"]
  auto_verified_attributes = ["phone_number"]

  sign_in_policy {
    # PASSWORD must always be listed; farmers are created without one, so only SMS_OTP works for them.
    allowed_first_auth_factors = ["SMS_OTP", "PASSWORD"]
  }

  sms_authentication_message = var.otp_message
  sms_verification_message   = var.otp_message

  sms_configuration {
    external_id    = "${local.name}-cognito-sms"
    sns_caller_arn = aws_iam_role.cognito_sms.arn
    sns_region     = var.region
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_phone_number"
      priority = 1
    }
  }

  schema {
    name                = "phone_number"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 8
      max_length = 20
    }
  }

  # Only the backend (with the client secret) can start a sign-up or sign-in.
  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  # Cognito needs the SNS role to exist and be assumable before the pool is created.
  depends_on = [aws_iam_role_policy.cognito_sms]
}

resource "aws_cognito_user_pool_client" "farmers_backend" {
  name         = "${local.name}-farmers-backend"
  user_pool_id = aws_cognito_user_pool.farmers.id

  # Confidential client: the secret stays on the server, so nobody can call
  # Cognito directly with this client to trigger SMS and run up the bill.
  generate_secret = true

  # ALLOW_REFRESH_TOKEN_AUTH is rejected when refresh token rotation is on (Cognito
  # handles refresh itself in that mode), so only USER_AUTH is listed.
  explicit_auth_flows = [
    "ALLOW_USER_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  auth_session_validity         = 5 # minutes to enter the OTP

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = var.farmer_refresh_token_days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # Every refresh returns a new refresh token, so a farmer who opens the app at
  # least once every `farmer_refresh_token_days` never has to log in again.
  refresh_token_rotation {
    feature                    = "ENABLED"
    retry_grace_period_seconds = 30
  }
}

# ---------------------------------------------------------------------------
# Staff (dashboard): email + password + mandatory authenticator-app MFA
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool" "admins" {
  name                = "${local.name}-admins"
  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  mfa_configuration = "ON"
  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # No self sign-up: staff accounts are created by an admin.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "admins_backend" {
  name            = "${local.name}-admins-backend"
  user_pool_id    = aws_cognito_user_pool.admins.id
  generate_secret = true

  explicit_auth_flows = [
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  auth_session_validity         = 10

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = var.admin_refresh_token_days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# Roles, read from the `cognito:groups` claim in the access token.
resource "aws_cognito_user_group" "staff" {
  for_each = {
    admin         = "Full access to the dashboard and staff management"
    field_officer = "Field team: dashboard access"
    viewer        = "Read-only dashboard access"
  }

  name         = each.key
  description  = each.value
  user_pool_id = aws_cognito_user_pool.admins.id
}

resource "aws_cognito_user" "first_admin" {
  user_pool_id             = aws_cognito_user_pool.admins.id
  username                 = var.admin_email
  desired_delivery_mediums = ["EMAIL"]

  attributes = {
    email          = var.admin_email
    email_verified = true
  }

  # The temporary password is emailed by Cognito and changed at first login.
  lifecycle {
    ignore_changes = [temporary_password, password]
  }
}

resource "aws_cognito_user_in_group" "first_admin" {
  user_pool_id = aws_cognito_user_pool.admins.id
  group_name   = aws_cognito_user_group.staff["admin"].name
  username     = aws_cognito_user.first_admin.sub
}
