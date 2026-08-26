# Grafana Alert Cleanup

The one-shot cleanup is retired. This empty source keeps its Argo CD
Application registered for one final sync so pruning removes the retirement
marker before the Application is deleted.
