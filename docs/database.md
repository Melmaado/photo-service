# Database

## Overview
This application uses PostgreSQL. It stores two kinds of data: user accounts and photos.

## Data model

### Table users
| Column | Type | Note |
|---|---|---|
| id | INTEGER | primary key |
| username | TEXT | unique |
| hashed_password | TEXT | **never** the plain password |
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

### Photo Storage
The photos are stored in the database, not on a disk for the following reasons: the application runs on 3 different pods, often on different machines, while a disk is attached to only one machine. If the pictures were on a disk, the 3 pods couldn't access all of them.
Furthermore, since all of the pods communicate with the database, they all have access to the pictures. The replication of the database creates copies of the pictures too, and sharding allows keeping each user's pictures in the same shard of the database as the user. Finally, the test refresh copies them as well.

### Duplicate detection
`pic_hash` is the SHA-256 of the photo bytes, computed at upload. Two photos with
the same `user_id` and the same `pic_hash` are duplicates.
There is no UNIQUE constraint: the goal is to find and compare existing duplicates,
not to block them at upload.
SHA-256 only finds exact copies. A later migration adds a perceptual hash to also
find similar photos.

### Passwords
In the `users` table, only the hash of the password is stored. The password is hashed during sign-up using `generate_password_hash()` and verified during login using `check_password_hash()`, both from `werkzeug.security`. This ensures that if the database leaks, the real passwords can't be read directly. Each hash includes a random salt so two identical passwords get two different hashes. 

## Limitations
Storing photos in the database makes it grow quickly. A production setup would store
the files in object storage (such as AWS S3) and keep only their path in the database.