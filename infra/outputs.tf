output "instance_id" {
  description = "For SSM: aws ssm start-session --target <this>"
  value       = aws_instance.app.id
}

output "elastic_ip" {
  description = "Point the Porkbun A record for putyouon.app here (6.4)"
  value       = aws_eip.app.public_ip
}

output "db_endpoint" {
  description = "New value for SSM /putyouon/prod/POSTGRES_HOST (6.5)"
  value       = aws_db_instance.main.address
}
