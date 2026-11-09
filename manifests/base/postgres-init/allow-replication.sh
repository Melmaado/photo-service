#!/bin/bash
echo "host replication all all scram-sha-256" >> "$PGDATA/pg_hba.conf"