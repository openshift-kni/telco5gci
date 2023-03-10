#!/usr/bin/env python3

import argparse
import json
import os
import re
import requests
import sys

ansi = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')
color_code_pattern = re.compile(r'\033\[[0-9;]*m')
ttime = re.compile(r'([\d\.]+) seconds')
SUITES = [
    "vrf",
    "sctp",
    "serial",
    "sriov",
    "gatekeeper",
    "tuningcni",
    "pao",
    "metallb",
    "xt_u32",
    "sro",
    "performance",
    "ptp",
    "bondcni",
    "ovs_qos",
    "s2i",
    "dpdk",
    "fec",
    "multinetworkpolicy",
]


def clean_line(line):
    line = color_code_pattern.sub('', line.strip())
    # line = line.strip('\n')
    return line


def get_time(x):
    if "seconds" not in "".join(x):
        return "0"
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
        line = clean_line(line)
        for t in SUITES:
            if (t in line and re.search(rf'^\W*(?:\[r[fe][fe]_id[^]]*\])?(?:\[test_id[^]]*\])?\W*({t})\W', line)) or (
                    t == 'metallb' and 'MetalLB' in line):
                name = line
                if len(x) > (ind + 1):
                    name += " " + clean_line(x[ind + 1])
                name = name.strip('"')
                break
        if name:
            break
    # name = ansi.sub('', name)
    return name


def get_result(x):
    for line in x:
        line = clean_line(line)
        if "• Failure " in line:
            return "fail"
        if "S [SKIPPING]" in line:
            return "skip"
        if "•" in line:
            return "pass"
    return "skip"


def get_artifact_link(url):
    if '/artifacts' in url:
        url = url.split('/artifacts')[0]
        return url
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


def get_files_by_url(url):
    link = get_artifact_link(url)
    if not link:
        print(f"Can't get artifacts link from URL {url}")
        sys.exit(1)
    build_id = url.strip("/").split("/")[-1]
    art_link = link + "/artifacts/e2e-telco5g-cnftests/telco5g-cnf-tests/build-log.txt"
    nf = requests.get(art_link)
    if not nf or not nf.ok:
        print(f"Can't get results for build {build_id}")
        return
    f_path = os.path.join("/tmp", f"build_log_{build_id}.log")
    with open(f_path, "w") as g:
        g.write(nf.text)
    return f_path


def parse_data(fpath):
    res = {}
    with open(fpath, encoding="utf-8") as f:
        text = f.readlines()
    start = 0
    for ind, line in enumerate(text):
        if "Running Suite: CNF Features e2e integration tests" in line:
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
                and "[BeforeEach]" not in line
                    and '[It]' not in line):
                chunk.append(line)

    for z in tests_list:
        name = get_name(z)
        if name:
            time = get_time(z)
            test_result = get_result(z)
            res[name] = {"time": time, "result": test_result}

    return res


def work_out(result, out, format):
    with open(out, "w") as f:
        if format == "json":
            json.dump(result, f)


def parse_files(path):
    data = {}
    file_data = parse_data(path)
    data.update(file_data)
    return data


def parse_url(job_url):
    file_p = get_files_by_url(job_url)
    return parse_files(file_p)


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
        "-o", "--output-file", default="/tmp/us_result.json",
        help="Output file for result. (default=/tmp/us_result.json)"
    )
    parser.add_argument(
        "-f", "--format", default="json", choices=["json"],
        help="Output file format (default=json)."
    )
    args = parser.parse_args()
    if args.job_url:
        result = parse_url(args.job_url)

    if args.path:
        result = parse_files(args.path)

    work_out(result, args.output_file, args.format)


if __name__ == '__main__':
    main()
