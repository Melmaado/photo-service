# Onboarding

## 1. Tools to install

The commands below are for macOS and use [Homebrew](https://brew.sh), the macOS package manager. Install Homebrew first if you don't have it.

| Tool | Why the project needs it | How to install |
|---|---|---|
| **Python 3.12.6** | The language of the app. Same version as the Docker image (`python:3.12.6-slim`) and the CI, so the code behaves the same everywhere | Installer from [python.org](https://www.python.org/downloads/release/python-3126/) |
| **Git** | Version control: clone the repository, commit and push | `brew install git` |
| **Docker Desktop** | Builds and runs the images, runs PostgreSQL and Redis for local development. It also provides the local **Kubernetes** cluster and the `kubectl` command | Installer from [docker.com](https://www.docker.com/products/docker-desktop/), then enable Kubernetes in *Settings → Kubernetes* |
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
git switch dev
```

All the commands below are run from the root of the repository (the `photo-service/` folder). New work always starts from `dev` (see section 7).

## 3. Run the app locally (without Kubernetes)

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

### Start PostgreSQL and Redis
The app needs two PostgreSQL databases (one per shard) and Redis. Locally, they run in Docker containers:

```bash
docker run -d --name photo-db -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=photo -p 5432:5432 postgres:17
docker run -d --name photo-cache -p 6379:6379 redis:7.4
```

`POSTGRES_DB=photo` creates the database of shard 0. Once `photo-db` is ready (a few seconds), create the one of shard 1:

```bash
docker exec photo-db createdb -U postgres photo1
```

Locally, both shards live in the same PostgreSQL server, as two separate databases: the app does not see the difference.

The containers are created once. After a restart of Docker Desktop, start them again with `docker start photo-db photo-cache`.

### Create the `.env` file
The app reads its configuration from environment variables, or from a `.env` file at the root of the repository. This file is in `.gitignore`: it is never committed.

```bash
APP_VERSION=1.0
DATABASE_URL_0=postgresql://postgres:dev@localhost:5432/photo
DATABASE_URL_1=postgresql://postgres:dev@localhost:5432/photo1
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-change-me
```

| Variable | Role |
|---|---|
| `DATABASE_URL_0`, `DATABASE_URL_1` | the two shards |
| `REDIS_URL` | the cache. Without it, the app works without cache |
| `SECRET_KEY` | signs the session cookie |
| `APP_VERSION` | the version displayed by the app |
| `URL_PREFIX` | optional, serves the app under a path (used by test online: `/test`) |

The app reads `.env` only when it starts: restart it after a change.

### Create the tables
The schema is managed by Alembic (see the *Database* page). The migrations are applied to **each** shard:

```bash
set -a; source .env; set +a
DATABASE_URL="$DATABASE_URL_0" alembic upgrade head
DATABASE_URL="$DATABASE_URL_1" alembic upgrade head
```

The first line loads `.env` into the terminal, so that `$DATABASE_URL_0` is defined. Running the migrations again does nothing if the databases are up to date.

### Start the app
Two ways, depending on what you need:

```bash
# Flask development server (quick, for coding)
python app.py

# gunicorn, the production server used in the Docker image
gunicorn app:app --bind 0.0.0.0:8080 --workers=1 --threads=1
```

Then open `http://localhost:8080` and log in with any username. In another terminal:

```bash
curl http://localhost:8080/health
```

The version can be set with an environment variable: `APP_VERSION=1.0 python app.py`. Without it, the app falls back to a `.env` file if there is one, then to its default value.

### Run the tests

```bash
pytest
```

The tests do not need PostgreSQL or Redis. All the tests must pass before pushing: the CI runs the same command and blocks the pipeline if one fails.

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
docker run --rm -p 8080:8080 --env-file .env \
  -e DATABASE_URL_0=postgresql://postgres:dev@host.docker.internal:5432/photo \
  -e DATABASE_URL_1=postgresql://postgres:dev@host.docker.internal:5432/photo1 \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  photo-service:dev-local
```

- `-p 8080:8080` publishes the port: `<port on your machine>:<port in the container>`;
- `--rm` deletes the container when it stops (Ctrl+C), so stopped containers don't pile up;
- inside a container, `localhost` is the container itself. `host.docker.internal` is the Mac, where PostgreSQL and Redis are published.

The machine name displayed is the container ID, and the version is the one passed with `--build-arg`.

> **Note:** on a Mac with an Apple chip, images built by the CI (on GitHub's Intel machines) run through emulation. Docker shows a platform warning, but the app works.

## 5. The dev environment (local cluster)

The `dev` environment runs on the Kubernetes cluster of Docker Desktop, with the same architecture as online: 3 app pods, 2 PostgreSQL shards with a replica each, and Redis with a replica.

### Prerequisites
- Kubernetes is enabled in Docker Desktop, and `kubectl` points to it:
  `kubectl config current-context` must return `docker-desktop`;
- The **ingress-nginx** controller is installed in the cluster (once per cluster, see the *Cluster Setup* page).

### First deployment
Once per cluster:

```bash
kubectl apply -f manifests/namespaces.yaml
kubectl apply -k manifests/overlays/dev
kubectl get pods -n 21359-dev
```

Wait until the 9 pods are `Running`. The image is downloaded from GHCR; the tag in the overlay may be old until the next CI deployment.

### Check that it works

```bash
curl http://dev.photo.localhost/health
```

Domains ending in `.localhost` automatically point to your own machine: no configuration needed.

### Update the dev environment
dev is updated by the CI: every merge into the `dev` branch deploys the new image on the local cluster (job `deploy-dev`). Nothing to do by hand.

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
- Draw diagrams with plain ASCII characters (`+ - | v >`): other symbols can be missing from the font and break the alignment;
- For every technical choice, explain **why**, not only **how**.

## 7. How changes reach dev, test and prod

Nobody deploys by hand: every environment is updated by the CI pipeline.

### The usual workflow

1. Start from an up-to-date `dev` and create a branch:
```bash
   git switch dev
   git pull
   git switch -c feature/my-change      # or fix/my-fix
```
2. Make your change and run the tests locally:
```bash
   pytest
```
3. Commit with a short message describing **what** changes (for example `Add photo upload route`), then push the branch;
4. Open a pull request into **`dev`** and merge it. The CI deploys it to dev: check it on `http://dev.photo.localhost`;
5. When `dev` is ready to be released, open a pull request from **`dev`** into **`main`** and merge it. The CI deploys it to test: check it on `http://team1.laboinfo-ecam.be/test`;
6. In the **Actions** tab, the run waits on `deploy-prod`: click **Review deployments → Approve and deploy**. The same image goes to `http://team1.laboinfo-ecam.be`.

The displayed version is the hash of the commit.

### Good to know
- **`main` and `dev` are protected:** they cannot be deleted, and force pushes are refused. Changes reach them through pull requests;
- **Before a rebase or a merge, pull the base branch.** A pull request merged on GitHub does not update the local copy of `dev`;
- **On any other branch,** the tests and the build still run, but nothing is deployed. A branch is a safe place to try something out;
- **If a test fails, nothing is built or deployed**, and the commit gets a ❌ in the Actions tab;
- **The deployment jobs run on the self-hosted runner** of the maintainer's Mac. It is configured once on that machine only: a new developer does not need to install it. If the runner is stopped, the deployments wait until it is started again.

For the details of each job, the technical choices and the troubleshooting guide, see the *CI/CD* page.

## 8. Useful buttons

Two workflows are started by hand in the **Actions** tab of the repository:

- **Refresh test database**: copies production into test, with anonymized usernames. The new usernames and their number of photos are shown in the step *Show the logs*: use one of them to log in to test;
- **Redeploy online**: rebuilds test, prod and monitoring from `main`, after approval. Only needed if the online namespace was wiped.

## 9. Monitoring and scaling

- The dashboard is public: http://team1.laboinfo-ecam.be/grafana. It shows test and prod; dev is not monitored;
- To scale the online services, install [Headlamp](https://headlamp.dev) (`brew install --cask headlamp`) and use the context `team1@cluster-sc`. A manual scale is undone by the next deployment, which sets the number of replicas back to the value in Git. See *Monitoring*.