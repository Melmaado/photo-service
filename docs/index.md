# Welcome to Photo Service

GitHub : [github.com/melmaado/photo-service](https://github.com/melmaado/photo-service)

## Goal of the project

The objective of the app is to provide a photo storage service that can detect duplicates.
The deployment uses Kubernetes (k8s), using a pipeline dev->test->prod.

The stack used is: Python/Flask, Docker, Kubernetes, Ingress Nginx

## Project progress

The project features different milestones:

| # | Date | Goal | Points | Status |
|---|------|------|--------|--------|
| 1 | 13 Oct 2026 | A simple application is replicated and accessible through an Ingress Controller (no database required) | 5 | Done |
| 2 | 20 Oct 2026 | A push to Git triggers unit tests, image build and a rollout in the test environment | 5 | Pending |
| 3 | 03 Nov 2026 | A dashboard monitors the services and allows scaling them | 5 | Pending |
| – | 17 Nov 2026 | **Final evaluation**: live pipeline demo (Git push → Production), infrastructure review and documentation review | 35 | Pending |