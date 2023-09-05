#!/usr/bin/env python3

# Author: Sagi Shnaidman (@sshnaidm), Red Hat.
# This is heavily inspired by subunit2html.py tool:
# https://github.com/openstack/os-testr/blob/master/os_testr/subunit2html.py

import argparse
import codecs
import json
import re
from jinja2 import Template

from xml.sax import saxutils
from junitparser import JUnitXml, TestSuite


HTML_TMPL = r"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<!--?xml version="1.0" encoding="UTF-8"?-->
<html xmlns="http://www.w3.org/1999/xhtml" xmlns="http://www.w3.org/1999/xhtml"><head>
    <title>{{ title }}</title>
    <meta name="generator" content="{{ generator }}" />
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    {{ stylesheet }}
</head>
<body style="font-family: verdana, arial, helvetica, sans-serif; font-size: 80%;">
{{ heading }}
{{ report }}
{{ ending }}
</body>
</html>
"""
STYLESHEET_TMPL = """
<style>body {
font-family: verdana, arial, helvetica, sans-serif; font-size: 80%;
}
a.popup_link:hover {
color: red;
}
</style>
"""

HEADING_TMPL = """<div class="heading" style="margin-top: 0ex; margin-bottom: 1ex;">
<h1 style="font-size: 26pt; color: gray;">{{ title }}</h1>
{{ parameters }}
<p class="description" style="margin-top: 4ex; margin-bottom: 6ex;">{{ description }}</p>
</div>
"""
HEADING_ATTRIBUTE_TMPL = """
<p class="attribute" style="margin-top: 1ex; margin-bottom: 0; font-size:large;"><strong>{{ name }}:</strong> {{ value }}</p>
"""
REPORT_TMPL = """
<p id="show_detail_line" style="margin-top: 3ex; margin-bottom: 1ex;">Show
<a href="javascript:showCase(0)">Summary</a>
<a href="javascript:showCase(1)">Failed</a>
<a href="javascript:showCase(2)">All</a>
</p>
<table id="result_table" style="font-size: 110%; width: 100%; border-collapse: collapse; border: 1px solid #777;">
<colgroup>
<col align="left" />
<col align="right" />
<col align="right" />
<col align="right" />
<col align="right" />
<col align="right" />
<col align="right" />
<col align="right" />
<col align="right" />
</colgroup>
<tbody><tr id="header_row" style="font-weight: bold; color: white;" bgcolor="#777">
    <td style="padding: 2px; border: 1px solid #777;">Test Group/Test case</td>
    <td style="padding: 2px; border: 1px solid #777;">Time</td>
    <td style="padding: 2px; border: 1px solid #777;">Count</td>
    <td style="padding: 2px; border: 1px solid #777;">Pass</td>
    <td style="padding: 2px; border: 1px solid #777;">Fail</td>
    <td style="padding: 2px; border: 1px solid #777;">Error</td>
    <td style="padding: 2px; border: 1px solid #777;">Skip</td>
    <td style="padding: 2px; border: 1px solid #777;">View</td>
    <td style="padding: 2px; border: 1px solid #777;"> </td>
</tr>
{{ test_list }}
<tr id="total_row" style="font-weight: bold;">
    <td style="padding: 2px; border: 1px solid #777;">Total</td>
    <td style="padding: 2px; border: 1px solid #777;">{{ total_time }}</td>
    <td style="padding: 2px; border: 1px solid #777;">{{ count }}</td>
    <td style="padding: 2px; border: 1px solid #777;">{{ Pass }}</td>
    <td style="padding: 2px; border: 1px solid #777;">{{ fail }}</td>
    <td style="padding: 2px; border: 1px solid #777;">{{ error }}</td>
    <td style="padding: 2px; border: 1px solid #777;">{{ skip }}</td>
    <td style="padding: 2px; border: 1px solid #777;">&nbsp;</td>
    <td style="padding: 2px; border: 1px solid #777;">&nbsp;</td>
</tr>
</tbody></table>
"""
REPORT_CLASS_TMPL = r"""
<tr class="{{ style }}">
    <td class="testname" style="width: 40%; padding: 2px; border: 1px solid #777;">{{ desc }}</td>
    <td class="small" style="width: 40px; padding: 2px; border: 1px solid #777;">{{ time_suite_total }}</td>
    <td class="small" style="width: 40px; padding: 2px; border: 1px solid #777;">{{ count }}</td>
    <td class="small" style="width: 40px; padding: 2px; border: 1px solid #777;">{{ Pass }}</td>
    <td class="small" style="width: 40px; padding: 2px; border: 1px solid #777;">{{ fail }}</td>
    <td class="small" style="width: 40px; padding: 2px; border: 1px solid #777;">{{ error }}</td>
    <td class="small" style="width: 40px; padding: 2px; border: 1px solid #777;">{{ skip }}</td>
    <td class="small" style="width: 40px; padding: 2px; border: 1px solid #777;"><a href="javascript:showClassDetail('{{ cid }}',{{ count }})"
>Detail</a></td>
    <td style="padding: 2px; border: 1px solid #777;"> </td>
</tr>
"""
REPORT_TEST_WITH_OUTPUT_TMPL = r"""
<tr id="{{ tid }}" class="{{ Class }}">
    <td class="{{ style }}">{{ desc }}</div></td>
    <td style="padding: 2px; border: 1px solid #777;">{{ test_time }}</td>
    <td colspan="7" align="left" style="padding: 2px; border: 1px solid #777;">
    <!--css div popup start-->
    <a class="popup_link" onfocus="this.blur();" href="javascript:showTestDetail('div_{{ tid }}')">
        {{ status }}</a>
    <div id="div_{{ tid }}" class="popup_window" style="display: none; overflow-x: scroll; background-color: #E6E6D6; font-family: monospace; font-size: 10pt; padding: 10px;" align="left">
        <div style="color: red; cursor: pointer;" align="right">
        <a onfocus="this.blur();" onclick="document.getElementById('div_{{ tid }}').style.display = 'none' ">
           [x]</a>
        </div>
        <pre style="font-size: 80%;">
        {{ script }}
        </pre>
    </div>
    <!--css div popup end-->
    </td>
</tr>
"""

REPORT_TEST_NO_OUTPUT_TMPL = r"""
<tr id='{{ tid }}' class='{{ Class }}'>
    <td class='{{ style }}'><div class='testcase'>{{ desc }}</div></td>
    <td colspan='6' align='center'>{{ status }}</td>
</tr>
"""  # variables: (tid, Class, style, desc, status)

REPORT_TEST_OUTPUT_TMPL = r"""
{{ id }}: {{ output }}
"""
ENDING_TMPL = """<div id='ending'>&nbsp;</div>"""
DEFAULT_TITLE = "CNF Test Report"
DEFAULT_DESCRIPTION = ""


def time_format(t):
    if t == 0:
        return "0"
    if t > 1:
        return f"{t:.0f}"
    return f"{t:.1g}"


class HTMLReport:
    def __init__(self, args):
        if args.format == "xml":
            all_xml = JUnitXml.fromfile(args.files[0])
            for i in args.files[1:]:
                all_xml += JUnitXml.fromfile(i)
            if len(args.files) > 1:
                all_xml = self.merge(all_xml)
            if isinstance(all_xml, JUnitXml):
                all_xml = self.merge([i for i in all_xml])
            data = self.get_stat(all_xml)
        elif args.format == "json":
            all_json = {}
            for file in args.files:
                with open(file, "r") as f:
                    all_json.update(json.load(f))
            data = self.get_stat_json(all_json)
        html_template = Template(HTML_TMPL)
        if args.format == "xml":
            html = html_template.render(
                title=DEFAULT_TITLE,
                generator="j2html",
                stylesheet=Template(STYLESHEET_TMPL).render(),
                heading=self.generate_heading(data),
                report=self.generate_report(data, all_xml),
                ending=Template(ENDING_TMPL).render(),
            )
        elif args.format == "json":
            html = html_template.render(
                title=DEFAULT_TITLE,
                generator="j2html",
                stylesheet=Template(STYLESHEET_TMPL).render(),
                heading=self.generate_heading(data),
                report=self.generate_report_json(data, all_json),
                ending=Template(ENDING_TMPL).render(),
            )
        with open(args.output, "wb") as f:
            f.write(html.encode("utf8"))

    def getReportAttributes(self, test_data):
        """Return report attributes as a list of (name, value).
        It'll be used in heading.
        """
        status = []
        if test_data["success_count"]:
            status.append("Pass - <span style='color: green; font-weight:bold;'>%s</span>" % test_data["success_count"])
        if test_data["failure_count"]:
            status.append("Failure - <span style='color: red; font-size:larger; font-weight:bold;'>%s</span>" % test_data["failure_count"])
        if test_data["error_count"]:
            status.append("Error/Fail - <span style='color: red; font-size:larger; font-weight:bold;'>%s</span>" % test_data["error_count"])
        if test_data["skip_count"]:
            status.append("Skip - <span style='color: black; font-size:larger; font-weight:bold;'>%s</span>" % test_data["skip_count"])
        if status:
            status = " ".join(status)
        else:
            status = "none"
        return [
            ("Status", status),
        ]

    def generate_heading(self, test_data):
        """Generate heading for the report and status line."""
        report_attrs = self.getReportAttributes(test_data)
        a_lines = []
        for name, value in report_attrs:
            line = Template(HEADING_ATTRIBUTE_TMPL).render(
                name=name,
                value=value,
            )
            a_lines.append(line)
        heading = Template(HEADING_TMPL).render(
            title=saxutils.escape(Template(DEFAULT_TITLE).render()),
            parameters="".join(a_lines),
            description=saxutils.escape(Template(DEFAULT_DESCRIPTION).render()),
        )
        return heading

    def generate_report_test_json(self, rows, tid, cid, test):
        """Generate the HTML row of each test with its output."""
        status = "error"
        test_txt = ""
        test_dict = test[list(test.keys())[0]]
        test_result = test_dict["result"]
        test_time = float(test_dict["time"])
        test_name = list(test.keys())[0]

        if test_result == 'pass':
            status = "passed"
            test_txt = test_name
        elif test_result == 'skip':
            status = "skipped"
            test_txt = test_name
        elif test_result == 'fail':
            status = "failed"
            test_txt = ""
        # has_output = bool(test.system_out or test.system_err or test_txt)
        tid = "t%s.%s" % (cid + 1, tid + 1)
        tid = "p%s" % tid if status in ("passed", "skipped") else "f%s" % tid
        name = test_name
        desc = name
        output = test_txt
        script = Template(REPORT_TEST_OUTPUT_TMPL).render(
            id=tid,
            output=output,
        )

        row = Template(REPORT_TEST_WITH_OUTPUT_TMPL).render(
            tid=tid,
            Class=((status in ["skipped", "passed"]) and 'hiddenRow" style="display: none;' or "none"),
            style=(
                status == "error"
                and 'errorCase" style="color: #c00; font-weight: bold; padding: 2px; border: 1px solid #777;"'
                or (
                    status == "failed"
                    and 'failCase" style="color: #763b00; font-weight: bold; padding: 2px; border: 1px solid #777;" bgcolor="#ffc2c8'
                    or (
                        status == "skipped"
                        and 'skipCase" style="color: #0068df; font-weight: bold; padding: 2px; border: 1px solid #777;" bgcolor="#e1e1e1"><div class="testcase" style="margin-left: 2em;"'
                        or (status == "passed" and 'passCase" style="color: black; padding: 2px; border: 1px solid #777;" bgcolor="#c6ffc2"><div class="testcase" style="margin-left: 2em;' or "none")
                    )
                )
            ),
            desc=desc,
            script=script,
            status=status,
            test_time=time_format(test_time),
        )
        rows.append(row)
        # if not has_output:
        #     return

    def generate_report_test(self, rows, tid, cid, test):
        """Generate the HTML row of each test with its output."""
        status = "error"
        test_txt = ""

        if test.is_passed:
            status = "passed"
            test_txt = test.name
        elif test.is_skipped:
            status = "skipped"
            test_txt = (test.result[0].text or "") if test.result else test.name
        elif test.result and test.result[0].type == "Failure":
            status = "failed"
            test_txt = test.result[0].text or ""
        has_output = bool(test.system_out or test.system_err or test_txt)
        tid = "t%s.%s" % (cid + 1, tid + 1)
        tid = "p%s" % tid if status in ("passed", "skipped") else "f%s" % tid
        name = test.name
        desc = name
        test_time = test.time
        try:
            output = saxutils.escape(
                (test.system_out or "") + (test.system_err or "") + test_txt
            )
        # We expect to get this exception in python2.
        except UnicodeDecodeError:
            e = codecs.decode(test.system_err or "", "utf-8")
            o = codecs.decode(test.system_out or "", "utf-8")
            tt = codecs.decode(test_txt or "", "utf-8")
            output = saxutils.escape(o + e + tt)
        script = Template(REPORT_TEST_OUTPUT_TMPL).render(
            id=tid,
            output=output,
        )

        row = Template(REPORT_TEST_WITH_OUTPUT_TMPL).render(
            tid=tid,
            Class=((status in ["skipped", "passed"]) and 'hiddenRow" style="display: none;' or "none"),
            style=(
                status == "error"
                and 'errorCase" style="color: #c00; font-weight: bold; padding: 2px; border: 1px solid #777;"'
                or (
                    status == "failed"
                    and 'failCase" style="color: #763b00; font-weight: bold; padding: 2px; border: 1px solid #777;" bgcolor="#ffc2c8'
                    or (
                        status == "skipped"
                        and 'skipCase" style="color: #0068df; font-weight: bold; padding: 2px; border: 1px solid #777;" bgcolor="#e1e1e1"><div class="testcase" style="margin-left: 2em;'
                        or (status == "passed" and 'passCase" style="color: black; padding: 2px; border: 1px solid #777;" bgcolor="#c6ffc2"><div class="testcase" style="margin-left: 2em;' or "none")
                    )
                )
            ),
            desc=desc,
            script=script,
            status=status,
            test_time=time_format(test_time),
        )
        rows.append(row)
        if not has_output:
            return

    def generate_report(self, test_data, xml):
        """Generate the report of each suite with its tests."""
        rfe_sub = re.compile(r"\[r[fe][fe]_id:[^\]]+\]")
        clac = re.compile(r"^(\[[^\]]+\])+")

        # Groups tests by Feature name - [sriov], [pao], etc
        clasd_tests = {}
        for c in xml:
            name = c.name.replace("[It] ", "")
            if clac.search(name):
                cl_type = clac.search(name).group()
            else:
                cl_type = name.split()[0]
            if "ref_id" in cl_type or "rfe_id" in cl_type:
                cl_type = rfe_sub.sub("", cl_type)
            if cl_type not in clasd_tests:
                clasd_tests[cl_type] = [c]
            else:
                clasd_tests[cl_type].append(c)

        # Generate reports for each test
        rows = []
        total_time = 0
        for cid, t_class in enumerate(list(clasd_tests.keys())):
            tests = clasd_tests[t_class]

            desc = "%s tests suite" % t_class.capitalize()
            pa = []
            fa = []
            sk = []
            er = []
            time_suite = 0
            for t in tests:
                if t.is_passed:
                    pa.append(t)
                elif t.is_skipped:
                    sk.append(t)
                elif t.result and t.result[0].type == "Failure":
                    fa.append(t)
                else:
                    er.append(t)
                time_suite += t.time
            ne, nf, ns, np = len(er), len(fa), len(sk), len(pa)
            all_skipped = len(er) + len(fa) + len(sk) + len(pa) == len(sk)
            total_time += time_suite

            # Add template for each test line
            rows.append(
                Template(REPORT_CLASS_TMPL).render(
                    style=(
                        ne > 0
                        and 'errorClass" style="font-weight: bold; font-size: 120%;" bgcolor="#c00'
                        or nf > 0
                        and 'failClass" style="font-weight: bold; font-size: 120%;" bgcolor="#c60'
                        or all_skipped
                        and 'skipClass" style="font-weight: bold; font-size: 120%;" bgcolor="#bababa'
                        or 'passClass" style="font-weight: bold; font-size: 120%;" bgcolor="#6c6'
                    ),
                    desc=desc,
                    count=np + nf + ne + ns,
                    Pass=np,
                    fail=nf,
                    error=ne,
                    skip=ns,
                    time_suite_total=time_format(time_suite),
                    cid="c%s" % (cid + 1),
                )
            )

            for tid, t in enumerate(tests):
                self.generate_report_test(rows, tid, cid, t)

        # Write the report of Test suite with all tests inside in rows
        report = Template(REPORT_TMPL).render(
            test_list="".join(rows),
            count=str(
                test_data["success_count"]
                + test_data["failure_count"]
                + test_data["error_count"]
                + test_data["skip_count"]
            ),
            Pass=str(test_data["success_count"]),
            fail=str(test_data["failure_count"]),
            error=str(test_data["error_count"]),
            skip=str(test_data["skip_count"]),
            total_time=time_format(total_time),
        )
        return report

    def generate_report_json(self, test_data, all_json):
        """Generate the report of each suite with its tests."""
        rfe_sub = re.compile(r"\[r[fe][fe]_id:[^\]]+\]")
        clac = re.compile(r"^(\[[^\]]+\])+")

        # Groups tests by Feature name - [sriov], [pao], etc
        clasd_tests = {}
        for c in all_json:
            name = c
            if clac.search(name):
                cl_type = clac.search(name).group()
            else:
                cl_type = name.split()[0]
            if "ref_id" in cl_type or "rfe_id" in cl_type:
                cl_type = rfe_sub.sub("", cl_type)
            if cl_type not in clasd_tests:
                clasd_tests[cl_type] = {c: all_json[c]}
            else:
                clasd_tests[cl_type].update({c: all_json[c]})

        # Generate reports for each test
        rows = []
        total_time = 0
        for cid, t_class in enumerate(list(clasd_tests.keys())):
            tests = clasd_tests[t_class]

            desc = "%s tests suite" % t_class.capitalize()
            pa = []
            fa = []
            sk = []
            er = []
            time_suite = 0
            for t in tests:
                if tests[t]['result'] == 'pass':
                    pa.append({t: tests[t]})
                elif tests[t]['result'] == 'skip':
                    sk.append({t: tests[t]})
                elif tests[t]['result'] == 'fail':
                    fa.append({t: tests[t]})
                else:
                    er.append({t: tests[t]})
                time_suite += float(tests[t]['time'])
            ne, nf, ns, np = len(er), len(fa), len(sk), len(pa)
            all_skipped = len(er) + len(fa) + len(sk) + len(pa) == len(sk)
            total_time += time_suite

            # Add template for each test line
            rows.append(
                Template(REPORT_CLASS_TMPL).render(
                    style=(
                        ne > 0
                        and 'errorClass" style="font-weight: bold; font-size: 120%;" bgcolor="#c00'
                        or nf > 0
                        and 'failClass" style="font-weight: bold; font-size: 120%;" bgcolor="#c60'
                        or all_skipped
                        and 'skipClass" style="font-weight: bold; font-size: 120%;" bgcolor="#bababa'
                        or 'passClass" style="font-weight: bold; font-size: 120%;" bgcolor="#6c6'
                    ),
                    desc=desc,
                    count=np + nf + ne + ns,
                    Pass=np,
                    fail=nf,
                    error=ne,
                    skip=ns,
                    time_suite_total=time_format(time_suite),
                    cid="c%s" % (cid + 1),
                )
            )

            for tid, t in enumerate([{i: j} for i, j in tests.items()]):
                self.generate_report_test_json(rows, tid, cid, t)

        # Write the report of Test suite with all tests inside in rows
        report = Template(REPORT_TMPL).render(
            test_list="".join(rows),
            count=str(
                test_data["success_count"]
                + test_data["failure_count"]
                + test_data["error_count"]
                + test_data["skip_count"]
            ),
            Pass=str(test_data["success_count"]),
            fail=str(test_data["failure_count"]),
            error=str(test_data["error_count"]),
            skip=str(test_data["skip_count"]),
            total_time=time_format(total_time),
        )
        return report

    def get_stat(self, xml):
        """Get the statistics of the testsuite. Will be used in header and report"""
        res = {
            "success_count": 0,
            "failure_count": 0,
            "error_count": 0,
            "skip_count": 0,
        }

        for t in xml:
            if t.is_passed:
                res["success_count"] += 1
            elif t.is_skipped:
                res["skip_count"] += 1
            elif t.result and t.result[0].type == "Failure":
                res["failure_count"] += 1
            else:
                res["error_count"] += 1
        return res

    def get_stat_json(self, all_json):
        """Get the statistics of the testsuite. Will be used in header and report"""
        res = {
            "success_count": 0,
            "failure_count": 0,
            "error_count": 0,
            "skip_count": 0,
        }

        for t in all_json:
            if all_json[t]['result'] == 'pass':
                res["success_count"] += 1
            elif all_json[t]['result'] == 'skip':
                res["skip_count"] += 1
            elif all_json[t]['result'] == 'fail':
                res["failure_count"] += 1
            else:
                res["error_count"] += 1
        return res

    def merge(self, xml_tests):
        """Merge the testsuites and tests."""
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
    parser = argparse.ArgumentParser(description="Extract tasks from a playbook.")
    parser.add_argument(
        "--output",
        "-o",
        help="Output file. Default: %(default)s",
        default="cnf_result.html",
    )
    parser.add_argument(
        "--format",
        "-f",
        help="Format of input file, choose from %(choices)s. Default: %(default)s",
        choices=["json", "xml"],
        default="xml",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Files to extract tests from.",
    )
    args = parser.parse_args()
    HTMLReport(args)


if __name__ == "__main__":
    main()
