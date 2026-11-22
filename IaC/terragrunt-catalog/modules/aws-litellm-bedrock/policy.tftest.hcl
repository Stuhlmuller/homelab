mock_provider "aws" {}

override_data {
  target = data.aws_bedrock_foundation_model_agreement_offers.sol
  values = {
    offers = [{
      offer_id     = "fixture-offer"
      offer_token  = "mock"
      term_details = []
    }]
  }
}

run "restrict_gateway_to_declared_chat_models" {
  command = plan

  assert {
    condition = (
      aws_bedrock_foundation_model_agreement.sol.model_id == "openai.gpt-6.2-sol" &&
      data.aws_bedrock_foundation_model_agreement_offers.sol.offer_type == "PUBLIC"
    )
    error_message = "Only the public GPT-6.2 Sol offer may be accepted."
  }

  assert {
    condition = (
      length(jsondecode(aws_iam_user_policy.gateway.policy).Statement) == 5 &&
      toset(jsondecode(aws_iam_user_policy.gateway.policy).Statement[0].Resource) == toset([
        "arn:aws:bedrock:us-west-2:716182248480:inference-profile/us.amazon.nova-lite-v1:0",
        "arn:aws:bedrock:us-west-2:716182248480:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:us-west-2:716182248480:inference-profile/us.openai.gpt-6.2-sol",
      ]) &&
      toset(jsondecode(aws_iam_user_policy.gateway.policy).Statement[4].Resource) ==
      toset(["arn:aws:bedrock:us-west-2::foundation-model/deepseek.v3.2"]) &&
      alltrue([
        for statement in jsondecode(aws_iam_user_policy.gateway.policy).Statement :
        statement.Effect == "Allow" &&
        toset(statement.Action) == toset(["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]) &&
        alltrue([
          for resource in statement.Resource :
          contains(jsondecode(aws_iam_user_policy.gateway.policy).Statement[0].Resource, resource) ||
          resource == "arn:aws:bedrock:us-west-2::foundation-model/deepseek.v3.2" ||
          (
            can(regex("^arn:aws:bedrock:us-(east-[12]|west-2)::foundation-model/", resource)) &&
            contains(jsondecode(aws_iam_user_policy.gateway.policy).Statement[0].Resource,
            try(statement.Condition.StringEquals["bedrock:InferenceProfileArn"], "")) &&
            try(statement.Condition.StringEquals["bedrock:InferenceProfileArn"], "") ==
            "arn:aws:bedrock:us-west-2:716182248480:inference-profile/us.${element(split("/", resource), 1)}"
          )
        ])
      ])
    )
    error_message = "Only the declared US profiles and Oregon's DeepSeek V3.2 model may be invoked."
  }
}
