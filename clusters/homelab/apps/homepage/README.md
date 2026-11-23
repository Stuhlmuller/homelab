# Homepage

Homepage serves the homelab dashboard at `https://compass.stinkyboi.com`.
The Argo CD Application, Kubernetes Service and access routes retain the
`compass` identity so existing Octelium and Traefik clients can keep their
bookmarks. The workload is stateless.

Homepage lists opt-in Kubernetes Ingresses using its projected service account.
Add `gethomepage.dev/enabled: "true"` to a Kubernetes Ingress you want to
discover. Use Homepage annotations for its display name, group and icon. Only
grant annotation write access to people trusted to configure Homepage widgets.

The existing Istio and Traefik file-provider apps are listed in
`config/services.yaml`. These links have no controller-managed Kubernetes
Ingress. Keeping them in Homepage config lets Argo CD complete the cutover
without waiting for status from a load balancer.

Use Terragrunt to switch the existing Argo CD Application from the Compass
chart to this directory. Argo CD waits for the Homepage Deployment to become
healthy before updating the shared Service, then prunes obsolete chart
resources. The previous Compass source remains available while the Application
update is pending and can be restored by reverting the stack change and
applying its reviewed plan.

After sync, verify the Service has a ready Homepage endpoint and open the
dashboard through the existing hostname. Confirm that the Argo CD and Grafana
cards display and open their established URLs.
