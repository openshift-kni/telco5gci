#!/usr/bin/env python3

# Author: Sagi Shnaidman (@sshnaidm), Red Hat.

import argparse
import json

from junitparser import JUnitXml, TestSuite


def get_stat(xml):

    result = {
        "total": 0,
        "pass": 0,
        "skip": 0,
        "fail": 0,
        "error": 0,
        "total_run": 0,
        "tests": {}
    }

    for t in xml:
        name = t.name
        result['total'] += 1

        if t.is_passed:
            result['pass'] += 1
            result['tests'][name] = 'pass'
        elif t.is_skipped:
            result['skip'] += 1
            result['tests'][name] = 'skip'
        elif t.result and t.result[0].type == 'Failure':
            result['fail'] += 1
            result['tests'][name] = 'fail'
        else:
            result['error'] += 1
            result['tests'][name] = 'error'
    result['total_run'] = result['total'] - result['skip']

    return result


def merge(xml_tests):
    all_tests = dict()
    flat = []
    for suite in xml_tests:
        if isinstance(suite, TestSuite):
            flat += [i for i in suite]
        else:
            flat.append(suite)
    for i in flat:
        name = i.name
        if name not in all_tests:
            all_tests[name] = i
        else:
            # Overwrite skipped tests with results
            if all_tests[name].is_skipped and not i.is_skipped:
                all_tests[name] = i
    return list(all_tests.values())


def main():
    parser = argparse.ArgumentParser(
        description="Extract tasks from a playbook."
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file. Default: cnf_result.json",
        default="cnf_result.json",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Files to extract tests from.",
    )
    args = parser.parse_args()

    all_xml = JUnitXml.fromfile(args.files[0])
    for i in args.files[1:]:
        all_xml += JUnitXml.fromfile(i)
    if len(args.files) > 1:
        all_xml = merge(all_xml)
    data = get_stat(all_xml)

    with open(args.output, "w") as f:
        f.write(json.dumps(data))


if __name__ == '__main__':
    main()
