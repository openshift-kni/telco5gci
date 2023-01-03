#!/usr/bin/env python3

# Author: Sagi Shnaidman (@sshnaidm), Red Hat.
# This is heavily inspired by subunit2html.py tool:
# https://github.com/openstack/os-testr/blob/master/os_testr/subunit2html.py

import argparse
import codecs
import re
from jinja2 import Template

from xml.sax import saxutils
from junitparser import JUnitXml, TestSuite


HTML_TMPL = r"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
     "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>{{ title }}</title>
    <meta name="generator" content="{{ generator }}"/>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>
    {{ stylesheet }}
</head>
<body>
<script language="javascript" type="text/javascript"><!--
output_list = Array();
/* level - 0:Summary; 1:Failed; 2:All */
function showCase(level) {
    trs = document.getElementsByTagName("tr");
    for (var i = 0; i < trs.length; i++) {
        tr = trs[i];
        id = tr.id;
        if (id.substr(0,2) == 'ft') {
            if (level < 1) {
                tr.className = 'hiddenRow';
            }
            else {
                tr.className = '';
            }
        }
        if (id.substr(0,2) == 'pt') {
            if (level > 1) {
                tr.className = '';
            }
            else {
                tr.className = 'hiddenRow';
            }
        }
    }
}
function showClassDetail(cid, count) {
    var id_list = Array(count);
    var toHide = 1;
    for (var i = 0; i < count; i++) {
        tid0 = 't' + cid.substr(1) + '.' + (i+1);
        tid = 'f' + tid0;
        tr = document.getElementById(tid);
        if (!tr) {
            tid = 'p' + tid0;
            tr = document.getElementById(tid);
        }
        id_list[i] = tid;
        if (tr.className) {
            toHide = 0;
        }
    }
    for (var i = 0; i < count; i++) {
        tid = id_list[i];
        if (toHide) {
            document.getElementById('div_'+tid).style.display = 'none'
            document.getElementById(tid).className = 'hiddenRow';
        }
        else {
            document.getElementById(tid).className = '';
        }
    }
}
function showTestDetail(div_id){
    var details_div = document.getElementById(div_id)
    var displayState = details_div.style.display
    // alert(displayState)
    if (displayState != 'block' ) {
        displayState = 'block'
        details_div.style.display = 'block'
    }
    else {
        details_div.style.display = 'none'
    }
}
function html_escape(s) {
    s = s.replace(/&/g,'&amp;');
    s = s.replace(/</g,'&lt;');
    s = s.replace(/>/g,'&gt;');
    return s;
}
/* obsoleted by detail in <div>
function showOutput(id, name) {
    var w = window.open("", //url
                    name,
                    "resizable,scrollbars,status,width=800,height=450");
    d = w.document;
    d.write("<pre>");
    d.write(html_escape(output_list[id]));
    d.write("\n");
    d.write("<a href='javascript:window.close()'>close</a>\n");
    d.write("</pre>\n");
    d.close();
}
*/
--></script>
{{ heading }}
{{ report }}
{{ ending }}
</body>
</html>
"""
STYLESHEET_TMPL = """
<style type="text/css" media="screen">
body        { font-family: verdana, arial, helvetica, sans-serif;
    font-size: 80%; }
table       { font-size: 110%; width: 100%;}
pre         { font-size: 80%; }
/* -- heading -------------------------------------------------------------- */
h1 {
        font-size: 26pt;
        color: gray;
}
.heading {
    margin-top: 0ex;
    margin-bottom: 1ex;
}
.heading .attribute {
    margin-top: 1ex;
    margin-bottom: 0;
}
.heading .description {
    margin-top: 4ex;
    margin-bottom: 6ex;
}
/* -- css div popup -------------------------------------------------------- */
a.popup_link {
}
a.popup_link:hover {
    color: red;
}
.popup_window {
    display: none;
    overflow-x: scroll;
    /*border: solid #627173 1px; */
    padding: 10px;
    background-color: #E6E6D6;
    font-family: "Ubuntu Mono", "Lucida Console", "Courier New", monospace;
    text-align: left;
    font-size: 10pt;
}
}
/* -- report --------------------------------------------------------------- */
#show_detail_line {
    margin-top: 3ex;
    margin-bottom: 1ex;
}
#result_table {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid #777;
}
#header_row {
    font-weight: bold;
    color: white;
    background-color: #777;
}
#result_table td {
    border: 1px solid #777;
    padding: 2px;
}
#total_row  { font-weight: bold; }
.passClass  { background-color: #6c6; font-weight: bold; font-size: 120%;}
.skipClass  { background-color: #bababa; font-weight: bold; font-size: 120%;}
.failClass  { background-color: #c60;  font-weight: bold; font-size: 120%;}
.errorClass { background-color: #c00; font-weight: bold; font-size: 120%;}
.passCase   { color: black; background-color: #c6ffc2; }
.failCase   { color: #763b00; font-weight: bold; background-color: #ffc2c8; }
.errorCase  { color: #c00; font-weight: bold;}
.skipCase   { color: #0068df; font-weight: bold; background-color: #e1e1e1; }
.hiddenRow  { display: none; }
.testcase   { margin-left: 2em; }
td.testname {width: 40%}
td.small {width: 40px}
/* -- ending --------------------------------------------------------------- */
#ending {
}
</style>
"""

HEADING_TMPL = """<div class='heading'>
<h1>{{ title }}</h1>
{{ parameters }}
<p class='description'>{{ description }}</p>
</div>
"""
HEADING_ATTRIBUTE_TMPL = """
<p class='attribute'><strong>{{ name }}:</strong> {{ value }}</p>
"""
REPORT_TMPL = """
<p id='show_detail_line'>Show
<a href='javascript:showCase(0)'>Summary</a>
<a href='javascript:showCase(1)'>Failed</a>
<a href='javascript:showCase(2)'>All</a>
</p>
<table id='result_table'>
<colgroup>
<col align='left' />
<col align='right' />
<col align='right' />
<col align='right' />
<col align='right' />
<col align='right' />
<col align='right' />
<col align='right' />
</colgroup>
<tr id='header_row'>
    <td>Test Group/Test case</td>
    <td>Count</td>
    <td>Pass</td>
    <td>Fail</td>
    <td>Error</td>
    <td>Skip</td>
    <td>View</td>
    <td> </td>
</tr>
{{ test_list }}
<tr id='total_row'>
    <td>Total</td>
    <td>{{ count }}</td>
    <td>{{ Pass }}</td>
    <td>{{ fail }}</td>
    <td>{{ error }}</td>
    <td>{{ skip }}</td>
    <td>&nbsp;</td>
    <td>&nbsp;</td>
</tr>
</table>
"""
REPORT_CLASS_TMPL = r"""
<tr class='{{ style }}'>
    <td class="testname">{{ desc }}</td>
    <td class="small">{{ count }}</td>
    <td class="small">{{ Pass }}</td>
    <td class="small">{{ fail }}</td>
    <td class="small">{{ error }}</td>
    <td class="small">{{ skip }}</td>
    <td class="small"><a href="javascript:showClassDetail('{{ cid }}',{{ count }})"
>Detail</a></td>
    <td> </td>
</tr>
"""
REPORT_TEST_WITH_OUTPUT_TMPL = r"""
<tr id='{{ tid }}' class='{{ Class }}'>
    <td class='{{ style }}'><div class='testcase'>{{ desc }}</div></td>
    <td colspan='7' align='left'>
    <!--css div popup start-->
    <a class="popup_link" onfocus='this.blur();'
    href="javascript:showTestDetail('div_{{ tid }}')" >
        {{ status }}</a>
    <div id='div_{{ tid }}' class="popup_window">
        <div style='text-align: right; color:red;cursor:pointer'>
        <a onfocus='this.blur();'
onclick="document.getElementById('div_{{ tid }}').style.display = 'none' " >
           [x]</a>
        </div>
        <pre>
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
DEFAULT_TITLE = 'CNF Test Report'
DEFAULT_DESCRIPTION = ''


def getReportAttributes(test_data):
    """Return report attributes as a list of (name, value)."""
    status = []
    if test_data['success_count']:
        status.append('Pass %s' % test_data['success_count'])
    if test_data['failure_count']:
        status.append('Failure %s' % test_data['failure_count'])
    if test_data['error_count']:
        status.append('Error %s' % test_data['error_count'])
    if test_data['skip_count']:
        status.append('Skip %s' % test_data['skip_count'])
    if status:
        status = ' '.join(status)
    else:
        status = 'none'
    return [
        ('Status', status),
    ]


def generate_heading(test_data):
    report_attrs = getReportAttributes(test_data)
    a_lines = []
    for name, value in report_attrs:
        line = Template(HEADING_ATTRIBUTE_TMPL).render(
            name=saxutils.escape(name),
            value=saxutils.escape(value),
        )
        a_lines.append(line)
    heading = Template(HEADING_TMPL).render(
        title=saxutils.escape(Template(DEFAULT_TITLE).render()),
        parameters=''.join(a_lines),
        description=saxutils.escape(Template(DEFAULT_DESCRIPTION).render()),
    )
    return heading


def generate_report_test(rows, tid, cid, test):
    status = "error"
    test_txt = ""

    if test.is_passed:
        status = "passed"
        test_txt = test.name
    elif test.is_skipped:
        status = "skipped"
        test_txt = (test.result[0].text or '') if test.result else test.name
    elif test.result and test.result[0].type == 'Failure':
        status = "failed"
        test_txt = test.result[0].text or ''
    has_output = bool(test.system_out or test.system_err or test_txt)
    tid = "t%s.%s" % (cid + 1, tid + 1)
    tid = "p%s" % tid if status in ('passed', 'skipped') else "f%s" % tid
    name = test.name
    desc = name
    try:
        output = saxutils.escape(
            (test.system_out or '') + (test.system_err or '') + test_txt)
    # We expect to get this exception in python2.
    except UnicodeDecodeError:
        e = codecs.decode(test.system_err or '', 'utf-8')
        o = codecs.decode(test.system_out or '', 'utf-8')
        tt = codecs.decode(test_txt or '', 'utf-8')
        output = saxutils.escape(o + e + tt)
    script = Template(REPORT_TEST_OUTPUT_TMPL).render(
        id=tid,
        output=output,
    )

    row = Template(REPORT_TEST_WITH_OUTPUT_TMPL).render(
        tid=tid,
        Class=((status in ['skipped', 'passed']) and 'hiddenRow' or 'none'),
        style=(status == 'error' and 'errorCase' or
               (status == 'failed' and 'failCase' or
                (status == 'skipped' and 'skipCase' or
                 (status == 'passed' and 'passCase' or
                  'none')))),
        desc=desc,
        script=script,
        status=status,
    )
    rows.append(row)
    if not has_output:
        return


def generate_report(test_data, xml):
    rfe_sub = re.compile(r"\[r[fe][fe]_id:[^\]]+\]")
    clac = re.compile(r"^(\[[^\]]+\])+")

    # Groups tests by Feature name - [sriov], [pao], etc
    clasd_tests = {}
    for c in xml:
        name = c.name
        if clac.search(name):
            cl_type = clac.search(name).group()
        else:
            cl_type = name.split()[0]
        if 'ref_id' in cl_type or 'rfe_id' in cl_type:
            cl_type = rfe_sub.sub("", cl_type)
        if cl_type not in clasd_tests:
            clasd_tests[cl_type] = [c]
        else:
            clasd_tests[cl_type].append(c)

    rows = []
    for cid, t_class in enumerate(list(clasd_tests.keys())):
        tests = clasd_tests[t_class]

        desc = "%s tests suite" % t_class.capitalize()
        pa = []
        fa = []
        sk = []
        er = []
        for t in tests:
            if t.is_passed:
                pa.append(t)
            elif t.is_skipped:
                sk.append(t)
            elif t.result and t.result[0].type == 'Failure':
                fa.append(t)
            else:
                er.append(t)
        ne, nf, ns, np = len(er), len(fa), len(sk), len(pa)
        all_skipped = len(er) + len(fa) + len(sk) + len(pa) == len(sk)

        rows.append(
            Template(REPORT_CLASS_TMPL).render(
                style=(ne > 0 and 'errorClass'
                       or nf > 0 and 'failClass'
                       or all_skipped and 'skipClass'
                       or 'passClass'),
                desc=desc,
                count=np + nf + ne + ns,
                Pass=np,
                fail=nf,
                error=ne,
                skip=ns,
                cid='c%s' % (cid + 1),
            ))

        for tid, t in enumerate(tests):
            generate_report_test(rows, tid, cid, t)

    report = Template(REPORT_TMPL).render(
        test_list=''.join(rows),
        count=str(test_data['success_count'] + test_data['failure_count'] +
                  test_data['error_count'] + test_data['skip_count']),
        Pass=str(test_data['success_count']),
        fail=str(test_data['failure_count']),
        error=str(test_data['error_count']),
        skip=str(test_data['skip_count']),
    )
    return report


def get_stat(xml):
    res = {
        'success_count': 0,
        'failure_count': 0,
        'error_count': 0,
        'skip_count': 0,
    }

    for t in xml:
        if t.is_passed:
            res['success_count'] += 1
        elif t.is_skipped:
            res['skip_count'] += 1
        elif t.result and t.result[0].type == 'Failure':
            res['failure_count'] += 1
        else:
            res['error_count'] += 1
    return res


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
        help="Output file. Default: cnf_result.html",
        default="cnf_result.html",
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
    html_template = Template(HTML_TMPL)
    html = html_template.render(
        title=DEFAULT_TITLE,
        generator="j2html",
        stylesheet=Template(STYLESHEET_TMPL).render(),
        heading=generate_heading(data),
        report=generate_report(data, all_xml),
        ending=Template(ENDING_TMPL).render(),

    )
    with open(args.output, "wb") as f:
        f.write(html.encode('utf8'))


if __name__ == '__main__':
    main()
