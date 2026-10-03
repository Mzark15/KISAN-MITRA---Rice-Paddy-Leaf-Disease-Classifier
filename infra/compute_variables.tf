# Inputs for compute.tf (VPC, ALB, ECS Fargate, autoscaling, WAF, alarms).

variable "enable_compute" {
  description = "Create the API hosting stack. Turn off only to manage Cognito/DynamoDB on their own."
  type        = bool
  default     = true
}

variable "acm_certificate_arn" {
  description = "ACM certificate (same region) for the HTTPS listener. Required outside dev: the Android app only talks HTTPS. Empty = plain-HTTP listener, dev only."
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "ECR image tag the task definition starts with. CI deploys later builds by commit SHA."
  type        = string
  default     = "bootstrap"
}

variable "task_cpu" {
  description = "Fargate CPU units per task (1024 = 1 vCPU). Inference is CPU-bound."
  type        = number
  default     = 2048
}

variable "task_memory" {
  description = "Fargate memory (MiB) per task. TensorFlow plus the EfficientNetV2-S model needs about 1.5 GB."
  type        = number
  default     = 4096
}

variable "min_tasks" {
  description = "Minimum running tasks. Keep at least 2 (one per AZ) in prod."
  type        = number
  default     = 2
}

variable "max_tasks" {
  description = "Autoscaling ceiling. Also the cap on the AWS bill during a traffic spike or attack."
  type        = number
  default     = 20
}

variable "single_nat_gateway" {
  description = "One shared NAT gateway (cheaper, but one AZ is a single point of failure for outbound LLM calls) or one per AZ (prod)."
  type        = bool
  default     = false
}

variable "waf_rate_limit_per_5min" {
  description = "Max requests per client IP per 5 minutes before the WAF blocks it."
  type        = number
  default     = 2000
}

variable "cors_origins" {
  description = "Allowed browser origins. The Android app's origin is https://localhost."
  type        = string
  default     = "https://localhost"
}

variable "auth_disabled" {
  description = "Temporary guest mode: the API skips login and treats each client IP as a guest. Keep false in production."
  type        = bool
  default     = false
}
