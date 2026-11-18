output "bucket_name" {
  value = aws_s3_bucket.backup.id
}

output "bucket_arn" {
  value = aws_s3_bucket.backup.arn
}

output "region" {
  value = var.aws_region
}

output "publisher_role_arn" {
  value = var.publisher == null ? null : aws_iam_role.publisher[0].arn
}
