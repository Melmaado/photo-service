# Cluster Setup

This page explains how the Kubernetes clusters are built, from scratch, and how to move the project to a cloud cluster. It is done **once per cluster**. To work on the app day to day, see the *Onboarding* page.

The project runs on two clusters:

| Cluster | Environments | Managed by |
|---|---|---|
| Local (Docker Desktop) | dev | the developer |
| Online (OVH, shared) | test, prod, monitoring | the teacher (the team only has the namespace `team1`) |

## Local cluster

### Architecture

```
                 Browser / curl
                       | port 80
+- Cluster (Docker Desktop) ---------------------+
|                      v                         |
|  namespace ingress-nginx                       |
|    Ingress Controller (nginx, localhost)       |
|                      | dev.photo.localhost     |
|                      v                         |
|  namespace 21359-dev                           |
|    Ingress -> Service -> app (3 pods)          |
|                            |                   |
|          +-----------------+-------------+     |
|          v                 v             v     |
|      postgres       postgres-shard1    redis   |
|      (shard 0)      (shard 1)          (cache) |
|      2 pods         2 pods             2 pods  |
+------------------------------------------------+
```

- **One single Ingress controller** for the whole cluster: it is the only entry point from outside;
- The Services are **ClusterIP** or headless: they are only reachable from inside the cluster;
- dev is a complete copy of the online environments: 3 app pods, 2 PostgreSQL shards with one replica each, and Redis with one replica (9 pods).

### 1. Enable Kubernetes

1. Install Docker Desktop (see *Onboarding*);
2. In Docker Desktop, open *Settings → Kubernetes*, enable Kubernetes and apply;
3. Wait until *Kubernetes running* is displayed at the bottom of the window.

Check that `kubectl` points to this cluster:

```bash
kubectl config current-context    # must return docker-desktop
kubectl get nodes                 # one node, STATUS Ready
```

Always check the context before an `apply` or a `delete`: once several clusters are configured, a command sent to the wrong one can break it.

### 2. Install the Ingress controller

The controller is installed with Helm, the Kubernetes package manager: it is made of dozens of resources (Deployment, Services, access rights) that are not written by hand.

```bash
helm upgrade --install ingress-nginx ingress-nginx \
  --repo https://kubernetes.github.io/ingress-nginx \
  --namespace ingress-nginx --create-namespace
```

- `upgrade --install` installs it if missing and updates it otherwise, so the command can be run again safely;
- it lives in its **own namespace**, `ingress-nginx`, because it is shared by all environments.

Check:

```bash
kubectl get pods -n ingress-nginx       # the controller pod is Running
kubectl get service -n ingress-nginx    # ingress-nginx-controller: LoadBalancer, EXTERNAL-IP localhost
curl -i http://localhost                # 404 from nginx: the controller answers, no rule matches yet
```

On Docker Desktop, the `LoadBalancer` Service is published directly on `localhost`, on ports 80 (HTTP) and 443 (HTTPS).

nginx refuses requests bigger than 1 MB by default, which blocks most photo uploads. The Ingress of the project raises this limit with the annotation `nginx.ingress.kubernetes.io/proxy-body-size: "20m"`.

> **Note:** the community project ingress-nginx was retired by Kubernetes in March 2026: it still works, but no longer receives updates or security fixes. It is used here for its simplicity and its documentation. For production, a maintained alternative should be preferred (NGINX Ingress Controller by F5, Traefik, or the Gateway API, like the online cluster). Only the `ingressClassName` field of the Ingress resources would change.

### 3. Create the namespace

```bash
kubectl apply -f manifests/namespaces.yaml
kubectl get namespaces
```

The namespace `21359-dev` is prefixed with the student ID, so it never collides with other students' namespaces on a shared cluster. It is kept outside Kustomize: a namespace does not belong to a namespace.

### 4. Deploy dev

dev is deployed by the CI (job `deploy-dev`) on every push to `dev` or `main`. See the *CI/CD* page. It can also be deployed by hand:

```bash
kubectl apply -k manifests/overlays/dev --context docker-desktop
```

The `dev` overlay adds the Ingress from `manifests/local-ingress/`, which is not part of the base because the online cluster uses the Gateway API instead. It also generates the Secret `photo-secrets` with fixed local values: they only protect a local database, so they can be in Git.

The image comes from GHCR, like online. The image tag committed in the overlay may be old: the CI sets the right one at each deployment.

Check:

```bash
kubectl get pods -n 21359-dev                # 9 pods Running
kubectl get ingress -n 21359-dev             # dev.photo.localhost
curl http://dev.photo.localhost/health
```

### 5. Set up the CI runner

The deployment jobs of the CI run on a **self-hosted runner** installed on the developer's Mac: GitHub's machines cannot reach the local cluster, and the credentials of the online cluster must not leave the Mac. This is done once, on that machine only.

1. On GitHub: *Settings → Actions → Runners → New self-hosted runner*, then choose **macOS** and the right architecture (**ARM64** for an Apple chip);
2. Create a folder **outside the project**, then run the *Download* commands shown by GitHub inside it:
```bash
   mkdir ~/actions-runner && cd ~/actions-runner
```
3. Run the *Configure* command shown by GitHub (`./config.sh --url … --token …`). The token is secret: never share it or put it in a screenshot. Keep the default answers, and give the runner an explicit name (`melmaado-mac`);
4. Install it as a macOS service, so it starts with the session and keeps running in the background:
```bash
   ./svc.sh install
   ./svc.sh start
   ./svc.sh status    # Started
```
   It must appear as **Idle** in *Settings → Actions → Runners*;
5. The service does not read the shell configuration. If `kubectl` or `kustomize` are not found, add their folder (`/opt/homebrew/bin`) to `~/actions-runner/.path`, then `./svc.sh stop && ./svc.sh start`;
6. In *Settings → Actions → General*, require **approval** for workflows coming from fork pull requests.

The runner uses the `kubectl` contexts and the tools of the machine: both contexts (`docker-desktop` and `team1@cluster-sc`) must exist, and `kustomize` must be installed (`brew install kustomize`).

### 6. Stop, restart and reset

| Action | Effect |
|---|---|
| Quit Docker Desktop, or *Stop* Kubernetes | The cluster stops. Everything is kept: at restart, the pods come back automatically. Meanwhile, `deploy-dev` fails |
| *Start* Kubernetes again | Nothing to reapply. Check with `kubectl get pods -A` |
| *Reset cluster* (*Settings → Kubernetes*) | **Deletes everything**: controller, namespace, deployments, data. Redo sections 2 and 3, then re-run the last CI pipeline (or section 4) |

## Online cluster (OVH)

The project also runs on a shared Kubernetes cluster hosted at OVH and managed by the teacher. Each team gets **one namespace** (`team1`) and limited rights inside it.

### Access

The teacher provides a kubeconfig file. It contains a **private key**: it is never committed, shared or shown in a screenshot.

1. Store it as `~/.kube/ecam.yaml`;
2. Back up the current configuration, then merge both files into one:
```bash
cp ~/.kube/config ~/.kube/config.backup
KUBECONFIG=~/.kube/config:~/.kube/ecam.yaml kubectl config view --flatten > /tmp/merged-config
mv /tmp/merged-config ~/.kube/config
```
3. Check that both clusters are available:
```bash
kubectl config get-contexts     # docker-desktop and team1@cluster-sc
```

The current context stays `docker-desktop`. Every command for the online cluster passes the context explicitly: `kubectl --context team1@cluster-sc …`.

### Architecture

```
                       Internet
                          | team1.laboinfo-ecam.be
+- namespace infra (teacher) -------------------------+
|        Gateway main-gateway (Envoy Gateway)         |
+--------+-----------------+-----------------+--------+
         | /               | /test           | /grafana
+- namespace team1 -----------------------------------+
|        v                 v                 v        |
|     prod              test              Grafana     |
|     app (3)           app (3)              |        |
|     postgres (2)      postgres (2)      Prometheus  |
|     shard1 (2)        shard1 (2)        (internal)  |
|     redis (2)         redis (2)                     |
+-----------------------------------------------------+
```

Each environment has its own HTTPRoute: `team1-routes-prod`, `team1-routes-test` and `grafana-route`.

- The **Gateway** belongs to the teacher: teams cannot see or change it. Each team attaches its own **HTTPRoutes** to it (Gateway API, the successor of Ingress);
- prod is served on `/`, test on `/test` and Grafana on `/grafana`. The longest matching prefix wins, so `/test/...` never reaches prod;
- In total: 9 pods for test, 9 for prod, plus Prometheus and Grafana.

### Several environments in one namespace

Without the right to create namespaces, the environments are told apart **by name and by label**, in the overlays `online-test` and `online-prod`:

```yaml
namespace: team1
nameSuffix: -test
labels:
  - pairs:
      env: test
    includeSelectors: true
```

- `nameSuffix` gives each resource a unique name (`photo-service-test`, `postgres-test`, `redis-test`…);
- `includeSelectors: true` adds `env: test` to the **selectors** too. Without it, all pods would share `app: photo-service`, and the Service of test would also send traffic to the pods of prod.

Kustomize renames the objects, but not the names written inside text fields. These are fixed by hand:

- `patch-env.yaml` sets the internal addresses of the databases and Redis (`postgres-test-0.postgres-test`, `redis-test-0.redis-test`…) and `URL_PREFIX=/test`;
- each `httproute.yaml` points to its Service with its suffix (`photo-service-test`).

### Serving test under `/test`

The app normally answers on `/`. To serve it under `/test`, the overlay sets `URL_PREFIX=/test`, and a small WSGI middleware in `app.py` removes the prefix from incoming requests and adds it back to every link generated with `url_for`. The session cookie name and path also use the prefix, so logging in to test does not log out of prod.

### Rights of the team

The rights in `team1` are limited. What matters for the project:

| Action | Allowed | Consequence |
|---|---|---|
| Deployments, StatefulSets, Services, Secrets, HTTPRoutes | yes | everything the app needs |
| Persistent volumes | only through `volumeClaimTemplates` | the StatefulSet controller creates them |
| Delete a Secret | no (update/patch only) | Secrets are updated with `kubectl apply` |
| ConfigMaps | no | configuration files are stored in Secrets |
| `exec`, `port-forward`, events | no | debug with `kubectl logs` and `-o jsonpath='{.status.conditions}'` |
| Argo CD `Application` | no | deployments are done by GitHub Actions |
| Create a namespace | no | test and prod share `team1` |

The cluster is shared and **almost full**. New pods can stay `Pending` with `Insufficient memory`. The memory requests were lowered (PostgreSQL asks for 96 Mi) so that test and prod both fit; there is no room left for an online dev.

### Secrets

Two Secrets are not in Git, because they contain passwords:

- `photo-secrets`: `POSTGRES_PASSWORD` and `SECRET_KEY` (Flask session signature);
- `grafana-admin`: `admin-password` of Grafana.

They are created with random values by `scripts/deploy-online.sh` when they are missing, and never displayed. To read the Grafana password, only in a private terminal:

```bash
kubectl --context team1@cluster-sc -n team1 get secret grafana-admin \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

Never recreate `photo-secrets` while the PostgreSQL volumes still exist: PostgreSQL keeps the password of its first start, and the app could no longer connect.

### Deploy

The app is deployed by the CI only (see *CI/CD*). The image tag in the online overlays is not updated in Git, so applying them by hand would bring back an old version.

If the namespace is wiped, everything is rebuilt with the **Redeploy online** button (*Actions → Redeploy online → Run workflow*, then approve), or by hand with an explicit tag:

```bash
./scripts/deploy-online.sh "$(git rev-parse origin/main)"
```

The script:

1. creates the missing Secrets;
2. applies `online-test` and `online-prod` with the given image tag;
3. applies `monitoring`;
4. waits for every Deployment to be ready, and stops at the first error.

It is idempotent: if everything already exists, Kubernetes answers `unchanged` and nothing restarts. The databases come back **empty** after a wipe: there are no backups. The init container recreates the tables.

Before applying a change for the first time, a dry run checks the syntax **and the rights**, without creating anything:

```bash
kubectl --context team1@cluster-sc apply -k manifests/overlays/online-prod --dry-run=server
```

### Check

```bash
kubectl --context team1@cluster-sc -n team1 get pods -l env=prod
kubectl --context team1@cluster-sc -n team1 describe httproute team1-routes-prod   # Accepted: True, ResolvedRefs: True
curl http://team1.laboinfo-ecam.be/health
curl http://team1.laboinfo-ecam.be/test/health
```

## Moving to a cloud cluster

The same manifests can run on a managed cluster such as **Amazon EKS**, **Google GKE** or **Azure AKS**. The app does not depend on OVH; only the way the cluster is reached and a few shared pieces change.

### What stays the same

- The base manifests: app, StatefulSets, Services, probes, init container;
- The images on GHCR (public, nothing to configure);
- The Kustomize overlays and the CI flow (`test → build → deploy → approval → prod`).

### What changes

| Topic | Local / OVH | Cloud |
|---|---|---|
| Cluster | Docker Desktop / shared namespace | own cluster, created with `eksctl`, `gcloud` or `az` |
| Environments | name suffixes in `team1` | **one namespace per environment** (`photo-test`, `photo-prod`): `nameSuffix` and `patch-env.yaml` are no longer needed |
| Entry point | nginx Ingress / teacher's Gateway | own Gateway (or Ingress) with a cloud load balancer, and a DNS record |
| HTTPS | none locally / teacher's Gateway | cert-manager with Let's Encrypt |
| Volumes | Docker Desktop disk / OVH | the default StorageClass of the cloud (EBS, Persistent Disk, Azure Disk) |
| Secrets | created by the script | a secret manager (AWS Secrets Manager, Google Secret Manager, Key Vault) with External Secrets Operator |
| CI access | self-hosted runner with a kubeconfig | GitHub-hosted runner with **OIDC**: GitHub gets a short-lived token from the cloud, no key is stored |
| Database | PostgreSQL StatefulSets | can stay, or move to a managed database (RDS, Cloud SQL, Azure Database) with backups and failover included |
| Photos | in PostgreSQL | object storage (S3, Cloud Storage, Blob Storage), only the path in the database |

### Steps

1. **Create the cluster** with the cloud CLI (for example `eksctl create cluster --name photo --region eu-west-3 --nodes 3`), then check the new context with `kubectl config get-contexts`;
2. **Install the entry point**: a Gateway API implementation (Envoy Gateway, or the cloud's own) or an Ingress controller. It gets a public IP from the cloud load balancer; point a DNS record to it;
3. **Install cert-manager** and a Let's Encrypt issuer for HTTPS;
4. **Create the namespaces** `photo-test` and `photo-prod`;
5. **Adapt the overlays**: replace `namespace: team1` and `nameSuffix` by the new namespaces, remove `patch-env.yaml`, and point the HTTPRoutes to the new Gateway with the real host name;
6. **Create the Secrets** in each namespace, by hand with `openssl rand` or through External Secrets;
7. **Give the CI access**: create a cloud role that trusts GitHub's OIDC provider for this repository, and replace `runs-on: self-hosted` by `ubuntu-24.04` in the deploy jobs, with the cloud's login action (for example `aws-actions/configure-aws-credentials`) before `kubectl`;
8. **Deploy** by pushing to `main`, then check with `kubectl get pods -n photo-prod` and the public URL;
9. **Optionally**, install Argo CD: the CI would then only write the new tag to Git, and Argo CD would sync the cluster.

### Cost and limits

A managed cluster costs money even when idle (control plane and nodes). For a small project, a single small node pool is enough; a managed database and object storage add their own costs, but remove the need to run backups and failover by hand.