#!/usr/bin/env python3

import argparse
import json
import os
import re
import requests
import sys

ansi = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')
ttime = re.compile(r'([\d\.]+) seconds')
SUITES = ["vrf",
          "sctp",
          "serial",
          "sriov",
          "gatekeeper",
          "tuningcni",
          "pao",
          "Metallb",
          "xt_u32",
          "sro",
          "performance",
          "ptp",
          "bondcni",
          "ovs_qos",
          "s2i",
          "dpdk",
          "fec"]


def get_time(x):
    if "seconds" not in "".join(x):
        return None
    found = ttime.search("".join(x))
    if found:
        return found.group(1)


def get_name(x):
    whole = "".join(x)

    for t in SUITES:
        if t in whole:
            break
    else:
        return None
    name = ""
    for ind, line in enumerate(x):
        for t in SUITES:
            if t in line and re.search(rf'^\W*({t})', line):
                name = line.strip()
                if len(x) > (ind + 1):
                    name += " " + x[ind+1].strip()
                break
        if name:
            break
    name = ansi.sub('', name)
    return name


def get_artifact_link(url):
    q = requests.get(url)
    if not q.ok:
        return None
    ff = q.text
    link = None
    art_re = re.compile(r'<a href="([^"]+)">Artifacts</a>')
    for line in ff.split("\n"):
        if art_re.search(line):
            link = art_re.search(line).group(1)
    if not link:
        return None
    return link


def get_files_by_url(url, tests=None):
    files = []
    link = get_artifact_link(url)
    if not link:
        print(f"Can't get artifacts link from URL {url}")
        sys.exit(1)
    build_id = url.strip("/").split("/")[-1]
    if tests and not isinstance(tests, list):
        tests = [tests]
        if tests == ["all"]:
            tests = SUITES
        for test in tests:
            art_link = link + \
                f"artifacts/e2e-telco5g/telco5g-cnf-tests/artifacts/deploy_and_test_{test}.log"
            nf = requests.get(art_link)
            if not nf or not nf.ok and tests == SUITES:
                continue
            elif not nf or not nf.ok:
                print(f"Can't get results for test {test}")
                continue
            f_path = os.path.join("/tmp", f"{build_id}_{test}")
            with open(f_path, "w") as g:
                g.write(nf.text)
            files.append(f_path)
    return files


def parse_data(fpath):
    res = {}
    with open(fpath) as f:
        text = f.readlines()
    start = 0
    t_started = False
    for ind, line in enumerate(text):
        if "Running Suite: CNF Features e2e integration tests" in line:
            t_started = True
        if t_started and "------------------------------" in line:
            start = ind
            break
    else:
        return res

    need = text[start:]
    tests_list = []
    chunk = []
    for line in need:
        if "------------------------------" in line:
            if chunk:
                tests_list.append(chunk)
            chunk = []
        else:
            if ("/tmp" not in line
                and "BeforeEach" not in line
                    and '[It]' not in line):
                chunk.append(line)

    for z in tests_list:
        name = get_name(z)
        if name:
            time = get_time(z)
            if time:
                res[name] = time
            else:
                res[name] = 0

    return res


def work_out(result, out, format):
    with open(out, "w") as f:
        if format == "json":
            json.dump(result, f)


def parse_files(paths, test_suite, output_file, format):
    data = {}
    if not isinstance(paths, list):
        paths = [paths]
    for p in paths:
        file_data = parse_data(p)
        data.update(file_data)
    return data


def parse_url(job_url, test_suite, output_file, format):
    files = get_files_by_url(job_url, test_suite)
    return parse_files(files, test_suite, output_file, format)


def main():
    parser = argparse.ArgumentParser(
        __doc__,
        description="Parse Ginkgo test log, i.e. deploy_and_test_sriov.log")
    parser.add_argument(
        "-u", "--job-url", help="URL of the job from Prow.",
    )
    parser.add_argument(
        "-p", "--path", help="File path with ginkgo log."
    )
    parser.add_argument(
        "-t",
        "--test-suite",
        choices=SUITES + ['all'],
        default='all',
        help=(
            "Test suite to parse. "
            f"Default 'all'. "
            f"Choose from {SUITES + ['all']}"
        )
    )
    parser.add_argument(
        "-o", "--output-file", default="/tmp/us_result.json",
        help="Output file for result. (default=/tmp/us_result.json)"
    )
    parser.add_argument(
        "-f", "--format", default="json", choices=["json"],
        help="Output file format (default=json)."
    )
    args = parser.parse_args()
    if args.job_url:
        result = parse_url(args.job_url, args.test_suite,
                           args.output_file, args.format)

    if args.path:
        result = parse_files(args.path, args.test_suite,
                             args.output_file, args.format)

    work_out(result, args.output_file, args.format)

    # srt = sorted(res, key=lambda x: float(res[x]), reverse=True)
    # res[srt[0]]
    # for i in srt[:5]:
    #     print(i, res[i])


if __name__ == '__main__':
    main()
