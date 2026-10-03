# Deploying Kisan Mitra on AWS

Production runs entirely on AWS, defined in `infra/` (Terraform) and shipped by
`.github/workflows/deploy.yml`.

```
Android app / web ─HTTPS─▶ WAF ─▶ ALB (2 AZs) ─▶ ECS Fargate tasks (private subnets, autoscaled)
                                                    ├─ DynamoDB      (users, diagnoses, stats, rate limits; PITR on)
                                                    ├─ Cognito       (farmer SMS-OTP pool, staff pool)
                                                    ├─ Secrets Manager (Cognito client secrets, LLM keys)
                                                    └─ LLM / Bhashini APIs via NAT
```

The API container is stateless, so capacity is just the number of tasks. Autoscaling adds
tasks on CPU (target 55%) and requests per task (target 300), between `min_tasks` and
`max_tasks`. Per-farmer limits (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_PER_DAY`) and a per-IP WAF
rule protect the paid LLM/SMS calls.

## 1. One-time setup

1. **Remote Terraform state.** Uncomment the `backend "s3"` block in `infra/versions.tf` and
   create that bucket first (versioned, encrypted, private). State holds secrets.
2. **Certificate.** Request an ACM certificate for your API domain in `ap-south-1` and validate it.
3. **Variables.** Copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars` and set at least:
   ```hcl
   environment         = "prod"
   admin_email         = "ops@yourdomain"
   acm_certificate_arn = "arn:aws:acm:ap-south-1:...:certificate/..."
   deletion_protection = true
   github_repo         = "owner/repo"
   ```
4. **Create the registry, push a first image, then the rest.** The service needs an image to start:
   ```bash
   cd infra && terraform init
   terraform apply -target=aws_ecr_repository.api
   aws ecr get-login-password | docker login --username AWS --password-stdin <ecr_repository_url>
   docker build -t <ecr_repository_url>:bootstrap .. && docker push <ecr_repository_url>:bootstrap
   terraform apply
   ```
5. **DNS.** Point your API domain (CNAME/alias) at the ALB (`terraform output api_url`).
6. **Secrets.** Put real provider keys in Secrets Manager (they never enter Terraform state):
   ```bash
   aws secretsmanager put-secret-value --secret-id kisan-mitra-prod/llm \
     --secret-string '{"SAMBANOVA_API_KEY":"...","GEMINI_API_KEY":"...","BHASHINI_API_KEY":"..."}'
   ```
7. **Rotate any key that was ever committed** (an earlier SambaNova key is in git history).
8. **GitHub.** Set repository variables `AWS_DEPLOY_ROLE_ARN` (`terraform output github_deploy_role_arn`)
   and `ENVIRONMENT` (`prod`). Confirm the SNS alert email subscription.
9. **SMS (India).** Register the OTP template on the DLT portal and raise
   `sms_monthly_spend_limit_usd` before launch.

## 2. Every release

Push to `phase-1-mvp`. The workflow builds the app and image, pushes `<sha>` to ECR, and rolls the
ECS service. Failed health checks roll back automatically (deployment circuit breaker).

## 3. Operating it

| Concern | Where |
|---|---|
| Logs | CloudWatch `/ecs/kisan-mitra-<env>` (30-day retention) |
| Alerts | SNS email: ALB 5xx, unhealthy targets, p95 latency, CPU |
| Backups | DynamoDB point-in-time recovery |
| Scale limits | `min_tasks` / `max_tasks` (also the bill ceiling) |
| Cost drivers | Fargate tasks, NAT gateways, SMS, LLM calls |

Before real launch traffic, load-test `/diagnose` (CPU-bound: expect roughly one image per second
per vCPU) and tune `task_cpu`, `max_tasks` and the autoscaling targets from the results.

## 4. Local development

`./start.sh` or `docker compose up` run the API against a dev AWS stack (`terraform output -raw
backend_env > .env`). Android testing: see `MOBILE.md`.
