output "bucket_name" {
  value = aws_s3_bucket.langfuse.id
}

output "region" {
  value = var.aws_region
}
