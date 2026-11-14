# Welcome to Photo Service

GitHub : [github.com/melmaado/photo-service](https://github.com/melmaado/photo-service)

## Goal of the project

The objective of the app is to provide a photo storage service that can detect duplicates.
The deployment uses Kubernetes (k8s), using a pipeline dev -> test -> prod.

Users log in with a username, upload photos, see their duplicates side by side, mark favorites, open a photo in a lightbox, download or delete it.

## Stack

| Layer | Tools |
|---|---|
| Application | Python / Flask, gunicorn |
| Data | PostgreSQL (2 shards, each with a replica), Alembic migrations, Redis cache (with a replica) |
| Packaging | Docker, GHCR |
| Clusters | Kubernetes: Docker Desktop locally, OVH online |
| Configuration | Kustomize (base + overlays) |
| Entry point | ingress-nginx (local), Gateway API (online) |
| CI/CD | GitHub Actions, self-hosted runner, protected `production` environment |
| Monitoring | Prometheus, Grafana |

## Environments

| Environment | Where | URL |
|---|---|---|
| dev | local cluster (Docker Desktop) | http://dev.photo.localhost |
| test | online cluster (OVH) | http://team1.laboinfo-ecam.be/test |
| prod | online cluster (OVH) | http://team1.laboinfo-ecam.be |
| Monitoring dashboard | online cluster (OVH) | http://team1.laboinfo-ecam.be/grafana |

A change goes `feature/*` -> pull request -> `dev` -> release pull request -> `main` -> test -> manual approval -> prod. See *CI/CD*.

## Documentation

| Page | Content |
|---|---|
| *Onboarding* | install the tools, run the app locally, the daily workflow |
| *Cluster Setup* | build the local and online clusters, move to a cloud cluster |
| *CI/CD* | the pipeline, its jobs, the technical choices, troubleshooting |
| *Database* | data model, migrations, replication, sharding, cache, test data refresh |
| *Monitoring* | metrics, Prometheus, Grafana, scaling |

## Project progress

The project features different milestones:

| # | Date | Goal | Points | Status |
|---|------|------|--------|--------|
| 1 | 13 Oct 2026 | A simple application is replicated and accessible through an Ingress Controller (no database required) | 5 | Done |
| 2 | 20 Oct 2026 | A push to Git triggers unit tests, image build and a rollout in the test environment | 5 | Done |
| 3 | 03 Nov 2026 | A dashboard monitors the services and allows scaling them | 5 | Done |
| – | 17 Nov 2026 | **Final evaluation**: live pipeline demo (Git push → Production), infrastructure review and documentation review | 35 | Pending |