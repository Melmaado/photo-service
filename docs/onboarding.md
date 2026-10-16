# Onboarding

## 1. Tools to install

The commands below are for macOS and use [Homebrew](https://brew.sh), the macOS package manager. Install Homebrew first if you don't have it.

| Tool | Why the project needs it | How to install |
|---|---|---|
| **Python 3.12.6** | The language of the app. Same version as the Docker image (`python:3.12.6-slim`) and the CI, so the code behaves the same everywhere | Installer from [python.org](https://www.python.org/downloads/release/python-3126/) |
| **Git** | Version control: clone the repository, commit and push | `brew install git` |
| **Docker Desktop** | Builds and runs the images. It also provides the local **Kubernetes** cluster and the `kubectl` command | Installer from [docker.com](https://www.docker.com/products/docker-desktop/), then enable Kubernetes in *Settings → Kubernetes* |
| **Helm** | The Kubernetes package manager, used once to install the **ingress-nginx** controller | `brew install helm` |
| **kustomize** | Edits the Kustomize overlays from the command line (`kustomize edit set image`). Only needed on the machine hosting the CI runner: applying an overlay only needs `kubectl` | `brew install kustomize` |

### Check the installation

```bash
python3 --version                  # Python 3.12.6
git --version
docker --version
kubectl config current-context     # docker-desktop
helm version
kustomize version
```

## 2. Get the code

```bash
git clone https://github.com/Melmaado/photo-service.git
cd photo-service
```

All the commands below are run from the root of the repository (the `photo-service/` folder).

## 3. Run the app locally (without Docker)

### Create the virtual environment
A venv isolates the project's Python packages from the rest of the machine.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

The prompt now starts with `(.venv)`. Run `source .venv/bin/activate` again in every new terminal.

### Install the dependencies
`requirements-dev.txt` installs the app dependencies (`requirements.txt`) plus `pytest`.

```bash
pip install -r requirements/requirements-dev.txt
```

### Start the app
Two ways, depending on what you need:

```bash
# Flask development server (quick, for coding)
python app.py

# gunicorn, the production server used in the Docker image
gunicorn app:app --bind 0.0.0.0:8080 --workers=2 --threads=3
```

Then, in another terminal:

```bash
curl http://localhost:8080
curl http://localhost:8080/health
```

The version can be set with an environment variable: `APP_VERSION=1.0 python app.py`. Without it, the app falls back to a `.env` file if there is one, then to its default value.

### Run the tests

```bash
pytest
```

All the tests must pass before pushing: the CI runs the same command and blocks the pipeline if one fails.

## 4. Run the app with Docker

Docker Desktop must be running (check with `docker info`: the **Server** section must answer).

### Build the image

```bash
docker build --build-arg APP_VERSION=dev-local -t photo-service:dev-local .
```

- `--build-arg APP_VERSION=…` bakes the version into the image. Without it, the image displays `dev`;
- `-t photo-service:dev-local` gives the image a name and a tag. Use the same value for the tag and the version, so both always match;
- the final `.` is the build context: the current folder, where the `Dockerfile` is.

### Run a container

```bash
docker run --rm -p 8080:8080 photo-service:dev-local
```

- `-p 8080:8080` publishes the port: `<port on your machine>:<port in the container>`;
- `--rm` deletes the container when it stops (Ctrl+C), so stopped containers don't pile up.

Then, in another terminal:

```bash
curl http://localhost:8080
```

The machine name displayed is the container ID, and the version is the one passed with `--build-arg`.

> **Note:** on a Mac with an Apple chip, images built by the CI (on GitHub's Intel machines) run through emulation. Docker shows a platform warning, but the app works.

## 5. Deploy to the local cluster


This deploys the `dev` environment on the Kubernetes cluster of Docker Desktop.

### Prerequisites
- Kubernetes is enabled in Docker Desktop, and `kubectl` points to it:
  `kubectl config current-context` must return `docker-desktop`;
- The **ingress-nginx** controller is installed in the cluster (once per cluster, see the *Cluster Setup* page).

### 1. Build the dev image
The `dev` overlay uses a **local** image, `photo-service:1.4`, with `imagePullPolicy: Never`: Kubernetes never downloads it, so it must exist on your machine.

```bash
docker build --build-arg APP_VERSION=1.4 -t photo-service:1.4 .
```

### 2. Create the namespaces
Once per cluster. Applying it again does nothing (`unchanged`).

```bash
kubectl apply -f manifests/namespaces.yaml
```

### 3. Deploy the dev environment

```bash
kubectl apply -k manifests/overlays/dev
kubectl get pods -n 21359-dev
```

Wait until the 3 pods are `1/1 Running`.

### 4. Check that it works

```bash
curl http://dev.photo.localhost
```

Each environment has its own domain, handled by the Ingress controller. Domains ending in `.localhost` automatically point to your own machine: no configuration needed. Run the command several times: the pod name changes, which shows the traffic is shared between the 3 replicas.

### Update the dev environment
To deploy a new version of your code in `dev`:

1. Build a new image with a new tag, for example `1.5`, using the same value for `-t` and `--build-arg`;
2. Change `newTag` in `manifests/overlays/dev/kustomization.yaml` to `"1.5"` (with quotes: a tag is text);
3. Apply again with `kubectl apply -k manifests/overlays/dev`. Kubernetes performs a rolling update.

The `test` environment is not deployed by hand: the CI does it on every push to `main` (see the *CI/CD* page).

## 6. Work on the documentation

The documentation is a website built with [MkDocs](https://www.mkdocs.org) and the Material theme. The pages are Markdown files in the `docs/` folder, and the site configuration (title, theme, menu) is in `mkdocs.yml`.

### Create a separate virtual environment
The documentation tools have their own venv, `.venv-docs`, so they never end up in `requirements.txt` and therefore never in the app image.

```bash
python3 -m venv .venv-docs
source .venv-docs/bin/activate
pip install -r requirements/requirements-docs.txt
```

Tip: use one terminal per venv, `.venv` for the app and `.venv-docs` for the documentation. The prompt shows which one is active.

### Preview the site

```bash
mkdocs serve
```

Open the address it displays (by default `http://127.0.0.1:8000`). The page reloads automatically every time a file is saved.

### Add a page
1. Create a Markdown file in `docs/`, in lowercase and without spaces (for example `docs/my_page.md`);
2. Add it to the `nav` section of `mkdocs.yml`, otherwise it won't appear in the menu:
```yaml
   nav:
     - "My page": my_page.md
```

### Writing rules
- Leave an **empty line before a list or a table**, otherwise MkDocs displays them as plain text;
- Put commands in code blocks with the language (```` ```bash ````, ```` ```yaml ````);
- For every technical choice, explain **why**, not only **how**.

## 7. How changes reach the test environment

The `test` environment is updated automatically by the CI pipeline: nobody deploys it by hand.

### The usual workflow

1. Make your change and run the tests locally:
```bash
   pytest
```
2. Commit with a short message describing **what** changes (for example `Add photo upload route`);
3. Push to the `main` branch;
4. Follow the run in the **Actions** tab of the repository: `test` → `build` → `deploy`;
5. Check the result:
```bash
   curl http://test.photo.localhost
```
   The displayed version is the hash of your commit.

### Good to know
- **Only pushes to `main` are deployed.** On any other branch, the tests and the build still run, but `deploy` is skipped. A branch is a safe place to try something out;
- **If a test fails, nothing is built or deployed**, and the commit gets a ❌ in the Actions tab;
- **The `deploy` job runs on the self-hosted runner** of the machine that hosts the cluster. It is configured once on that machine only: a new developer does not need to install it. If the runner is stopped, `deploy` waits until it is started again;
- **The `dev` environment is not updated by the CI**: it stays on the local image until you update it yourself (see section 5).

For the details of each job, the technical choices and the troubleshooting guide, see the *CI/CD* page.