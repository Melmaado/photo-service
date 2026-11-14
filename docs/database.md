# Database

## Overview
This application uses PostgreSQL to store user accounts and photos, and Redis as a cache in front of it.

## Data model

### Table users
| Column | Type | Note |
|---|---|---|
| id | INTEGER | primary key |
| username | TEXT | unique |
| created_at | TIMESTAMP | |

### Table photos
| Column | Type | Note |
|---|---|---|
| id | INTEGER | primary key |
| user_id | INTEGER | foreign key to users.id |
| filename | TEXT | |
| size | INTEGER | in bytes |
| pic_hash | TEXT | SHA-256, indexed with user_id |
| pic | BYTEA | the image itself |
| is_favorite | BOOLEAN | `FALSE` by default, added by the second migration |
| created_at | TIMESTAMP | |

## Design choices

### Users and login
Users log in with a username only, without a password. A user who logs in
with a new username gets a new account. The user id is kept in a signed
Flask session cookie, so each user only sees their own photos.
This keeps the application simple; the focus of the project is the infrastructure.
The username is also used to choose the database shard.

### Photo storage
The photos are stored in the database, not on a disk, for the following reasons: the application runs on 3 different pods, often on different machines, while a disk is attached to only one machine. If the pictures were on a disk, the 3 pods couldn't access all of them.
Furthermore, since all of the pods communicate with the database, they all have access to the pictures. The replication of the database creates copies of the pictures too, and sharding allows keeping each user's pictures in the same shard of the database as the user. Finally, the test refresh copies them as well.

### Duplicate detection
`pic_hash` is the SHA-256 of the photo bytes, computed at upload. Two photos with
the same `user_id` and the same `pic_hash` are duplicates.
There is no UNIQUE constraint: the goal is to find and compare existing duplicates,
not to block them at upload.
SHA-256 only finds exact copies: a resized or recompressed photo is not detected.

### Favorites
A user can mark a photo as favorite with the heart button. Favorites are shown
first in the list (`ORDER BY is_favorite DESC, created_at DESC`).

### Schema migrations
The schema is managed with Alembic. Each change is a versioned file in
`migrations/versions/`, written in plain SQL. `alembic upgrade head` applies
only the missing migrations, so it is safe to run at every deployment.

| Revision | Change |
|---|---|
| `701da9212420` | create the `users` and `photos` tables |
| `b37c3182b49a` | add `is_favorite` to `photos` |

At each deployment, an init container runs `alembic upgrade head` on both
shards before the app starts. If a migration fails, the init container fails,
the new pods never start and the old pods keep serving traffic.

Each migration has a `downgrade`, so it can be rolled back:

```bash
DATABASE_URL="$DATABASE_URL_0" alembic downgrade -1
DATABASE_URL="$DATABASE_URL_1" alembic downgrade -1
```

New columns are added with a default value, so the old version of the app
keeps working during a rolling update.

### Replication
PostgreSQL is deployed as a StatefulSet consisting of two pods using streaming replication:

- `postgres-0` acts as the primary. All write operations from the application arrive here, since the app establishes its connection to the primary pod by its DNS name (`postgres-0.postgres`, and `postgres-shard1-0.postgres-shard1` for shard 1).

- `postgres-1` serves as a read-only replica. During its initial startup, it clones the primary using `pg_basebackup` and then continuously applies changes as they stream in through the WAL (write-ahead log).

An init script appends a `replication` entry to `pg_hba.conf` on the primary, permitting the replica to establish a connection.

Each shard is replicated the same way.

### Sharding
Users are distributed across two independent PostgreSQL clusters (shards): `postgres` (shard 0) and `postgres-shard1` (shard 1), each running its own primary and replica.

The application determines which shard to use based on the username via `sha256(username)[0] % 2`. Because SHA-256 produces a consistent result on every pod and across all restarts, a given user (and all their photos) will always reside in the same shard. Python's built-in `hash()` is deliberately avoided, since its output differs between processes.

The sharding is done in the application: each shard is a normal PostgreSQL.
An alternative is Citus, a PostgreSQL extension that shards tables
automatically behind a coordinator node. It was not used because it adds
another component to run and the online cluster has little memory left.

### Cache
Photos are cached in Redis to avoid reading about 1 MB from PostgreSQL for
every thumbnail.

- Pattern: cache-aside. The app reads Redis first. On a miss, it reads
  PostgreSQL and stores the photo in Redis for 10 minutes.

- Key: `photo:<username>:<photo_id>`. The username is required because photo
  ids are only unique inside one shard, and it keeps users from reading
  each other's photos.

- Deleting a photo also deletes its key, so a deleted photo is never served.

- The response header `X-Cache` shows `HIT` or `MISS`.

- The 3 app pods share the same cache.

Redis runs as a StatefulSet with 2 pods: `redis-0` is the primary,
`redis-1` replicates it with `--replicaof`. Redis has no persistent volume:
it is a cache, so an empty restart only causes cache misses.
`maxmemory 100mb` with `allkeys-lru` removes the least recently used photos
when memory is full.

If Redis is down, the app keeps working: every Redis call is wrapped in a
`try/except` with a 0.5 second timeout, and the photo is read from PostgreSQL
instead. Pages are slower but nothing breaks.

## Test data refresh
The test environment can be filled with a copy of the production data, with
the **Refresh test database** button in GitHub Actions.

For each shard, a one-off pod (`manifests/jobs/refresh-test-db.yaml`) runs
`scripts/refresh-test-db.sh`:

1. `pg_dump` copies the production shard into the test shard.

2. Usernames are replaced by `user_<id>_<n>`, and file names by
   `photo_<id>.<extension>`.
   
3. The new names and the number of photos of each user are printed in the logs.

The fake username is chosen so that it lands in the **same shard** as the
original user: the SQL computes `sha256(name)[0] % 2` like the app and tries
`n = 0, 1, 2…` until it matches. Without this, the anonymized users could not
log in. The photos and their hashes are kept, so duplicates still work in test.

To log in to test after a refresh, open the run of the workflow and read the
step **Show the logs**.

## Limitations
- Storing photos in the database makes it grow quickly. A production setup would store the files in object storage (such as AWS S3) and keep only their path in the database.

- There is no password: anyone who knows a username can access that user's photos. A production setup would add real authentication.

- No automatic failover is in place: should the primary go down, the replica retains all data but won't promote itself on its own. Handling that would require a tool such as Patroni or CloudNativePG.

- The application talks exclusively to the primary, read queries are not distributed to the replica.

- Introducing a new shard means changing `%2` to `%3`, which shifts the majority of users into a different shard. Their data would then need to be migrated (a resharding operation). Using consistent hashing would reduce how many users have to be moved.

- There are no backups. If the volumes are deleted, the redeploy script recreates empty databases. A production setup would run `pg_dump` regularly to object storage.

- Redis has no automatic failover (Redis Sentinel would add it). If `redis-0` is down, the app falls back to PostgreSQL, but nothing is cached until it comes back.

- Redis has no password; it is only reachable from inside the cluster.

- The anonymization only changes usernames and file names. The photos themselves are copied as they are, so test contains the real images.