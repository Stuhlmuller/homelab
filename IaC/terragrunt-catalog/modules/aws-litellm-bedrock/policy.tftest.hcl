mock_provider "aws" {}

run "restrict_gateway_to_us_inference_profiles" {
  command = plan

  assert {
    condition = (
      length(jsondecode(aws_iam_user_policy.gateway.policy).Statement) == 3 &&
      toset(jsondecode(aws_iam_user_policy.gateway.policy).Statement[0].Resource) == toset([
        "arn:aws:bedrock:us-west-2:716182248480:inference-profile/us.amazon.nova-lite-v1:0",
        "arn:aws:bedrock:us-west-2:716182248480:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      ]) &&
      alltrue([
        for statement in jsondecode(aws_iam_user_policy.gateway.policy).Statement :
        statement.Effect == "Allow" &&
        toset(statement.Action) == toset(["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]) &&
        alltrue([
          for resource in statement.Resource :
          contains(jsondecode(aws_iam_user_policy.gateway.policy).Statement[0].Resource, resource) ||
          (
            can(regex("^arn:aws:bedrock:us-(east-[12]|west-2)::foundation-model/", resource)) &&
            try(statement.Condition.StringEquals["bedrock:InferenceProfileArn"], "") ==
            "arn:aws:bedrock:us-west-2:716182248480:inference-profile/us.${element(split("/", resource), 1)}"
          )
        ])
      ])
    )
    error_message = "Only Oregon US inference profiles and their profile-conditioned foundation models may be invoked."
  }
}
