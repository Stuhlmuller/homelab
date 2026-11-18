resource "aws_iam_user" "langfuse" {
  # checkov:skip=CKV_AWS_273: Non-human S3 client with no console login; this Talos cluster has no workload IAM federation configured.
  name = "homelab-langfuse-s3"
  path = "/homelab/"
  tags = var.tags
}

data "aws_iam_policy_document" "langfuse" {
  statement {
    sid = "ListLangfuseBlobBucket"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [local.bucket_arn]
  }

  statement {
    sid = "WriteLangfuseBlobObjects"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = ["${local.bucket_arn}/*"]
  }
}

resource "aws_iam_user_policy" "langfuse" {
  # checkov:skip=CKV_AWS_40: One non-human client receives only the exact dedicated bucket permissions, avoiding a reusable broader group.
  name   = "langfuse-blob-storage"
  user   = aws_iam_user.langfuse.name
  policy = data.aws_iam_policy_document.langfuse.json
}

resource "aws_iam_access_key" "langfuse" {
  user = aws_iam_user.langfuse.name
}
