# The app host (gameplan 6.1-6.4): one EC2 instance in the default VPC, its security
# group, and a stable Elastic IP. The database is in rds.tf.

# --- Read-only lookups. Terraform reads these but never changes them. ---------------

data "aws_vpc" "default" {
  default = true
}

# One subnet, pinned to the same AZ as the database (rds.tf) so app-to-DB traffic isn't
# billed as cross-AZ.
data "aws_subnet" "app" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = local.az
  default_for_az    = true
}

# Latest Amazon Linux 2023 x86_64 (x86 because essentia-tensorflow only ships amd64
# wheels, 0.2). AL2023 comes with the SSM agent, which is the only way in (no SSH).
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
}

# Created by hand in Phase 0 (0.4): SSM core + ECR pull + /putyouon/prod SSM read.
data "aws_iam_instance_profile" "app" {
  name = "putyouon-ec2-instance-role"
}

locals {
  az = "us-east-1a"
}

# --- Security group (6.2) -------------------------------------------------------------

resource "aws_security_group" "app" {
  name        = "putyouon-app"
  description = "putyouon app host: HTTP/HTTPS in, no SSH (shell is via SSM)"
  vpc_id      = data.aws_vpc.default.id
}

# 80 is needed for the ACME HTTP-01 challenge and the HTTPS redirect (Phase 4/7).
# IPv4 only: the box has no IPv6, and a stray AAAA record breaks Certbot (6.4).
resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# The SSM agent, ECR pulls, Docker/Compose downloads, Let's Encrypt and the RDS
# connection are all outbound.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# --- Instance (6.1, 6.3) --------------------------------------------------------------

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = "t3.small" # 2 GB. Resize = stop, change type, start.
  subnet_id              = data.aws_subnet.app.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = data.aws_iam_instance_profile.app.name

  # First-boot setup: Docker, Compose plugin, swap, certbot webroot (6.3).
  user_data = file("${path.module}/user-data.sh")

  # 12 GB: ~8.5 GB peak (OS + Docker ~2, two image versions mid-deploy ~3.8, swap 2,
  # logs ~0.5). gp3 grows online if that turns out tight.
  root_block_device {
    volume_type = "gp3"
    volume_size = 12
    encrypted   = true
  }

  # IMDSv2 only; hop limit 1 keeps containers (one extra network hop away) from
  # reading the instance role's credentials.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # A sustained CPU burst (embedding) throttles to baseline instead of adding
  # "unlimited" surplus charges.
  credit_specification {
    cpu_credits = "standard"
  }

  tags = {
    Name = "putyouon-app"
  }

  lifecycle {
    # The AMI parameter moves every AL2023 release. Without this, the next plan after a
    # release would replace (destroy and recreate) the running instance. Patch in place
    # with dnf instead; pick up a new AMI deliberately.
    # user_data only runs on first boot, so an edit to it shouldn't touch a running box.
    ignore_changes = [ami, user_data]
  }
}

# --- Elastic IP (6.4) -----------------------------------------------------------------

# A stable address for the Porkbun A record, OAuth redirects and Certbot. A plain
# public IP changes on every stop/start.
resource "aws_eip" "app" {
  domain = "vpc"

  tags = {
    Name = "putyouon-app"
  }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}
