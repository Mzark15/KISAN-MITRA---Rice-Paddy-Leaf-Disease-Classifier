output "api_url" {
  description = "Base URL for the app (VITE_API_BASE_URL). Point a DNS name at the ALB and use that https URL for release builds."
  value       = var.enable_compute ? "${local.https ? "https" : "http"}://${aws_lb.api[0].dns_name}" : null
}

output "ecr_repository_url" {
  value = var.enable_compute ? aws_ecr_repository.api[0].repository_url : null
}

output "ecs_cluster" {
  value = var.enable_compute ? aws_ecs_cluster.main[0].name : null
}
