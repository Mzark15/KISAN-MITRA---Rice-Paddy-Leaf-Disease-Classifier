variable "project" {
  description = "Prefix for every resource name."
  type        = string
  default     = "kisan-mitra"
}

variable "environment" {
  description = "dev / staging / prod. Each environment gets its own pools and tables."
  type        = string
  default     = "dev"
}

variable "region" {
  description = "AWS region. Mumbai keeps farmer data in India (DPDP Act)."
  type        = string
  default     = "ap-south-1"
}

variable "admin_email" {
  description = "Email of the first dashboard admin. Cognito emails them a temporary password."
  type        = string
}

variable "deletion_protection" {
  description = "Protect user pools and tables from `terraform destroy`. Turn on for prod."
  type        = bool
  default     = false
}

variable "farmer_refresh_token_days" {
  description = "How long a farmer stays logged in without using the app. Each refresh issues a new token, so active users never see the login screen again."
  type        = number
  default     = 180
}

variable "admin_refresh_token_days" {
  description = "Dashboard sessions are shorter: staff log in again after this many days."
  type        = number
  default     = 7
}

variable "otp_message" {
  description = "SMS text for sign-in codes. In India this must match a template registered on the DLT portal before production."
  type        = string
  default     = "Kisan Mitra: your login code is {####}. Do not share it with anyone."
}

variable "sms_monthly_spend_limit_usd" {
  description = "Account-wide SNS SMS spend cap (USD). The AWS default is 1 (~350 OTPs to India). Raise it before launch."
  type        = number
  default     = 1
}

variable "manage_sms_preferences" {
  description = "Let Terraform set the account-wide SNS SMS type and spend limit. Needs the account's SMS/End User Messaging service enabled; if SetSMSAttributes fails with a subscription error, leave false and set the limit in the SNS console."
  type        = bool
  default     = false
}
