# ---------------------------------------------------------------------------
# Compute: the API on ECS Fargate behind an ALB, autoscaled, in private subnets.
#
#   Android app / web --HTTPS--> WAF --> ALB (public subnets, 2 AZs)
#                                          `--> Fargate tasks (private subnets, 2+ AZs)
#                                                |- DynamoDB, Cognito  (task IAM role, no access keys)
#                                                `- LLM / Bhashini APIs (outbound via NAT)
#
# The service is stateless (state lives in DynamoDB and Cognito), so scaling out is just
# more tasks. Everything here is gated by var.enable_compute.
# ---------------------------------------------------------------------------

locals {
  compute   = var.enable_compute ? 1 : 0
  azs       = slice(data.aws_availability_zones.available.names, 0, 2)
  https     = var.acm_certificate_arn != ""
  container = "api"
  port      = 8000
  nat_count = var.enable_compute ? (var.single_nat_gateway ? 1 : length(local.azs)) : 0
}

data "aws_availability_zones" "available" {
  state = "available"
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

resource "aws_vpc" "main" {
  count                = local.compute
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  count  = local.compute
  vpc_id = aws_vpc.main[0].id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count             = var.enable_compute ? length(local.azs) : 0
  vpc_id            = aws_vpc.main[0].id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(aws_vpc.main[0].cidr_block, 4, count.index)
  tags              = { Name = "${local.name}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = var.enable_compute ? length(local.azs) : 0
  vpc_id            = aws_vpc.main[0].id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(aws_vpc.main[0].cidr_block, 4, count.index + 8)
  tags              = { Name = "${local.name}-private-${count.index}" }
}

resource "aws_route_table" "public" {
  count  = local.compute
  vpc_id = aws_vpc.main[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }
}

resource "aws_route_table_association" "public" {
  count          = var.enable_compute ? length(local.azs) : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_eip" "nat" {
  count  = local.nat_count
  domain = "vpc"
}

resource "aws_nat_gateway" "main" {
  count         = local.nat_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  depends_on    = [aws_internet_gateway.main]
}

resource "aws_route_table" "private" {
  count  = var.enable_compute ? length(local.azs) : 0
  vpc_id = aws_vpc.main[0].id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[var.single_nat_gateway ? 0 : count.index].id
  }
}

resource "aws_route_table_association" "private" {
  count          = var.enable_compute ? length(local.azs) : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# DynamoDB traffic stays on the AWS network and skips NAT data charges.
resource "aws_vpc_endpoint" "dynamodb" {
  count             = local.compute
  vpc_id            = aws_vpc.main[0].id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id
}

# ---------------------------------------------------------------------------
# Security groups: internet -> ALB -> tasks, nothing else
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  count       = local.compute
  name        = "${local.name}-alb"
  description = "Public HTTP(S) to the load balancer"
  vpc_id      = aws_vpc.main[0].id
}

resource "aws_security_group" "tasks" {
  count       = local.compute
  name        = "${local.name}-tasks"
  description = "API containers: only the ALB can reach them"
  vpc_id      = aws_vpc.main[0].id
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  count             = local.compute
  security_group_id = aws_security_group.alb[0].id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  count             = local.compute
  security_group_id = aws_security_group.alb[0].id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_tasks" {
  count                        = local.compute
  security_group_id            = aws_security_group.alb[0].id
  referenced_security_group_id = aws_security_group.tasks[0].id
  from_port                    = local.port
  to_port                      = local.port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  count                        = local.compute
  security_group_id            = aws_security_group.tasks[0].id
  referenced_security_group_id = aws_security_group.alb[0].id
  from_port                    = local.port
  to_port                      = local.port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "tasks_out" {
  count             = local.compute
  security_group_id = aws_security_group.tasks[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# ---------------------------------------------------------------------------
# Image registry and logs
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "api" {
  count                = local.compute
  name                 = local.name
  image_tag_mutability = "IMMUTABLE" # every build is a unique commit-SHA tag
  force_delete         = !var.deletion_protection

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  count      = local.compute
  repository = aws_ecr_repository.api[0].name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 30 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  count             = local.compute
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

# ---------------------------------------------------------------------------
# Secrets. Cognito client secrets come from this stack. LLM and voice keys are set by hand,
# so they never enter Terraform state:
#   aws secretsmanager put-secret-value --secret-id <env>/llm --secret-string file://llm.json
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "cognito" {
  count                   = local.compute
  name                    = "${local.name}/cognito"
  recovery_window_in_days = var.deletion_protection ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "cognito" {
  count     = local.compute
  secret_id = aws_secretsmanager_secret.cognito[0].id
  secret_string = jsonencode({
    COGNITO_FARMER_CLIENT_SECRET = aws_cognito_user_pool_client.farmers_backend.client_secret
    COGNITO_ADMIN_CLIENT_SECRET  = aws_cognito_user_pool_client.admins_backend.client_secret
  })
}

resource "aws_secretsmanager_secret" "llm" {
  count                   = local.compute
  name                    = "${local.name}/llm"
  recovery_window_in_days = var.deletion_protection ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "llm" {
  count     = local.compute
  secret_id = aws_secretsmanager_secret.llm[0].id
  secret_string = jsonencode({
    SAMBANOVA_API_KEY = "CHANGE_ME"
    GEMINI_API_KEY    = "CHANGE_ME"
    BHASHINI_API_KEY  = "CHANGE_ME"
  })
  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ---------------------------------------------------------------------------
# IAM: the task role replaces the long-lived access key in iam.tf
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# Pulls the image, writes logs, reads the two secrets at container start.
resource "aws_iam_role" "task_execution" {
  count              = local.compute
  name               = "${local.name}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  count      = local.compute
  role       = aws_iam_role.task_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  count = local.compute
  name  = "read-secrets"
  role  = aws_iam_role.task_execution[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = [aws_secretsmanager_secret.cognito[0].arn, aws_secretsmanager_secret.llm[0].arn]
    }]
  })
}

# What the running app may do: the same permissions as the backend user in iam.tf, as a role.
resource "aws_iam_role" "task" {
  count              = local.compute
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task" {
  count  = local.compute
  name   = "backend-access"
  role   = aws_iam_role.task[0].id
  policy = aws_iam_user_policy.backend.policy
}

# ---------------------------------------------------------------------------
# Load balancer
# ---------------------------------------------------------------------------

resource "aws_lb" "api" {
  count                      = local.compute
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb[0].id]
  drop_invalid_header_fields = true
  idle_timeout               = 120 # LLM replies and ensemble inference can take a while
  enable_deletion_protection = var.deletion_protection
}

resource "aws_lb_target_group" "api" {
  count                = local.compute
  name                 = local.name
  port                 = local.port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main[0].id
  deregistration_delay = 30

  health_check {
    path                = "/healthz"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  count             = local.https && var.enable_compute ? 1 : 0
  load_balancer_arn = aws_lb.api[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}

# With a certificate, port 80 only redirects. Without one (dev) it serves the API directly.
resource "aws_lb_listener" "http" {
  count             = local.compute
  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = local.https ? "redirect" : "forward"
    target_group_arn = local.https ? null : aws_lb_target_group.api[0].arn

    dynamic "redirect" {
      for_each = local.https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

# ---------------------------------------------------------------------------
# WAF: per-IP rate limit and AWS managed rule sets in front of the ALB
# ---------------------------------------------------------------------------

resource "aws_wafv2_web_acl" "api" {
  count = local.compute
  name  = local.name
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "rate-limit-per-ip"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit_per_5min
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit-per-ip"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-common"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
        # Photo and audio uploads legitimately exceed the default 8 KB body rule.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-ip-reputation"
    priority = 3
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "api" {
  count        = local.compute
  resource_arn = aws_lb.api[0].arn
  web_acl_arn  = aws_wafv2_web_acl.api[0].arn
}

# ---------------------------------------------------------------------------
# ECS service
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  count = local.compute
  name  = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "api" {
  count                    = local.compute
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution[0].arn
  task_role_arn            = aws_iam_role.task[0].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = local.container
    image        = "${aws_ecr_repository.api[0].repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = local.port, protocol = "tcp" }]
    stopTimeout  = 30

    environment = [
      { name = "PORT", value = tostring(local.port) },
      { name = "AWS_REGION", value = var.region },
      { name = "DYNAMODB_TABLE_PREFIX", value = local.name },
      { name = "COGNITO_FARMER_POOL_ID", value = aws_cognito_user_pool.farmers.id },
      { name = "COGNITO_FARMER_CLIENT_ID", value = aws_cognito_user_pool_client.farmers_backend.id },
      { name = "COGNITO_ADMIN_POOL_ID", value = aws_cognito_user_pool.admins.id },
      { name = "COGNITO_ADMIN_CLIENT_ID", value = aws_cognito_user_pool_client.admins_backend.id },
      { name = "CORS_ORIGINS", value = var.cors_origins },
      { name = "MODEL_PATH", value = "/app/backend/models" },
      { name = "WEB_CONCURRENCY", value = "2" },
      { name = "AUTH_DISABLED", value = var.auth_disabled ? "1" : "0" },
    ]

    secrets = [
      { name = "COGNITO_FARMER_CLIENT_SECRET", valueFrom = "${aws_secretsmanager_secret.cognito[0].arn}:COGNITO_FARMER_CLIENT_SECRET::" },
      { name = "COGNITO_ADMIN_CLIENT_SECRET", valueFrom = "${aws_secretsmanager_secret.cognito[0].arn}:COGNITO_ADMIN_CLIENT_SECRET::" },
      { name = "SAMBANOVA_API_KEY", valueFrom = "${aws_secretsmanager_secret.llm[0].arn}:SAMBANOVA_API_KEY::" },
      { name = "GEMINI_API_KEY", valueFrom = "${aws_secretsmanager_secret.llm[0].arn}:GEMINI_API_KEY::" },
      { name = "BHASHINI_API_KEY", valueFrom = "${aws_secretsmanager_secret.llm[0].arn}:BHASHINI_API_KEY::" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api[0].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  count                              = local.compute
  name                               = "api"
  cluster                            = aws_ecs_cluster.main[0].id
  task_definition                    = aws_ecs_task_definition.api[0].arn
  desired_count                      = var.min_tasks
  launch_type                        = "FARGATE"
  health_check_grace_period_seconds  = 120 # TensorFlow import + model load
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks[0].id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api[0].arn
    container_name   = local.container
    container_port   = local.port
  }

  lifecycle {
    # Autoscaling owns the count; CI (.github/workflows/deploy.yml) owns the task definition revision.
    ignore_changes = [desired_count, task_definition]
  }

  depends_on = [aws_lb_listener.http]
}

# ---------------------------------------------------------------------------
# Autoscaling: CPU (inference is CPU-bound) and requests per task
# ---------------------------------------------------------------------------

resource "aws_appautoscaling_target" "api" {
  count              = local.compute
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.main[0].name}/${aws_ecs_service.api[0].name}"
  min_capacity       = var.min_tasks
  max_capacity       = var.max_tasks
}

resource "aws_appautoscaling_policy" "cpu" {
  count              = local.compute
  name               = "${local.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api[0].service_namespace
  scalable_dimension = aws_appautoscaling_target.api[0].scalable_dimension
  resource_id        = aws_appautoscaling_target.api[0].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 55
    scale_out_cooldown = 60
    scale_in_cooldown  = 300
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "requests" {
  count              = local.compute
  name               = "${local.name}-requests"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api[0].service_namespace
  scalable_dimension = aws_appautoscaling_target.api[0].scalable_dimension
  resource_id        = aws_appautoscaling_target.api[0].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 300
    scale_out_cooldown = 60
    scale_in_cooldown  = 300
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.api[0].arn_suffix}/${aws_lb_target_group.api[0].arn_suffix}"
    }
  }
}

# ---------------------------------------------------------------------------
# Alarms -> email (admin_email must confirm the SNS subscription)
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  count = local.compute
  name  = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = local.compute
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.admin_email
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  count               = local.compute
  alarm_name          = "${local.name}-alb-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.api[0].arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  count               = local.compute
  alarm_name          = "${local.name}-unhealthy-hosts"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.api[0].arn_suffix, TargetGroup = aws_lb_target_group.api[0].arn_suffix }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "latency_p95" {
  count               = local.compute
  alarm_name          = "${local.name}-latency-p95"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = aws_lb.api[0].arn_suffix }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  threshold           = 8
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  count               = local.compute
  alarm_name          = "${local.name}-cpu-high"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = { ClusterName = aws_ecs_cluster.main[0].name, ServiceName = aws_ecs_service.api[0].name }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
}
