#!/bin/bash

./parse_log.py -u $1 -o /tmp/run_full_log.txt
./j2html.py -f json /tmp/run_full_log.txt -o /tmp/full.html
echo "See full result in /tmp/full.html"
