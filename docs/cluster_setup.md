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

Both use Kustomize overlays: `kubectl apply -k manifests/overlays/<environment>`.

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