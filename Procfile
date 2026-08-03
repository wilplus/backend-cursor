web: sh bin/railway-web.sh
# Durable pipeline worker (async-queue work). Railway runs one process per
# service: the web service uses the default `web`, and the worker service
# sets Custom Start Command `sh bin/railway-worker.sh` (see the script
# header + docs/ASYNC-PIPELINE-QUEUE.md).
worker: sh bin/railway-worker.sh
