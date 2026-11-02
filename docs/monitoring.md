# Monitoring

This page explains how the services are monitored and scaled on the online cluster (OVH). Monitoring runs in the `team1` namespace, next to the app.

## 1. Overview

```
                      Browser
                         │  http://team1.laboinfo-ecam.be/grafana
┌─ namespace team1 ──────▼──────────────────────────────────────────┐
│                                                                   │
│   Grafana (dashboard, read-only)                                  │
│      │  PromQL queries                                            │
│      ▼                                                            │
│   Prometheus (collects metrics every 15 s)                        │
│      │  GET /metrics on each pod                                  │
│      ▼                                                            │
│   photo-service-prod (3 pods)      photo-service-test (3 pods)    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

- **The app** exposes its own metrics on `/metrics`: number of requests, response codes, response times;
- **Prometheus** finds every pod of the app and collects these metrics every 15 seconds;
- **Grafana** queries Prometheus and displays the results on a public, read-only dashboard;
- **Scaling** is done from a separate tool (Headlamp or `kubectl`), and its effect is visible on the dashboard.

| What | Where |
|---|---|
| App (prod) | http://team1.laboinfo-ecam.be |
| Dashboard | http://team1.laboinfo-ecam.be/grafana |
| Prometheus | internal only (`http://prometheus:9090` inside the cluster) |

## 2. Application metrics

The app uses the library `prometheus-flask-exporter`. Two lines in `app.py` are enough:

```python
from prometheus_flask_exporter import PrometheusMetrics
metrics = PrometheusMetrics(app)
```

This adds a `/metrics` route and measures **every request** automatically, without changing the existing routes. The main metrics are:

| Metric | Type | Meaning |
|---|---|---|
| `flask_http_request_total` | counter | total number of requests, by method and status code |
| `flask_http_request_duration_seconds` | histogram | duration of the requests, by path, method and status code |

- A **counter** only goes up; Grafana turns it into a rate (requests per second) with `rate()`;
- A **histogram** sorts the requests into duration buckets (`le` = "less than or equal to"); it is used to compute percentiles such as the p95 latency;
- `/metrics` does not count itself, so the collection by Prometheus does not distort the numbers.

### Why gunicorn runs with 1 worker

Each gunicorn worker is a separate process with **its own counters**. With 2 workers, each call to `/metrics` would land on one of them at random, and the numbers would jump back and forth. The container therefore runs **1 worker and 1 thread**: to handle more traffic, we add **pods**, not workers. This is the usual approach on Kubernetes (one process per container), and it makes scaling easy to read: 3 pods handle 3 requests at a time, 5 pods handle 5.

Trade-offs to keep in mind:

- With 1 thread, gunicorn uses its `sync` worker: a slow request blocks the whole pod, including its health probes;
- When the app handles slow operations (photo uploads), a few threads per worker may be needed.

### Check

```bash
curl -s http://team1.laboinfo-ecam.be/metrics | grep flask_http_request_total
```

The `/health` route is also counted, because the readiness and liveness probes call it every few seconds. The dashboard filters it out (see section 5).

## 3. Prometheus

Prometheus runs as a Deployment in `team1` (1 pod, image `prom/prometheus`), behind a ClusterIP Service on port `9090`. It is **not exposed** outside the cluster: it has no authentication, and only Grafana needs to reach it.

### Finding the pods: DNS discovery

Prometheus must collect `/metrics` on **each pod** separately. The normal Service is not enough: it load-balances, so each collection would reach a random pod.

On a cluster with full rights, Prometheus asks the Kubernetes API for the list of pods. Our account cannot give it those rights, so it uses **DNS** instead:

- The base contains a **headless Service** (`clusterIP: None`): it has no virtual IP, and its DNS name returns **the IP of every pod** it selects;
- Each environment gets its own one (`photo-service-headless-prod`, `photo-service-headless-test`), with the `env` label in its selector;
- Prometheus resolves these names every few seconds: when a pod is added or removed (scaling, rolling update), it is discovered **automatically**.

```yaml
scrape_configs:
  - job_name: photo-service-prod
    dns_sd_configs:
      - names:
          - photo-service-headless-prod.team1.svc.cluster.local
        type: A
        port: 8080
```

The full DNS name (`<service>.<namespace>.svc.cluster.local`) is used on purpose: short names depend on how each tool handles DNS search domains, which is not consistent.

### Configuration through a Secret

`prometheus.yml` would normally be stored in a ConfigMap, but our account cannot create ConfigMaps. It is stored in a **Secret** instead, generated by Kustomize and mounted in `/etc/prometheus`:

```yaml
secretGenerator:
  - name: prometheus-config
    files:
      - prometheus.yml
generatorOptions:
  disableNameSuffixHash: true
```

- `disableNameSuffixHash`: by default, Kustomize adds a hash to the name and creates a new Secret at each change. Our account cannot delete Secrets, so they would pile up;
- The file contains no sensitive data: the Secret is only a way to deliver it.

Prometheus does **not** reload its configuration on its own. After changing `prometheus.yml`:

```bash
kubectl --context team1@cluster-sc apply -k manifests/monitoring
kubectl --context team1@cluster-sc rollout restart deployment/prometheus
```

### Check

From inside the cluster, with a throwaway pod (port-forward is not allowed on this cluster):

```bash
kubectl --context team1@cluster-sc run curl-test --image=curlimages/curl --restart=Never -- curl -s http://prometheus:9090/api/v1/targets
kubectl --context team1@cluster-sc logs curl-test | grep -o '"health":"[a-z]*"' | sort | uniq -c
kubectl --context team1@cluster-sc delete pod curl-test
```

Expected: one `"health":"up"` per app pod (6 with 3 pods in prod and 3 in test). Wait for the pod to be `Completed` before reading its logs.

## 4. Grafana

Grafana runs as a Deployment in `team1` (1 pod, image `grafana/grafana`), behind a ClusterIP Service on port `3000`. It is exposed at `/grafana` through its own HTTPRoute, attached to the same Gateway as the app.

### Sharing the domain with the app

The app and Grafana use the same domain, `team1.laboinfo-ecam.be`, with two HTTPRoutes:

| HTTPRoute | Path | Backend |
|---|---|---|
| `team1-routes-prod` | `/` | `photo-service-prod:8080` |
| `grafana-route` | `/grafana` | `grafana:3000` |

When several rules match a URL, the Gateway API picks the **longest prefix**: `/grafana/...` goes to Grafana, everything else goes to the app. Grafana is told it lives under `/grafana` (`GF_SERVER_ROOT_URL` and `GF_SERVER_SERVE_FROM_SUB_PATH`), so no URL rewrite is needed.

### Configuration as code (provisioning)

Grafana has no persistent disk (our account cannot create PersistentVolumeClaims): its internal database lives in an `emptyDir` and is **lost at every restart**. Everything it needs is therefore described in files stored in Git, and loaded at startup:

| File | Secret | Mounted in | Role |
|---|---|---|---|
| `grafana-datasources.yaml` | `grafana-datasources` | `/etc/grafana/provisioning/datasources` | Prometheus as data source |
| `grafana-dashboard-provider.yaml` | `grafana-dashboard-provider` | `/etc/grafana/provisioning/dashboards` | where to find the dashboards |
| `grafana-dashboard-photo-service.json` | `grafana-dashboards` | `/etc/grafana/dashboards` | the dashboard itself |

- The data source has a fixed `uid` (`prometheus`): the dashboard refers to it by this identifier, which stays the same across restarts;
- Provisioned items **cannot be edited** in the interface: Git is the only source of truth (see section 8 to change the dashboard).

### Access and security

The dashboard is public and read-only:

| Variable | Value | Effect |
|---|---|---|
| `GF_AUTH_ANONYMOUS_ENABLED` | `true` | visitors can see the dashboards without an account |
| `GF_AUTH_ANONYMOUS_ORG_ROLE` | `Viewer` | ... but cannot change anything |
| `GF_AUTH_DISABLE_LOGIN_FORM` | `true` | no login form |
| `GF_AUTH_BASIC_ENABLED` | `false` | no login through the API either |

The Gateway only serves **HTTP**: a password sent to Grafana would travel in clear. With these settings, no password is ever sent over the network.

The admin password is stored in a Secret created **by hand** (`grafana-admin`), never in Git. The Deployment marks it `optional: true`, so Grafana starts even if this Secret does not exist (for example after the cluster is wiped).

### Startup time

On each start, Grafana rebuilds its internal database, which takes about **one minute** with its CPU limit. The liveness probe therefore waits 60 seconds before its first check; otherwise Kubernetes would restart Grafana in a loop before it is ready.

## 5. The dashboard

The dashboard **Photo Service** has 4 panels. It opens on the last 15 minutes and refreshes every 10 seconds.

| Panel | Type | Question it answers |
|---|---|---|
| Active pods | Stat | How many pods are running, per environment? |
| Requests per second | Time series | How much traffic does each environment receive? |
| Requests per pod (prod) | Time series | How is the traffic spread across the prod pods? |
| Latency p95 | Time series | How fast do the requests get an answer? |

Numbers (Stat) show the **current state**; curves (Time series) show **trends**.

### Active pods

```promql
sum by (job) (up)
```

- `up` is created by Prometheus itself for each target: `1` if the last collection worked, `0` otherwise;
- `sum by (job)` adds them up per environment.

When an environment is scaled, this number follows within 15 to 30 seconds (the time for Prometheus to discover the new pods and collect them).

### Requests per second

```promql
sum by (job) (rate(flask_http_request_duration_seconds_count{path!="/health"}[1m]))
```

- `flask_http_request_duration_seconds_count` counts the requests **with their path**, unlike `flask_http_request_total`;
- `{path!="/health"}` removes the calls made by the health probes, which would hide the real traffic;
- `rate(...[1m])` turns the counter into requests per second, averaged over the last minute. Curves therefore rise and fall over about one minute, not instantly.

An environment that never received real traffic has **no series at all**: it is missing from the panel, rather than shown at 0.

### Requests per pod (prod)

```promql
sum by (instance) (rate(flask_http_request_duration_seconds_count{path!="/health", job="photo-service-prod"}[1m]))
```

Same query, limited to prod and grouped by `instance` (the IP and port of each pod). It shows the **load balancing** done by the Service: with 3 pods, each one gets about a third of the traffic. When prod is scaled, new curves appear and each one goes down.

### Latency p95

```promql
histogram_quantile(0.95, sum by (le, job) (rate(flask_http_request_duration_seconds_bucket{path!="/health"}[5m])))
```

- `histogram_quantile(0.95, ...)`: 95% of the requests are faster than this value;
- `le` (the bucket boundaries) must be kept in `sum by`, otherwise the percentile cannot be computed;
- A 5-minute window is used, because a percentile needs more requests than a rate to be stable.

The p95 is used rather than the average: an average hides the slow requests, the p95 shows what the least lucky users experience.

Today the app answers in well under a millisecond. All requests fall into the smallest bucket (0 to 5 ms), and Prometheus assumes they are spread evenly inside it, so the panel shows a flat **4.75 ms**. This is the precision limit of the buckets, not the real latency; the panel becomes meaningful once the app does real work (storing photos, detecting duplicates). Without traffic, the panel is empty.

## 6. Scaling

Grafana only **shows**: it is read-only on purpose, so that a monitoring tool cannot change production. Scaling is done with a separate tool that uses our own kubeconfig.

### Why not from a dashboard inside the cluster?

A tool running **inside** the cluster would need its own rights on the Kubernetes API (a ServiceAccount and a Role). Our account cannot create them. Any scaling therefore goes through **our** kubeconfig, from our machine.

Our account is also not allowed to use the `deployments/scale` subresource, which `kubectl scale` relies on. Scaling is done by changing `spec.replicas` in the Deployment itself (`patch`), which is allowed and has exactly the same effect.

### With Headlamp (graphical)

[Headlamp](https://headlamp.dev) is a Kubernetes dashboard installed on the developer's machine. It reads `~/.kube/config` and only shows what the account is allowed to do.

1. Open Headlamp and select the cluster `team1@cluster-sc` (namespace `team1`);
2. *Workloads → Deployments*, then the Deployment to scale;
3. Click the **pencil** (edit), change `spec.replicas`, and apply.

Headlamp hides its *Scale* button, because our account cannot use the `scale` subresource; editing the YAML goes through `patch` instead.

The pages *Overview* and *Events* show permission errors: our account cannot see the nodes nor the events. This is expected.

### With kubectl

```bash
kubectl --context team1@cluster-sc patch deployment photo-service-prod -p '{"spec":{"replicas":5}}'
```

### What happens

1. Kubernetes creates the new pods;
2. They get an IP, and the headless Service adds them to its DNS answer;
3. Prometheus discovers them and starts collecting their metrics (within 15 to 30 seconds);
4. On the dashboard, *Active pods* goes from 3 to 5, and *Requests per pod* shows 5 curves sharing the same traffic.

To generate traffic during a demo:

```bash
./scripts/load.sh          # 300 requests, about 1 minute 30
./scripts/load.sh 1000     # 1000 requests, about 5 minutes
```

### Git stays the source of truth

Scaling from Headlamp or `kubectl` changes the **live object** in the cluster, not the files in Git. The two now differ (*configuration drift*): Git says 3, the cluster runs 5.

At the next `apply` (`scripts/deploy-online.sh`, or the pipeline), Kubernetes goes back to the value in Git.

| Need | Method | Lasts |
|---|---|---|
| Absorb a traffic peak now | Headlamp / `kubectl patch` | until the next deployment |
| Change the number of pods for good | change `replicas` in Git, commit, `apply` | permanent, versioned |

In companies, GitOps tools (Argo CD, Flux) go further: they watch the cluster and automatically undo any change that did not go through Git.

Automatic scaling (HorizontalPodAutoscaler) is not possible here: our account cannot create HPAs, and cannot read the CPU and memory metrics they rely on.

## 7. Constraints and limitations

The online cluster is shared: our account (`team1`) only has rights inside its own namespace. The monitoring stack was designed around these rights:

| Not allowed | Consequence | Workaround |
|---|---|---|
| ConfigMaps (the Role says `configmap`, singular) | no ConfigMap for config files | config files delivered as **Secrets** |
| PersistentVolumeClaims | no persistent disk | `emptyDir`; Grafana fully provisioned from Git |
| Metrics API (`metrics.k8s.io`) | no CPU / memory metrics | application metrics (requests, errors, latency) |
| ServiceAccounts, Roles | Prometheus cannot list pods through the API | discovery through a **headless Service** and DNS |
| `pods/portforward` | no direct access to internal Services | throwaway `curl` pod + `kubectl logs` |
| `deployments/scale` | no `kubectl scale`, no *Scale* button in Headlamp | scaling through `patch` on `spec.replicas` |
| HorizontalPodAutoscalers | no automatic scaling | manual scaling |
| Events, nodes | less information in `kubectl describe` and Headlamp | `kubectl logs`, `kubectl get pods` |
| Deleting Secrets | old Secrets would pile up | `disableNameSuffixHash: true` |

Rights can be checked at any time:

```bash
kubectl --context team1@cluster-sc auth can-i --list
kubectl --context team1@cluster-sc auth can-i create pods --subresource=portforward
```

For subresources, `--subresource` is required: `auth can-i create pods/portforward` checks a **pod named** `portforward`, and gives a wrong `yes`.

### Known limitations

- **Data loss on restart**: Prometheus keeps its data in an `emptyDir`. A restart or a move to another node starts the history from zero. Grafana loses nothing, since it is rebuilt from Git;
- **HTTP only**: the Gateway does not serve HTTPS for our domain. This is why Grafana has no login at all, and why test and dev are not exposed;
- **`/metrics` is public**: it is served by the prod pods, so it is reachable through the public route. It only contains request counters, but in a real company it would be blocked at the Gateway, since Prometheus reads it from inside the cluster;
- **Latency precision**: limited by the histogram buckets (see section 5);
- **Grafana dashboard format**: the dashboard uses the new v2 format (needed for the auto grid layout). At startup, Grafana 13.3.0 logs an internal error about `managedFields` for this dashboard (`[SHOULD NOT HAPPEN]`). The dashboard loads and works normally; the error comes from Grafana's own handling of the v2 format.

## 8. Editing the dashboard

The dashboard is stored in Git (`manifests/monitoring/grafana-dashboard-photo-service.json`) and cannot be changed in the interface. Small changes (a title, a query, the default time range in `timeSettings`) can be made **directly in the JSON file**. For bigger changes, it is easier to use the editor of Grafana, then export the result.

### 1. Open the login temporarily

The admin password must exist in the cluster. If needed, create it (it never goes into Git):

```bash
GRAFANA_PASSWORD="$(openssl rand -base64 24)"
kubectl --context team1@cluster-sc create secret generic grafana-admin \
  --from-literal=admin-password="$GRAFANA_PASSWORD" \
  --dry-run=client -o yaml | kubectl --context team1@cluster-sc apply -f -
echo -n "$GRAFANA_PASSWORD" | pbcopy    # copied to the clipboard, store it in a password manager
unset GRAFANA_PASSWORD
```

In `grafana-deployment.yaml`, set `GF_AUTH_DISABLE_LOGIN_FORM` to `"false"`, then:

```bash
kubectl --context team1@cluster-sc apply -k manifests/monitoring
kubectl --context team1@cluster-sc rollout status deployment/grafana --timeout=300s
```

Log in as `admin`. While the login is open, the password travels over HTTP: keep this window short.

### 2. Change and export

1. Open the dashboard, click *Edit*, make the changes;
2. The dashboard cannot be saved (it is provisioned): use *Export → Export as JSON* instead, with **"export for sharing externally" disabled**, so that the panels keep referring to the data source by its `uid` (`prometheus`);
3. In the exported file, keep only `"name"` in `metadata`: the other fields (timestamps, user IDs, versions) belong to this Grafana instance and change at every save;
4. Replace the file in the repository, and check that it is valid JSON:

```bash
python3 -m json.tool manifests/monitoring/grafana-dashboard-photo-service.json > /dev/null && echo "valid JSON"
```

### 3. Lock again and deploy

Set `GF_AUTH_DISABLE_LOGIN_FORM` back to `"true"`, then:

```bash
kubectl --context team1@cluster-sc apply -k manifests/monitoring
kubectl --context team1@cluster-sc rollout status deployment/grafana --timeout=300s
```

Grafana restarts, rebuilds its database and loads the new dashboard from the file. Commit the JSON and the Deployment together.