# Alarms that page a human (gameplan 9.2). Dashboards live in Grafana Cloud (9.1); these
# are the few things that should reach you when you aren't looking at a dashboard.
#
# Split by source: AWS publishes the EC2/RDS metrics for free, while disk, uptime and
# certificate expiry aren't AWS-visible at all, so the box publishes them itself
# (putyouon-metrics.timer, in user-data.sh).

resource "aws_sns_topic" "alerts" {
  name = "putyouon-alerts"
}

# AWS emails a confirmation link; alerts don't flow until it's clicked. Terraform shows
# this subscription as "pending confirmation" until then, which is expected.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "bframoslopez@gmail.com"
}

# The instance publishes the custom metrics below. Scoped to this namespace so a
# compromised box can't write into anyone else's.
resource "aws_iam_policy" "instance_put_metrics" {
  name        = "putyouon-ec2-put-metrics"
  description = "Publish putyouon/instance custom metrics to CloudWatch"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "cloudwatch:PutMetricData"
      Resource = "*" # PutMetricData takes no resource ARNs; the namespace condition is the scope
      Condition = {
        StringEquals = { "cloudwatch:namespace" = "putyouon/instance" }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "instance_put_metrics" {
  role       = data.aws_iam_instance_profile.app.role_name
  policy_arn = aws_iam_policy.instance_put_metrics.arn
}

locals {
  # Every alarm notifies, and also tells you when it recovers.
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# --- AWS-published metrics -----------------------------------------------------------

# Failing status checks = the instance or its host is broken. AWS retires/reboots on some
# of these, but you want to know either way.
resource "aws_cloudwatch_metric_alarm" "ec2_status_check" {
  alarm_name          = "putyouon-ec2-status-check-failed"
  alarm_description   = "EC2 status check failing: instance or underlying host is unhealthy."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { InstanceId = aws_instance.app.id }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# 30 GB allocated and no storage autoscaling, so a full disk means a dead database.
# 3 GB gives room to react (scale storage) before writes start failing.
resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "putyouon-rds-free-storage-low"
  alarm_description   = "RDS free storage below 3 GB. Increase allocated_storage in infra/rds.tf."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 3 * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# db.t4g.micro's default max_connections works out to roughly 112. Connection exhaustion
# is one of the two classic ways this class of app falls over (9.2).
resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "putyouon-rds-connections-high"
  alarm_description   = "RDS connections above 80 (max ~112). Check for leaked sessions or pool size."
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# RDS T-class instances always run in unlimited mode (6.5): a credit balance at zero means
# sustained CPU is being billed as surplus, not throttled. This is a cost alarm.
resource "aws_cloudwatch_metric_alarm" "rds_cpu_credits" {
  alarm_name          = "putyouon-rds-cpu-credits-low"
  alarm_description   = "RDS CPU credit balance low: sustained load is being billed as surplus credits."
  namespace           = "AWS/RDS"
  metric_name         = "CPUCreditBalance"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 3
  threshold           = 30
  comparison_operator = "LessThanThreshold"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# --- Metrics the box publishes about itself ------------------------------------------

# The site answering over TLS is the only check that covers the whole path (nginx, the
# frontend, the backend and the certificate). treat_missing_data = breaching is the
# important part: if the instance dies, no metric arrives and this still fires.
resource "aws_cloudwatch_metric_alarm" "site_down" {
  alarm_name          = "putyouon-site-down"
  alarm_description   = "https://putyouon.app/health is not returning 200, or the instance stopped reporting."
  namespace           = "putyouon/instance"
  metric_name         = "SiteUp"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# Renewal runs from day 60. 20 days left means it has failed ~10 times: enough warning to
# fix it by hand before the site starts serving an expired certificate (7.2).
resource "aws_cloudwatch_metric_alarm" "cert_expiring" {
  alarm_name          = "putyouon-cert-expiring"
  alarm_description   = "TLS certificate expires in under 20 days: certbot renewal is failing."
  namespace           = "putyouon/instance"
  metric_name         = "CertDaysRemaining"
  statistic           = "Minimum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 20
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching" # the site-down alarm already covers a silent box
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# EC2 disk usage is not a native CloudWatch metric, which is why the box reports it. On a
# 12 GB volume, 80% leaves ~2.4 GB: enough for one more image pull while you clean up.
resource "aws_cloudwatch_metric_alarm" "disk_high" {
  alarm_name          = "putyouon-disk-high"
  alarm_description   = "Root volume over 80% full. Check image buildup (docker image prune -af) and logs."
  namespace           = "putyouon/instance"
  metric_name         = "DiskUsedPercent"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}
