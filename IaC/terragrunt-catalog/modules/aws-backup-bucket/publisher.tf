resource "aws_iam_policy" "publisher_boundary" {
  count       = var.publisher == null ? 0 : 1
  name        = "${var.publisher.role_name}-boundary"
  description = "Limits Enterprise recovery publication to its own versioned S3 prefix."
  policy      = local.publisher_policy
  tags        = var.tags
}

resource "aws_iam_role" "publisher" {
  count = var.publisher == null ? 0 : 1
  name  = var.publisher.role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRoleWithWebIdentity"
      # The CI plan role cannot enumerate IAM providers; the owner account is checked above.
      Principal = { Federated = "arn:aws:iam::${var.expected_account_id}:oidc-provider/token.actions.githubusercontent.com" }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub"           = var.publisher.subject
          "token.actions.githubusercontent.com:workflow"      = var.publisher.workflow
          "token.actions.githubusercontent.com:ref"           = var.publisher.ref
          "token.actions.githubusercontent.com:repository_id" = tostring(var.publisher.repository_id)
        }
      }
    }]
  })
  permissions_boundary = aws_iam_policy.publisher_boundary[0].arn
  max_session_duration = 3600
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "publisher" {
  count  = var.publisher == null ? 0 : 1
  name   = "prefix-only-recovery-publication"
  role   = aws_iam_role.publisher[0].id
  policy = local.publisher_policy
}
