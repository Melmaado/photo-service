# Welcome to Photo Service

GitHub : [github.com/melmaado/photo-service](https://github.com/melmaado/photo-service)

## Goal of the project

The objective of the app is to provide a photo storage service that can detect duplicates.
The deployment uses Kubernetes (k8s), using a pipeline dev->test->prod.

The stack used is: Python/Flask, Docker, Kubernetes (Docker Desktop locally, OVH online), Kustomize, GitHub Actions and GHCR, Gateway API (online) and ingress-nginx (local), Prometheus and Grafana.

## Live services

| What | URL |
|---|---|
| App (prod) | http://team1.laboinfo-ecam.be |
| Monitoring dashboard | http://team1.laboinfo-ecam.be/grafana |

The test environment runs on the same cluster but is not exposed publicly (see *Cluster Setup*).

## Project progress

The project features different milestones:

| # | Date | Goal | Points | Status |
|---|------|------|--------|--------|
| 1 | 13 Oct 2026 | A simple application is replicated and accessible through an Ingress Controller (no database required) | 5 | Done |
| 2 | 20 Oct 2026 | A push to Git triggers unit tests, image build and a rollout in the test environment | 5 | Done |
| 3 | 03 Nov 2026 | A dashboard monitors the services and allows scaling them | 5 | Done |
| – | 17 Nov 2026 | **Final evaluation**: live pipeline demo (Git push → Production), infrastructure review and documentation review | 35 | Pending |