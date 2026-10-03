# All tables are on-demand (pay per request, nothing to size, free tier covers
# development) with point-in-time recovery for backups.

locals {
  pitr_enabled = true
}

# One row per farmer, keyed by the Cognito user id (`sub`).
resource "aws_dynamodb_table" "users" {
  name                        = "${local.name}-users"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "user_id"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "user_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = local.pitr_enabled
  }
}

# One row per photo diagnosis.
resource "aws_dynamodb_table" "diagnoses" {
  name                        = "${local.name}-diagnoses"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "diagnosis_id"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "diagnosis_id"
    type = "S"
  }
  attribute {
    name = "day"
    type = "S"
  }
  attribute {
    name = "user_id"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "S"
  }

  # Dashboard "recent diagnoses": partitioned by day so writes spread out at scale.
  global_secondary_index {
    name            = "by_day"
    projection_type = "ALL"

    key_schema {
      attribute_name = "day"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  # A farmer's own photo history.
  global_secondary_index {
    name            = "by_user"
    projection_type = "ALL"

    key_schema {
      attribute_name = "user_id"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = local.pitr_enabled
  }
}

# Dashboard counters: one item per day (`day#YYYY-MM-DD`), updated atomically on
# every event, so the dashboard never scans the diagnoses table.
resource "aws_dynamodb_table" "stats" {
  name                        = "${local.name}-stats"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = local.pitr_enabled
  }
}

# OTP / login rate limits. Items expire automatically via TTL.
resource "aws_dynamodb_table" "rate_limits" {
  name         = "${local.name}-rate-limits"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
