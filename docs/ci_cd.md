# CI/CD
## 1. What happens when I push some new code ?
New code never goes straight to `main`. It follows this flow:

```
feature/* or fix/*  --PR-->  dev  --PR (release)-->  main
```

At every push, GitHub Actions tests three routes, `/`, `/health` and `/metrics`, using pytest.
If the tests pass, the image is built and published to GHCR. Then:

- on **`dev`** (a merged PR), the image is deployed to the **dev** environment, on the local cluster;
- on **`main`** (a merged release PR), the image goes through **dev**, then the **online test** environment, and after a manual approval, the **same image** is deployed to **production**;
- on any other branch, only the tests and the build run.

If one of the tests fails, the rest of the pipeline is skipped altogether.

```
push on main -> test -> build -> deploy-dev -> deploy-test -> approval -> deploy-prod
```

| Environment | Where | URL | Deployed by |
|---|---|---|---|
| dev | local cluster (Docker Desktop), namespace `21359-dev` | `http://dev.photo.localhost` | the CI, on `dev` and `main` |
| test | online cluster, namespace `team1` | `http://team1.laboinfo-ecam.be/test` | the CI, on `main` |
| prod | online cluster, namespace `team1` | `http://team1.laboinfo-ecam.be` | the CI, on `main`, after approval |

## 2. How does it work, step by step ?

### Job 1: `test`
This job runs on a `ubuntu-24.04` machine provided by GitHub :

1. Downloads the repository code onto the machine;

2. Sets up the right Python version, `3.12.6`, because it's the same as the one in the Dockerfile and the local venv;

3. Installs dependencies thanks to `requirements-dev.txt` which adds `pytest` to the app dependencies;

4. Runs `pytest` to check if the code works as intended.

The tests do not need a database or Redis: the app only connects to them inside the routes that use them, and the cache is disabled when `REDIS_URL` is not set.

This job fails if one of the tests fails.

### Job 2: `build`
This job needs the `test` job to succeed in order to run. It also runs on its own `ubuntu-24.04` machine provided by GitHub. To build a new image, a new checkout of the code is needed (`contents: read`). To publish an image on GHCR, the `packages: write` permission is necessary.

1. Downloads the repository code onto the machine;

2. Logs in GHCR through the action `docker/login-action` using the temporary token `GITHUB_TOKEN` provided automatically each run (no password needed);

3. Builds the new image of the app, named `ghcr.io/melmaado/photo-service`. Its tag is the hash of the commit. This hash is used as the value for `APP_VERSION` in the app as well;

4. Pushes the image to GHCR, the image is public because the package `photo-service` is, thanks to the repository being public.

An error in the Dockerfile, a connection issue, or a rights issue (failing push) can make this job fail.

### Job 3: `deploy-dev`
This job runs on a self-hosted runner, on the developer's Mac (`melmaado-mac`). The line `runs-on: self-hosted` of the workflow sends it there. It runs after `build`, for a push to `dev` or `main`.

1. Downloads the repository code onto the machine;

2. Updates the tag of the image in the `dev` overlay (`kustomize edit set image ...`), in the runner's working copy only, without committing to the repository;

3. Sends the `dev` overlay to the local cluster (`kubectl apply -k ... --context docker-desktop`). The local cluster pulls the image from GHCR, like the online one;

4. Waits until the rolling update is complete (`kubectl rollout status ... -n 21359-dev`).

### Job 4: `deploy-test`
This job also runs on the self-hosted runner. It runs only after `deploy-dev`, and only for a push to `main`.

1. Downloads the repository code onto the machine;

2. Updates the tag of the image (making it the commit hash) in the `online-test` overlay (`kustomize edit set image ...`), in the runner's working copy only;

3. Sends the `online-test` overlay to the online cluster (`kubectl apply -k ... --context team1@cluster-sc`). Since the image tag changed, Kubernetes starts a rolling update;

4. Each new pod first runs its `migrate` init container (`alembic upgrade head` on both shards), then the app starts. Old pods are only stopped once a new one is ready, so the service is never interrupted;

5. Waits until the rolling update is complete (`kubectl rollout status ...`), otherwise the job fails. Without waiting, the job would be green as soon as the request was sent, even if the pods crashed afterwards. The maximum waiting time is 300 seconds, because the migration can fail a few times before the databases are ready, and 3 pods are replaced one by one.

### Job 5: `deploy-prod`
This job needs `deploy-test` to succeed, and is attached to the GitHub environment `production`:

- The environment has a **required reviewer**: the job waits ("Waiting for review") until someone clicks **Approve and deploy**. This is the validation step: the new version can be checked on `/test` before it reaches production;
- Only the `main` branch is allowed to deploy to this environment.

The steps are the same as `deploy-test`, with the `online-prod` overlay and the `photo-service-prod` Deployment. The tag is the same `${{ github.sha }}`: the **exact image tested** is promoted, nothing is rebuilt.

### Other workflows (buttons)
Two workflows are started by hand, from the **Actions** tab (`workflow_dispatch`). Both run on the self-hosted runner.

| Workflow | What it does | Protection |
|---|---|---|
| **Refresh test database** | Copies production into test and anonymizes it (see [Database](database.md#test-data-refresh)) | Only touches test |
| **Redeploy online** | Runs `scripts/deploy-online.sh` with the commit of `main`: recreates the missing Secrets, then test, prod and monitoring | Only from `main`, environment `production` (approval required) |

## 3. Why is it done like that ?

### Why branches and pull requests?
`main` is what runs in production, so it must always work. Each change is made on its own branch (`feature/...` for a new feature, `fix/...` for a correction), then merged into `dev` with a pull request. The CI deploys `dev` on the local cluster, where the change can be checked with the other recent changes. When `dev` is ready, a **release** pull request merges `dev` into `main`, which starts the deployment to test and prod.

- Every change is visible in a pull request, with its diff and its CI result;
- Several changes can wait on `dev` and be released together;
- A ruleset protects `main` and `dev`: they cannot be deleted, and force pushes are blocked, so their history cannot be rewritten.

### Why do the tests come **before** the build ?
Because of the fail fast principle:

- Tests take a few seconds, the build takes way more time;

- If they fail, the job stops directly without building nor publishing an image that will never be deployed;

- No image with broken code will reach GHCR nor the cluster.

### Why is the image tag the commit hash and not `latest`?
Since each commit has a unique hash, it can have a unique tag for each commit. So that in case of an issue, it can be traced back to a specific commit. With latest:

- The text `image: …:latest` stays the same from one deployment to another, k8s thus never sees any change in the template and doesn't start any rolling update: the new image would never be deployed;

- It's also impossible to properly roll back since the previous version doesn't have a specific name.

Since the hash is used as tag and as `APP_VERSION`, the application shows exactly which commit is running.

### Why is the version baked **in** the image during the build?
1. Before: the version came from the manifest. In the base, Deployment had `APP_VERSION: "1.3"` hardcoded, making the displayed version "1.3" while running another version.

2. The issue: When the version is in the manifest, it depends on who deploys the image and how. Deploying the same image somewhere else would make it so it doesn't have a specific version, or have a fake one.

3. The solution: Putting the version in the image, during the build. The image keeps its version everywhere it runs. This is needed to promote the exact image tested from test to production: it tells the truth in both.

#### How it's done:

- In the **Dockerfile**, `ARG APP_VERSION=dev` gets a value during the build and `ENV APP_VERSION=$APP_VERSION` keeps it in the container;

- In the **CI**, `--build-arg APP_VERSION=< commit hash >` provides the hash;

- These two lines are put at **the bottom of** the Dockerfile: since the hash changes each build, it avoids re-running `pip install` on every build, thanks to the layer cache;

- Without `--build-arg`, the image displays `dev`, which directly highlights any oversight.

### Why a manual approval before production?
The statement asks for `Test → Validation → Production`. Tests only check a few routes; a human can check the real application on `/test` (login, upload, duplicates) before approving. The approval is recorded in GitHub (who approved, when), and nothing reaches production by accident.

### Why GitHub Actions and not Argo CD?
Argo CD is installed on the online cluster, but the `team1` user has no rights on its `Application` objects (`kubectl auth can-i create applications.argoproj.io` returns `no`). The same promotion is therefore done with GitHub Actions and a protected environment. With Argo CD, the CI would only write the new tag to Git, and Argo CD would synchronise the cluster from Git (see Limitations).

### Why a **self-hosted runner**? What are the safety precautions?
The deployment jobs need the credentials of the online cluster, stored in `~/.kube/config` on the developer's Mac. A GitHub-hosted runner would need this file as a repository secret, so the private key would leave the machine. With a self-hosted runner, the runner fetches the jobs from GitHub and the credentials never leave the Mac. It is also the only way to reach the local cluster, for `deploy-dev`.

The main risk of a self-hosted runner on a public repository is that someone executes undesired code on the local machine. To prevent that:

- The workflow only starts from a push or a button, which only the repository owner can do (no other collaborators);

- The deployment jobs run only for `dev` and `main`, and only `main` can deploy to the `production` environment;

- Workflows coming from pull requests of forks need approval from the repository owner (*Settings → Actions → General*);

- The runner lives in its own folder outside of the project, `~/actions-runner`.

The runner is installed as a macOS service (`./svc.sh install`): it starts automatically when the user logs in, and can be stopped with `./svc.sh stop`.

### Why use **Kustomize**? Why use a base and overlays?
#### The issue
Before using Kustomize, the namespace, the image, and `imagePullPolicy: Never` were hardcoded in the manifests. That would work for only **1** environment. For the other environments, there were only two bad options:

- **Copy all the manifests** for each environment. At each modification (for example the probes), one had to do it everywhere, and an oversight would create invisible differences between environments;

- **Modify the files on the fly** in the CI, with text replacement commands. Which is fragile and hard to read.

#### The idea of Kustomize: what is common is done once

```
manifests/
|-- namespaces.yaml                  # local namespace 21359-dev, applied once
|-- base/                            # what is common to every environment
|   |-- deployment.yaml              # app + migrate init container
|   |-- service.yaml
|   |-- service-headless.yaml        # used by Prometheus
|   |-- postgres-*.yaml              # shard 0 (StatefulSet + headless Service)
|   |-- postgres-shard1-*.yaml       # shard 1
|   |-- postgres-init/               # replication script (Secret)
|   `-- redis-*.yaml                 # Redis cache (StatefulSet + headless Service)
|-- local-ingress/                   # nginx Ingress, local cluster only
|-- monitoring/                      # Prometheus + Grafana, online
|-- jobs/                            # one-off pods (test database refresh)
`-- overlays/
    |-- dev/                         # local, namespace 21359-dev
    |-- online-test/                 # online, suffix -test, route /test
    `-- online-prod/                 # online, suffix -prod, route /
```

- The base manifests describe what every environment needs: the app, the two PostgreSQL shards with their replicas, Redis, and the Services. It's only written **once**.

- An overlay takes the base but changes specific things. It only contains differences.

| | `dev` | `online-test` | `online-prod` |
|---|---|---|---|
| cluster | local | online | online |
| namespace | `21359-dev` | `team1` | `team1` |
| name suffix | none | `-test` | `-prod` |
| label | | `env: test` | `env: prod` |
| entry point | Ingress `dev.photo.localhost` | route `/test` (`URL_PREFIX=/test`) | route `/` |
| internal addresses | from the base | `postgres-test-0.postgres-test`, … (`patch-env.yaml`) | `postgres-prod-0.postgres-prod`, … |
| Secret `photo-secrets` | generated with local values | created by hand | created by hand |
| image | set by the CI | set by the CI | set by the CI (same tag as test) |

Kustomize renames the objects with the suffix, but never changes the text inside environment variables or `backendRefs`. These hand-written names are therefore fixed by `patch-env.yaml` and in each `httproute.yaml`.

#### Two main advantages:

- **Applying an overlay needs nothing extra**: Kustomize is integrated into `kubectl`: `kubectl apply -k manifests/overlays/online-test`;

- **CI changes the image tag using a single command**: `kustomize edit set image ...`, without modifying the other files, but it needs the installation of `kustomize` on the runner's machine.

### Why `ubuntu-24.04` instead of `ubuntu-latest`?
During the first run of the CI, GitHub made it clear that the `ubuntu-latest` label will point to `Ubuntu 26` starting October 19, 2026. The environment could change and provoke an unexpected issue (for example `Python 3.12.6` not being supported). It's a good practice to use fixed versions to have a reproducible result, like `python:3.12.6-slim` in the Dockerfile and the pinned versions in `requirements.txt`. This way, the runner version only changes when we decide to.

## 4. What does it need to work ?
### On the runner's machine (`melmaado-mac`)

- The Mac turned on, and the **runner service started** (`./svc.sh status` shows `Started`);

- **Docker Desktop** running with Kubernetes enabled, for `deploy-dev`;

- The contexts `docker-desktop` and `team1@cluster-sc` in `~/.kube/config` (`kubectl config get-contexts`);

- The standalone **`kustomize`** tool installed: `brew install kustomize`.

### On the online cluster

Nothing needs to be created by hand: the **Redeploy online** button creates the Secrets `photo-secrets` and `grafana-admin` with random values when they are missing. They are never committed and never displayed.

### On GitHub

- The runner `melmaado-mac` registered and **Idle** in *Settings → Actions → Runners*;

- The environment `production` with a **required reviewer**, limited to the `main` branch, in *Settings → Environments*;

- The package `ghcr.io/melmaado/photo-service` **public**, so the clusters can pull it without credentials;

- Workflows from fork pull requests **requiring approval** in *Settings → Actions → General*;

- The ruleset protecting `main` and `dev` in *Settings → Rules → Rulesets*.

### When pushing

- The push must be on **`dev`** (deploys dev) or **`main`** (deploys dev, test and prod), otherwise the deployments are skipped;

- The tests must pass, otherwise `build` and the deployments are skipped.

## 5. What to do when it crashes ?
### Check that a deployment worked
```bash
# 1. The run is green in the Actions tab of the repository
# 2. The deployed image is the commit of the run
kubectl get deployment photo-service-test -n team1 --context team1@cluster-sc \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
# 3. All pods are running
kubectl get pods -n team1 --context team1@cluster-sc -l env=test
# 4. The app answers
curl http://team1.laboinfo-ecam.be/test/health
```

### Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| A deploy job stays in **Queued** | The runner is stopped, or the Mac is off | `cd ~/actions-runner && ./svc.sh start` |
| `deploy-dev` fails, so test and prod are skipped | Docker Desktop is closed | Start Docker Desktop, then **Re-run failed jobs** |
| `deploy-prod` shows **Waiting for review** | Normal: it waits for the approval | *Review deployments → Approve and deploy* |
| The deploy jobs are **skipped** | The push was not on `dev`/`main`, or `test`/`build` failed | Merge the PR; check the failed job's logs |
| `test` fails | A unit test fails | Open the `test` job logs: pytest shows the failing `assert`. Run `pytest` locally to reproduce |
| `build` fails at the push step | Missing `packages: write` permission, or GHCR login failed | Check the `permissions` block of the `build` job |
| `kubectl` or `kustomize: command not found` | The runner service does not know where the tools are installed | Add their folder (e.g. `/opt/homebrew/bin`) to `~/actions-runner/.path`, then `./svc.sh stop && ./svc.sh start` |
| New pods in `Init:Error` / `Init:CrashLoopBackOff` for a minute | The migration runs before the databases are ready | Wait: Kubernetes retries. If it lasts, `kubectl logs <pod> -c migrate` |
| Pods stuck in `Pending` | The shared cluster has no memory left | `kubectl get pod <pod> -o jsonpath='{.status.conditions}'` shows `Insufficient memory` |
| Pods stuck in `ImagePullBackOff` | The image cannot be downloaded (wrong tag, private package) | Check that the package is public and that the tag exists on GHCR |
| `rollout status` times out after 300 s | The new pods never become ready | Read the pod logs: `kubectl logs <pod> -n team1 --context team1@cluster-sc` |
| Everything was deleted from `team1` | The cluster was reset | **Actions → Redeploy online → Run workflow**, then approve |

### Roll back quickly
In an emergency, `kubectl rollout undo deployment/photo-service-prod -n team1 --context team1@cluster-sc` restores the previous version in a few seconds. It is an imperative command: the clean fix is then to revert the faulty commit on `main`, so that the next pipeline deploys a corrected version.

If the faulty version came with a schema migration, the previous app still works with the new schema, because new columns always have a default value. The migration can be rolled back with `alembic downgrade -1` (see [Database](database.md#schema-migrations)).

### Rebuild everything from scratch
`scripts/deploy-online.sh <tag>` redeploys test, prod and monitoring. It is idempotent: if everything already exists, Kubernetes answers `unchanged` and nothing restarts. The **Redeploy online** button runs it with the current commit of `main`. The databases come back empty: there are no backups (see [Database](database.md#limitations)).

## 6. Limitations

- **The deployed tag is not written back to Git.** The overlays in the repository still contain an older tag. Applying `online-test` or `online-prod` by hand would roll back the application; only the CI and the Redeploy button deploy the app. With Argo CD, the CI would commit the new tag and Git would always show what runs in the cluster.

- **The runner is a single machine.** If the Mac is off, deployments wait in the queue until it comes back. If Docker Desktop is closed, `deploy-dev` fails and blocks test and prod.

- **Dev is not online.** The shared cluster has no memory left for a third complete environment: new pods stay `Pending` with `Insufficient memory`. Dev runs on the developer's machine, test and prod online.

- **Test and prod share one namespace.** The online user only has rights on `team1`, so the environments are separated with name suffixes and labels instead of namespaces.

- **Security of a public repository.** The self-hosted runner runs on the developer's Mac, so the cluster credentials never leave it. Because the repository is public, workflows from forks require manual approval, only `main` can deploy to production, and the repository has no other collaborators.