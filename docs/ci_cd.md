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




## 4. What does it need to work ?


## 5. What to do when it crashes ?