# CI/CD
## 1. What happens when I push some new code ?
As soon as a push is made, GitHub Actions verifies the code of two routes, `/` and `/health` using pytest.
After the test is done successfully, the image is built, published to GHCR and then deployed to the `21359-test` namespace **only if** the push is done on the `main` branch. From any other branch, deploy is ignored.

If one of the tests fails, the rest of the pipeline is skipped altogether.

```
push -> test -> build -> deploy
```

## 2. How does it work, step by step ?

### Job 1: `test`
This job runs on a `ubuntu-24.04` machine provided by GitHub :

1. Downloads the repository code onto the machine;

2. Sets up the right Python version, `3.12.6`, because it's the same as the one in the Dockerfile and the local venv;

3. Installs dependencies thanks to `requirements-dev.txt` which adds `pytest` to the app dependencies;

4. Runs `pytest` to check if the code works as intended.

This job fails if one of the tests fails.

### Job 2: `build`
This job needs the `test` job to succeed in order to run. It also runs on its own `ubuntu-24.04` machine provided by GitHub. To build a new image, a new checkout of the code is needed (`contents: read`). To publish an image on GHCR, the `packages: write` permission is necessary.

1. Downloads the repository code onto the machine;

2. Logs in GHCR through the action `docker/login-action` using the temporary token `GITHUB_TOKEN` provided automatically each run (no password needed);

3. Builds the new image of the app, named `ghcr.io/melmaado/photo-service`. Its tag is the hash of the commit. This hash is used as the value for `APP_VERSION` in the app as well;

4. Pushes the image to GHCR, the image is public because the package `photo-service` is, thanks to the repository being public.

An error in the Dockerfile, a connection issue, or a rights issue (failing push) can make this job fail.

### Job 3: `deploy`
This job is hosted on a self-hosted runner, on a local machine (`melmaado-mac`), because the professor's cluster is not available, and a local k8s one is running on that same machine. If the job was not running locally, the GitHub machines used for `test` and `build` would not be able to communicate with the local cluster hosted by Docker Desktop. It's the runner that looks for the jobs on GitHub, not the opposite. The line `runs-on: self-hosted` of the `ci.yml` file sends this job to the runner. When the professor's cluster is available, the pipeline will not change, only the target of deployment.

It runs only after the `build` job, and only for a push to the `main` branch for two reasons: to keep the machine hosting the runner safe by only allowing code from `main` to be executed, and to avoid deploying code from a not validated test branch.

1. Downloads the repository code onto the machine;

2. Updates the tag of the image (making it the commit hash) in the test overlay (`kustomize edit set image ...`) in the runner's working copy without committing in the repository;

3. Sends the configuration of the test overlay to the cluster in the `21359-test` namespace (`kubectl apply -k ...`) and since the tag of the image changed, k8s starts a rolling update;

4. Waits until the rolling update is complete, if not so it makes the job fail. If it didn't wait, the job would be considered done as soon as the request was sent, even if the pods crash afterwards (`kubectl rollout status ...`). The maximum waiting time is 120 seconds.

Any issue with the `melmaado-mac` local machine (stopped runner, Docker Desktop being closed, `kustomize` being absent) or with deployment (image not found, pods never ready) would make the job fail.

## 3. Why is it done like that ?

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
1. Before: the version came from the manifest. In the base, Deployment had `APP_VERSION: "1.3"` hardcoded, making the displayed version "1.3" while running another version. Keeping it so would have kept displaying "1.3" at each push.

2. The issue: When the version is in the manifest, it depends on who deploys the image and how. Deploying the same image somewhere else would make it so it doesn't have a specific version, or have a fake one. The image wouldn't know where it comes from.

3. The solution: Putting the version in the image, during the build. The image keeps its version everywhere it runs. Which is needed for what is coming: in production, we won't build a new image but promote the exact one tested. So it will keep telling the truth, whether during test or production.

#### How it's done:

- In the **Dockerfile**, `ARG APP_VERSION=dev` gets a value during the build and `ENV APP_VERSION=$APP_VERSION` keeps it in the container;

- In the **CI**, `--build-arg APP_VERSION=< commit hash >` provides the hash;

- These two lines are put at **the bottom of** the Dockerfile: since the hash changes each build, it avoids re-running `pip install` on every build, thanks to the layer cache;

- Without `--build-arg`, the image displays `dev`, which directly highlights any oversight;

- The `env` block was removed from the base Deployment manifest, else it would have replaced the image version.

### Why a **self-hosted runner**? What are the safety precautions?
Because the machines provided by GitHub can't reach the local cluster. The runner fetches the jobs so the local cluster never needs to be exposed to the internet.

The main risk of a self-hosted runner on a public repository is that someone executes undesired code on the local machine. To prevent that:

- The workflow only starts from a push that only the repository owner and collaborators with write access can do;

- The `deploy` job runs only for the `main` branch;

- The workflows coming from pull requests of forks need approval from the repository owner;

- The runner is launched by hand thanks to the `./run.sh` script, it's not a permanent service;

- The runner is in its own folder outside of the project, `~/actions-runner`.

### Why use **Kustomize**? Why use a base and overlays?
#### The issue
Before using Kustomize, the namespace, the image, and `imagePullPolicy: Never` were hardcoded in the manifests. That would work for only **1** environment, which was `dev` at the time. For the other environments, there were only two bad options:

- **Copy all the manifests** for each environment. At each modification (for example the probes), one had to do it everywhere, and an oversight would create invisible differences between `dev` and `test`;

- **Modify the files on the fly** in the CI, with text replacement commands. Which is fragile and hard to read.

#### The idea of Kustomize: what is common is done once

```
manifests/
├── namespaces.yaml            # applied once, outside Kustomize
├── base/                      # what is common to every environment
│   ├── kustomization.yaml     # lists the 3 files below
│   ├── deployment.yaml
│   ├── service.yaml
│   └── ingress.yaml
└── overlays/                  # only the differences per environment
    ├── dev/
    │   └── kustomization.yaml # namespace 21359-dev, image 1.4, host dev.photo.localhost
    └── test/
        └── kustomization.yaml # namespace 21359-test, GHCR image, host test.photo.localhost
```

- The base manifests describe the common structure of what every environment needs: 3 replicas, port 8080, the probes, the Service, the Ingress, the Deployment. It's only written **once**.

- An overlay takes the base but changes specific things. It only contains differences.

| | `dev` | `test` |
|---|---|---|
| namespace | `21359-dev` | `21359-test` |
| image | `photo-service:1.4` (local) | `ghcr.io/melmaado/photo-service:<hash>` |
| `imagePullPolicy` | `Never` (from base) | `IfNotPresent` (patched) |
| Ingress domain | `dev.photo.localhost` (patched) | `test.photo.localhost` (patched) |

#### Two main advantages:

- **Applying an overlay needs nothing extra**: Kustomize is integrated into `kubectl`, the command `kubectl apply -f` is no longer used, now it's `kubectl apply -k manifests/overlays/test` that is used (except for `namespaces.yaml`);

- **CI changes the image tag using a single command**: `kustomize edit set image ...`, without modifying the other files, but it needs the installation of `kustomize` on the runner's machine.


### Why `ubuntu-24.04` instead of `ubuntu-latest`?
During the first run of the CI, GitHub made it clear that the `ubuntu-latest` label will point `Ubuntu 26` starting October 19, 2026, the day before the `milestone 2` demo. The main risk is that the environment could change, which could provoke an unexpected issue (for example `Python 3.12.6` not being supported). It’s a good practice to use fixed versions to have a reproducible result, like `python:3.12.6-slim` in the Dockerfile and the pinned versions in `requirements.txt`. This way, the runner version only changes when we decide to.

## 4. What does it need to work ?
### On the runner's machine (`melmaado-mac`)

- **Docker Desktop** running, with **Kubernetes** enabled;

- `kubectl` pointing to the local cluster: `kubectl config current-context` must return `docker-desktop`;

- The **ingress-nginx** controller installed in the cluster (with Helm, see the Cluster Setup page);

- The namespaces created: `kubectl apply -f manifests/namespaces.yaml`;

- The standalone **`kustomize`** tool installed: `brew install kustomize`;

- The **runner started** by hand: `cd ~/actions-runner && ./run.sh`. It must display `Listening for Jobs`. 

### On GitHub

- The runner `melmaado-mac` registered and **Idle** in *Settings → Actions → Runners*;

- The package `ghcr.io/melmaado/photo-service` **public**, so the cluster can pull it without credentials;

- Workflows from fork pull requests **requiring approval** in *Settings → Actions → General*.

### When pushing

- The push must be on the **`main`** branch, otherwise `deploy` is skipped;

- The tests must pass, otherwise `build` and `deploy` are skipped.

## 5. What to do when it crashes ?
### Check that a deployment worked
```bash
# 1. The run is green in the Actions tab of the repository
# 2. The new pods are running in the test namespace
kubectl get pods -n 21359-test
# 3. The app answers, and the displayed version is the commit hash of the run
curl http://test.photo.localhost
```

### Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `deploy` stays in **Queued** / waiting for a runner | The runner is stopped | Start it: `cd ~/actions-runner && ./run.sh` |
| `deploy` is **skipped** | The push was not on `main`, or `test`/`build` failed | Push on `main`; check the failed job's logs |
| `test` fails | A unit test fails | Open the `test` job logs: pytest shows the failing `assert`. Run `pytest` locally to reproduce |
| `build` fails at the push step | Missing `packages: write` permission, or GHCR login failed | Check the `permissions` block of the `build` job |
| `kustomize: command not found` | `kustomize` not installed, or the runner was started before installing it | `brew install kustomize`, then restart the runner (Ctrl+C, then `./run.sh`) |
| `kubectl` cannot connect to the cluster | Docker Desktop or Kubernetes is stopped | Start Docker Desktop and wait for *Kubernetes running* |
| Pods stuck in `ImagePullBackOff` / `ErrImagePull` | The image cannot be downloaded (wrong tag, private package) | Check that the package is public and that the tag exists on GHCR. Details: `kubectl describe pod <pod> -n 21359-test` |
| `rollout status` times out after 120 s | The new pods never become ready (app crashes, `/health` not answering) | Read the pod logs: `kubectl logs <pod> -n 21359-test` |
| `curl` returns a **404 from nginx** | No Ingress rule matches the domain | Use the right domain (`test.photo.localhost`) and check `kubectl get ingress -n 21359-test` |

### Roll back quickly
In an emergency, `kubectl rollout undo deployment/photo-service -n 21359-test` restores the previous version in a few seconds. It is an imperative command: the clean fix is then to revert the faulty commit on `main`, so that the repository and the cluster match again.