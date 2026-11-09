# Database

## Overview
This application uses PostgreSQL. It stores two kinds of data: user accounts and photos.

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
SHA-256 only finds exact copies. A later migration adds a perceptual hash to also
find similar photos.

### Schema migrations
The schema is managed with Alembic. Each change is a versioned file in
`migrations/versions/`, written in plain SQL. `alembic upgrade head` applies
only the missing migrations, so it is safe to run at every deployment.

### Replication
PostgreSQL is deployed as a StatefulSet consisting of two pods using streaming replication:

- `postgres-0` acts as the primary. All write operations from the application arrive here, since the app establishes its connection to the primary pod by its DNS name (`postgres-0.postgres`, and `postgres-shard1-0.postgres-shard1` for shard 1).

- `postgres-1` serves as a read-only replica. During its initial startup, it clones the primary using `pg_basebackup` and then continuously applies changes as they stream in through the WAL (write-ahead log).

An init script appends a `replication` entry to `pg_hba.conf` on the primary, permitting the replica to establish a connection.

Each shard is replicated the same way.

### Sharding
Users are distributed across two independent PostgreSQL clusters (shards): `postgres` (shard 0) and `postgres-shard1` (shard 1), each running its own primary and replica.

The application determines which shard to use based on the username via `sha256(username)[0] % 2`. Because SHA-256 produces a consistent result on every pod and across all restarts, a given user (and all their photos) will always reside in the same shard. Python's built-in `hash()` is deliberately avoided, since its output differs between processes.

With each deployment, the migration init container executes `alembic upgrade head` against both shards.

## Limitations
- Storing photos in the database makes it grow quickly. A production setup would store the files in object storage (such as AWS S3) and keep only their path in the database.

- There is no password: anyone who knows a username can access that user's photos. A production setup would add real authentication.

- No automatic failover is in place: should the primary go down, the replica retains all data but won't promote itself on its own. Handling that would require a tool such as Patroni or CloudNativePG.

- The application talks exclusively to the primary, read queries are not distributed to the replica.

- Introducing a new shard means changing `%2` to `%3`, which shifts the majority of users into a different shard. Their data would then need to be migrated (a resharding operation). Using consistent hashing would reduce how many users have to be moved.