# Homepage

Homepage serves the homelab dashboard at `https://compass.stinkyboi.com`.
The Argo CD Application, Kubernetes Service and access routes retain the
`compass` identity so existing Octelium and Traefik clients can keep their
bookmarks. The workload is stateless.

Homepage lists opt-in Kubernetes Ingresses using its projected service account.
Add `gethomepage.dev/enabled: "true"` to an Ingress and use Homepage annotations
for its display name, group, icon and other metadata. The
`compass-discovery` IngressClass has no traffic controller. Its records in
`ingress-discovery.yaml` provide explicit HTTPS links for apps whose traffic
is routed by Istio or the Traefik file provider. They are marked external
because their Ingress records do not describe the apps' Kubernetes backends.

Use Terragrunt to switch the existing Argo CD Application from the Compass
chart to this directory. Argo CD waits for the Homepage Deployment to become
healthy before updating the shared Service, then prunes obsolete chart
resources. The previous Compass source remains available while the Application
update is pending and can be restored by reverting the stack change and
applying its reviewed plan.

After sync, verify the Service has a ready Homepage endpoint and open the
dashboard through the existing hostname. Confirm that the Argo CD and Grafana
cards display and open their established URLs.
