#!/usr/bin/env python3

import argparse
import json
import os
import re
import requests
import sys

ansi = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")
color_code_pattern = re.compile(r"\033\[[0-9;]*m")
ttime = re.compile(r"([\d\.]+) seconds")
spex_time = re.compile(r"Ran \d+ of \d+ Specs in ([\d\.]+) seconds")
validation_re = r"^\W*(?:validation)?\W*(%s)\W"
test_re = r"^\W*(?:\[r[fe][fe]_id[^]]*\])?(?:\[test_id[^]]*\])?\W*(%s)\W"

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
    line = color_code_pattern.sub("", line.strip())
    # line = line.strip('\n')
    return line


def get_time(x):
    if "seconds" not in "".join(x):
        return "0"
    found = ttime.search("".join(x))
    if found:
        return found.group(1)


def get_name(x, validation=False):
    whole = "".join(x)
    regex = validation_re if validation else test_re

    for t in SUITES:
        if t in whole:
            break
    else:
        return None
    name = ""
    for ind, line in enumerate(x):
        line = clean_line(line)
        for t in SUITES:
            if (t in line and re.search(regex % t, line)) or (
                t == "metallb" and "MetalLB" in line
            ):
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


def spex_found(x):
    return spex_time.search("\n".join(x))


def update_spex(r, x):
    total_time = float(spex_time.search("\n".join(x)).group(1))
    cycle_time = r["total_cycle_time"]
    del r["total_cycle_time"]
    leftover = total_time - cycle_time
    fails = {k: v for k, v in r.items() if v["result"] == "fail"}
    if not fails:
        return r
    time_add = leftover / len(fails)
    for k, _ in fails.items():
        r[k]["time"] += time_add
    return r


def get_artifact_link(url):
    if "/artifacts" in url:
        url = url.split("/artifacts")[0]
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


def parse_test_data(fpath):
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
                    and "[It]" not in line):
                chunk.append(line)

    for z in tests_list:
        name = get_name(z)
        if name:
            time = get_time(z)
            test_result = get_result(z)
            res[name] = {"time": time, "result": test_result}

    return res


def parse_validation_data(fpath):
    res = {"total_cycle_time": 0}
    with open(fpath, encoding="utf-8") as f:
        text = f.readlines()
    start = 0
    end = len(text)
    t_started = False
    for ind, line in enumerate(text):
        if "Running Suite: CNF Features e2e validation" in line:
            t_started = True
        if t_started and "------------------------------" in line:
            start = ind
            break
    else:
        return res
    for ind, line in enumerate(text):
        if "Running Suite: CNF Features e2e integration tests" in line or (
            "Running Suite: CNF Features e2e setup" in line
        ):
            end = ind
            break

    need = text[start:end]
    tests_list = []
    chunk = []
    for line in need:
        if "------------------------------" in line or (
            "Running Suite: CNF Features e2e validation" in line
        ):
            if chunk:
                tests_list.append(chunk)
            chunk = []
        else:
            if ("/tmp" not in line
                and "[BeforeEach]" not in line
                    and "[It]" not in line):
                chunk.append(line)

    for z in tests_list:
        name = get_name(z, validation=True)
        if name:
            time = float(get_time(z))
            test_result = get_result(z)
            if name not in res:
                res[name] = {"time": time, "result": test_result}
            else:
                full_test_time = res[name]["time"] + time
                res[name] = {"time": full_test_time, "result": test_result}
            res["total_cycle_time"] += time
        if spex_found(z):
            res = update_spex(res, z)
            res["total_cycle_time"] = 0
    del res["total_cycle_time"]
    return res


def work_out(result, out, format):
    with open(out, "w") as f:
        if format == "json":
            json.dump(result, f)


def parse_files(path, test_type):
    if test_type == "validations":
        file_data = parse_validation_data(path)
    elif test_type == "tests":
        file_data = parse_test_data(path)
    elif test_type == "all":
        file_data = parse_validation_data(path)
        file_data.update(parse_test_data(path))
    return file_data


def parse_url(job_url, test_type):
    file_p = get_files_by_url(job_url)
    return parse_files(file_p, test_type)


def main():
    parser = argparse.ArgumentParser(
        __doc__,
        description="Parse Ginkgo test log, i.e. deploy_and_test_sriov.log"
    )
    parser.add_argument(
        "-u",
        "--job-url",
        help="URL of the job from Prow.",
    )
    parser.add_argument("-p", "--path", help="File path with ginkgo log.")
    parser.add_argument(
        "-o",
        "--output-file",
        default="/tmp/us_result.json",
        help="Output file for result. (default=/tmp/us_result.json)",
    )
    parser.add_argument(
        "-f",
        "--format",
        default="json",
        choices=["json"],
        help="Output file format (default=json).",
    )
    parser.add_argument(
        "-t",
        "--test-type",
        default="all",
        choices=["all", "validations", "tests"],
        help=(
            "What to extract from logs. Choose from %(choices)s. "
            "Default: %(default)s"
        ),
    )
    args = parser.parse_args()
    if args.job_url:
        result = parse_url(args.job_url, args.test_type)

    if args.path:
        result = parse_files(args.path, args.test_type)

    work_out(result, args.output_file, args.format)


if __name__ == "__main__":
    main()
