# Cluster Setup

# Cluster Setup

This page explains how the Kubernetes cluster is built, from scratch, and how to move it to a cloud cluster. It is done **once per cluster**. To work on the app day to day, see the *Onboarding* page.

## Architecture

```
                       Browser / curl
                             │  port 80
┌─ Cluster (Docker Desktop) ─▼─────────────────────────────────────┐
│                                                                  │
│  namespace ingress-nginx                                         │
│    Ingress Controller (nginx) ── Service LoadBalancer (localhost)│
│        │ routes by domain                                        │
│        ├──────────────────────────────┐                          │
│        ▼                              ▼                          │
│  namespace 21359-dev            namespace 21359-test             │
│    Ingress dev.photo.localhost    Ingress test.photo.localhost   │
│    Service (ClusterIP)            Service (ClusterIP)            │
│    Deployment: 3 pods             Deployment: 3 pods             │
│                                                                  │
│  namespace 21359-prod (created, not used yet)                    │
└──────────────────────────────────────────────────────────────────┘
```

- **One single Ingress controller** for the whole cluster: it is the only entry point from outside;
- **One namespace per environment**: each one has its own Ingress rule (its own domain), Service and Deployment;
- The Services are **ClusterIP**: they are only reachable from inside the cluster, through the Ingress controller.

## 1. Enable Kubernetes

1. Install Docker Desktop (see *Onboarding*);
2. In Docker Desktop, open *Settings → Kubernetes*, enable Kubernetes and apply;
3. Wait until *Kubernetes running* is displayed at the bottom of the window.

Check that `kubectl` points to this cluster:

```bash
kubectl config current-context    # must return docker-desktop
kubectl get nodes                 # one node, STATUS Ready
```

Always check the context before an `apply` or a `delete`: once several clusters are configured, a command sent to the wrong one can break it.

## 2. Install the Ingress controller

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

> **Note:** the community project ingress-nginx was retired by Kubernetes in March 2026: it still works, but no longer receives updates or security fixes. It is used here for its simplicity and its documentation. For production, a maintained alternative should be preferred (NGINX Ingress Controller by F5, Traefik, or the Gateway API). Only the `ingressClassName` field of the Ingress resources would change.

## 3. Create the namespaces

```bash
kubectl apply -f manifests/namespaces.yaml
kubectl get namespaces
```

The three namespaces `21359-dev`, `21359-test` and `21359-prod` are prefixed with the student ID, so they never collide with other students' namespaces on a shared cluster. They are kept outside Kustomize: a namespace does not belong to a namespace.

## 4. Deploy the environments

- **dev**: deployed by hand, with a local image. See section 5 of the *Onboarding* page;
- **test**: deployed automatically by the CI on every push to `main`. See the *CI/CD* page.

Both use Kustomize overlays: `kubectl apply -k manifests/overlays/<environment>`. The local overlays add the Ingress from `manifests/local-ingress/`, which is not part of the base because the online cluster uses the Gateway API instead.

Check the whole cluster:

```bash
kubectl get all -n 21359-dev
kubectl get all -n 21359-test
kubectl get ingress -A          # one rule per environment, each with its own domain
curl http://dev.photo.localhost
curl http://test.photo.localhost
```

## 5. Set up the CI runner

The `deploy` job of the CI runs on a **self-hosted runner** installed on the machine that hosts the cluster, because GitHub's machines cannot reach a local cluster. This is done once, on that machine only.

1. On GitHub: *Settings → Actions → Runners → New self-hosted runner*, then choose **macOS** and the right architecture (**ARM64** for an Apple chip);
2. Create a folder **outside the project**, then run the *Download* commands shown by GitHub inside it:
```bash
   mkdir ~/actions-runner && cd ~/actions-runner
```
3. Run the *Configure* command shown by GitHub (`./config.sh --url … --token …`). The token is secret: never share it or put it in a screenshot. Keep the default answers, and give the runner an explicit name;
4. Start the runner by hand when needed:
```bash
   ./run.sh
```
   It must display `Listening for Jobs`, and appear as **Idle** in *Settings → Actions → Runners*;
5. In *Settings → Actions → General*, require **approval** for workflows coming from fork pull requests.

The runner uses the `kubectl` context and the tools of the machine: `kubectl` must point to the cluster, and `kustomize` must be installed (`brew install kustomize`).

## 6. Stop, restart and reset

| Action | Effect |
|---|---|
| Quit Docker Desktop, or *Stop* Kubernetes | The cluster stops. Everything is kept: at restart, the pods come back automatically |
| *Start* Kubernetes again | Nothing to reapply. Check with `kubectl get pods -A` |
| *Reset cluster* (*Settings → Kubernetes*) | **Deletes everything**: controller, namespaces, deployments. Redo sections 2 to 4 |

## 7. Online cluster (OVH)

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

The current context stays `docker-desktop` (the CI runner uses it). Every command for the online cluster passes the context explicitly: `kubectl --context team1@cluster-sc …`.

### Architecture

```
                     Internet
                        │  http://team1.laboinfo-ecam.be
┌─ namespace infra (teacher) ─▼─────────────────────────────────────┐
│   Gateway main-gateway (Envoy Gateway, HTTP only)                 │
└───────────────┬───────────────────────────────┬───────────────────┘
                │ /                             │ /grafana
┌─ namespace team1 ──────────────────────────────────────────────────┐
│               ▼                               ▼                    │
│   HTTPRoute team1-routes-prod         HTTPRoute grafana-route      │
│   Service photo-service-prod          Service grafana              │
│   Deployment: 3 pods                  Prometheus (internal)        │
│                                                                    │
│   Service photo-service-test   (not exposed)                       │
│   Deployment: 3 pods                                               │
└────────────────────────────────────────────────────────────────────┘
```

- The **Gateway** belongs to the teacher: teams cannot see or change it. Each team attaches its own **HTTPRoutes** to it (Gateway API, the successor of Ingress);
- Only **prod** and the **dashboard** are public. **Test** is not exposed: without HTTPS, any login on it would send passwords in clear.

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

- `nameSuffix` gives each resource a unique name (`photo-service-test`, `photo-service-prod`);
- `includeSelectors: true` adds `env: test` to the **selectors** too. Without it, all pods would share `app: photo-service`, and the Service of test would also send traffic to the pods of prod.

The HTTPRoute points to its Service by name. Kustomize does not know this field, so the name is written with its suffix: `photo-service-prod`.

### Manifests layout

```
manifests/
├── base/              Deployment, Service, headless Service (common to every environment)
├── local-ingress/     Ingress, only used on the local cluster
├── monitoring/        Prometheus and Grafana (online)
└── overlays/
    ├── dev/           local
    ├── test/          local (deployed by the CI)
    ├── online-test/   OVH
    └── online-prod/   OVH, with the HTTPRoute
```

### Deploy

Everything online is redeployed with one command, from the repository root:

```bash
./scripts/deploy-online.sh
```

It applies `online-test`, `online-prod` and `monitoring`, waits for every Deployment to be ready, and stops at the first error. It can be run again safely: resources that did not change stay untouched. If the cluster is wiped, this script rebuilds everything from Git (only the Grafana admin password, which is not in Git, has to be recreated if needed).

The image tag of each environment is written in its overlay (`newTag`). A version goes to prod only after it was checked in test, with the **same tag**: the image that reaches prod is exactly the one that was tested. Overlays are committed after each change of tag, otherwise a rebuild would bring back an older version.

Before applying a change for the first time, a dry run checks the syntax **and the rights**, without creating anything:

```bash
kubectl --context team1@cluster-sc apply -k manifests/overlays/online-prod --dry-run=server
```

### Check

```bash
kubectl --context team1@cluster-sc get pods -l env=prod
kubectl --context team1@cluster-sc describe httproute team1-routes-prod   # Accepted: True, ResolvedRefs: True
curl http://team1.laboinfo-ecam.be
```

Test is not reachable from outside, and port-forward is not allowed on this cluster. It is checked from inside, with a throwaway pod:

```bash
kubectl --context team1@cluster-sc run curl-test --image=curlimages/curl --restart=Never -- curl -s http://photo-service-test:8080
kubectl --context team1@cluster-sc logs curl-test      # once the pod is Completed
kubectl --context team1@cluster-sc delete pod curl-test
```

### Current limits

- **Deployment is manual**: the CI still deploys to the local cluster. Deploying to OVH from the pipeline is the next step;
- **No dev environment online** yet: dev stays local;
- **Limited rights**: no ConfigMaps, no persistent volumes, no port-forward, no CPU metrics. The full list and the workarounds are in *Monitoring*, section 7.