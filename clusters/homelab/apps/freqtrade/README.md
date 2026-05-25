# Freqtrade

Freqtrade runs the homelab Bitcoin trading bot. It is installed in dry-run mode
by default so it can exercise live market data, persistence, and FreqUI without
placing real orders.

This is automation infrastructure, not a profit guarantee. A strategy must be
backtested, dry-run for long enough to cover different market regimes, reviewed
for exchange fees and tax consequences, and only then promoted with a separate
repository change.

## Runtime Contract

- Namespace: `finance`
- Tailnet host: `https://freqtrade.stinkyboi.com`
- Exchange market data: Kraken `BTC/USD`
- Mode: spot, dry-run
- Stake model: at most one simulated `100 USD` trade at a time
- Persistent state: `freqtrade` PVC on `nfs-default`
- Strategy: `HomelabBtcTrend`, mounted from repository-owned Python code

The API username is `freqtrader`. The password, JWT secret, and websocket token
come from AWS SSM Parameter Store through the `freqtrade-api` ExternalSecret.

## SSM Parameters

`IaC/live/aws-ssm-parameters` creates generated values for:

- `/homelab/freqtrade/api-password`
- `/homelab/freqtrade/jwt-secret-key`
- `/homelab/freqtrade/ws-token`

Read the API password when you need to sign in:

```sh
aws ssm get-parameter \
  --name /homelab/freqtrade/api-password \
  --with-decryption \
  --query Parameter.Value \
  --output text
```

## Validation

Render the repository-owned manifests:

```sh
kubectl kustomize clusters/homelab/apps/freqtrade
```

Render the Helm release:

```sh
helm template freqtrade app-template \
  --repo https://bjw-s-labs.github.io/helm-charts \
  --version 4.4.0 \
  --namespace finance \
  --values clusters/homelab/apps/freqtrade/values.yaml
```

After Argo CD syncs the app:

```sh
kubectl -n finance get externalsecret freqtrade-api
kubectl -n finance get deploy,pod,svc,pvc -l app.kubernetes.io/instance=freqtrade
kubectl -n finance logs deploy/freqtrade -c app --tail=100
```

Expected result: `freqtrade-api` is ready, the deployment has one available
pod, the PVC is bound, and logs show dry-run trading against `BTC/USD`.

## Promotion To Live Trading

Live trading must be a separate PR. Do not switch this app live by editing the
cluster or UI. The PR should:

1. Add ExternalSecret-backed exchange API credentials with withdrawal disabled
   at the exchange.
2. Change `dry_run` to `false` in `config.json`.
3. Keep an explicit stake cap and stop-loss.
4. Include backtest and dry-run evidence for the exact strategy revision.
5. Document rollback: set `dry_run` back to `true`, sync Argo CD, and verify no
   open orders remain at the exchange.
