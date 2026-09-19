# The production database (gameplan 6.5), restored from the final snapshot taken when
# put-you-on-instance-2 was deleted on 2026-09-08. The restore keeps the snapshot's master
# user and password (so SSM POSTGRES_USER/PASSWORD still match), its data, and its KMS
# key. Only POSTGRES_HOST changes: point SSM at the `db_endpoint` output after apply.

resource "aws_security_group" "db" {
  name        = "putyouon-db"
  description = "putyouon RDS: Postgres from the app host only"
  vpc_id      = data.aws_vpc.default.id
}

# By security-group reference, not IP: only instances in putyouon-app get in.
resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_instance" "main" {
  identifier          = "putyouon-db"
  snapshot_identifier = "final-put-you-on-instance-2e36d4fe0-ae3a-457a-9e19-36cd188f6067"

  # 1 GB RAM. The 1280-dim embeddings (~560 MB raw) won't stay cached, so kNN reads hit
  # disk until the HNSW index exists (10.2). Move to db.t4g.small if latency is bad.
  instance_class = "db.t4g.micro"

  # The snapshot's 30 GB is the floor; a restore can't shrink it.
  allocated_storage = 30
  storage_type      = "gp3"
  # Inherited from the (encrypted) snapshot, but must be declared: left unset, the
  # provider reads it as false and plans a destroy-and-recreate to "unencrypt" it.
  storage_encrypted = true

  availability_zone      = local.az
  db_subnet_group_name   = "default-${data.aws_vpc.default.id}"
  vpc_security_group_ids = [aws_security_group.db.id]

  # The deleted instance was public. This one is reachable only through the app host
  # (SSM shell or SSM port forwarding from a laptop).
  publicly_accessible = false
  multi_az            = false

  backup_retention_period    = 7
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true

  # Three layers against deleting the only copy of the data: AWS refuses the delete,
  # a delete would still take a final snapshot, and Terraform refuses to plan a destroy.
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "putyouon-db-final"

  lifecycle {
    prevent_destroy = true
    # Only meaningful at creation; don't let it drive a replacement later.
    ignore_changes = [snapshot_identifier]
  }
}
