# OpenClaw Operator Module

This module deploys the OpenClaw Kubernetes Operator to your cluster.

## What is OpenClaw?

OpenClaw is a Kubernetes operator for running Claude AI agents in your cluster. The operator manages OpenClawInstance resources, which represent individual Claude agents.

## Deployment

To deploy the OpenClaw operator:

```bash
cd IaC/production/homelab/openclaw
terragrunt apply
```

## Post-Deployment Steps

After deploying the operator, you need to:

1. Set the Anthropic API key in AWS SSM Parameter Store:
```bash
aws ssm put-parameter \
  --name "/homelab/openclaw-operator-system/anthropic_api_key" \
  --type "SecureString" \
  --value "sk-ant-your-api-key-here" \
  --overwrite
```

The External Secrets Operator will automatically sync this to a Kubernetes secret named `openclaw-api-keys` in the `openclaw-operator-system` namespace.

2. Deploy an OpenClawInstance:
```bash
kubectl apply -f IaC/modules/openclaw/example-instance.yaml
```

3. Verify the deployment:
```bash
# Check that the secret was created
kubectl get secret openclaw-api-keys -n openclaw-operator-system

# Check OpenClaw instances
kubectl get openclawinstances -n openclaw-operator-system

# Check pods
kubectl get pods -n openclaw-operator-system
```

## Configuration

The operator is deployed with default settings. To customize the deployment, you can add values to the `helm_release` resource in `main.tf`.

## References

- [OpenClaw GitHub Repository](https://github.com/openclaw-rocks/k8s-operator)
- [OpenClaw Documentation](https://openclaw.rocks)
