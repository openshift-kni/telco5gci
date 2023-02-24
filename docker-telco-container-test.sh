#!/bin/bash

CMD_RUN=${1:-"python3 /data/parse_tests.py -p /data/tests/ginkgo-v1-build.output -o /data/test-result-container.json"}
docker exec testpy36 bash -c "${CMD_RUN}"
