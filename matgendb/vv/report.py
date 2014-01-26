"""
Description.
"""
__author__ = 'Dan Gunter <dkgunter@lbl.gov>'
__date__ = '2/21/13'


from email.mime.text import MIMEText
import json
from operator import itemgetter
import smtplib

from .util import DoesLogging
from ..util import MongoJSONEncoder


class Report:
    def __init__(self, header):
        """Create blank report, with a header.

        :param header: Report header
        :type header: Header
        """
        self._hdr = header
        self._sections = []

    def add_section(self, section):
        self._sections.append(section)

    @property
    def header(self):
        return self._hdr

    def is_empty(self):
        if len(self._sections) == 0:
            return True
        self._total_rows = 0
        for sect in self._sections:
            self._count_rows(sect)
        return self._total_rows == 0

    def _count_rows(self, sect):
        if sect.body is not None:
            self._total_rows += sect.body.nrow
        for subsect in sect._sections:
            self._count_rows(subsect)

    def __iter__(self):
        return iter(self._sections)


class ReportSection(Report):
    """Section within a report, with data.
    """
    def __init__(self, header, body=None):
        """Create new report section, initialized with header and body.

        :param header: The header for the section
        :type header: SectionHeader
        :param body: The body of the section, or None if this is a container for sub-sections
        :type body: Table
        """
        Report.__init__(self, header)
        self._body = body

    @property
    def body(self):
        return self._body


class Header:
    """Base header class.
    """
    def __init__(self, title=''):
        self._kv = []
        self.title = title

    def add(self, key, value):
        self._kv.append((key, value))

    def get(self, key):
        return (v for k, v in self._kv if k == key)

    def __iter__(self):
        return iter(self._kv)

    def to_dict(self):
        return {k: v for k, v in self._kv}


class ReportHeader(Header):
    """Header for entire report.
    """
    pass


class SectionHeader(Header):
    """Header for one section of a report.
    """
    pass


class Table:
    """Table of values.
    """
    def __init__(self, colnames):
        self._colnames = colnames
        self._rows = []
        self._width = len(colnames)
        self._max_col_widths = map(len, colnames)

    def add(self, values):
        if len(values) != self._width:
            raise ValueError('expected {:d} values, got {:d}'.format(self._width, len(values)))
        self._rows.append(values)
        for i, v in enumerate(values):
            n = len(str(v))
            if self._max_col_widths[i] < n:
                self._max_col_widths[i] = n

    def sortby(self, name_or_index):
        name, index = None, None
        if isinstance(name_or_index, int):
            index = name_or_index
        else:
            name = name_or_index
        if name is not None:
            try:
                colnum = self._colnames.index(name)
            except ValueError:
                raise ValueError('column {} not in {}'.format(name, self._colnames))
        else:
            if index < 0 or index >= self._width:
                raise ValueError('index out of range 0..{:d}'.format(self._width - 1))
            colnum = index
        self._rows.sort(key=itemgetter(colnum))

    def __iter__(self):
        return iter(self._rows)

    @property
    def values(self):
        return [{self._colnames[i]: r[i] for i in range(self._width)}
                for r in self._rows]

    @property
    def column_names(self):
        return self._colnames

    @property
    def column_widths(self):
        return self._max_col_widths

    @property
    def ncol(self):
        return self._width

    @property
    def nrow(self):
        return len(self._rows)


## Exceptions

class ReportBackupError(Exception):
    pass

## Formatting


def css_minify(s):
    return s.replace('\n', ' ').replace('  ', ' ')

# CSS for HTML report output
DEFAULT_CSS = css_minify("""
html { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
body { margin: 2em;}
table { margin-top: 1em; clear: both; border: 0;}
dl, dt, dd { float: left; }
dl, dt { clear: both; }
dt { width: 8em; font-weight: 700; }
dd { width: 32em; }
tr:nth-child(even) { background-color: #E9E9E9; }
tr:nth-child(odd) { background-color: #E9E9E9; }
th, td {padding: 0.2em 0.5em;}
th { text-align: left;  color: black; margin: 0; font-weight: 300;}
h1, h2, h3 { clear: both; margin: 0; padding: 0; }
h1 { font-size: 18; color: rgb(44, 62, 80); }
h2 { font-size: 14; color: black; }
""")


class HTMLFormatter:
    """Format a report as HTML.
    """
    def __init__(self, line_sep='\n', id_column=0, css=DEFAULT_CSS):
        self._sep = line_sep
        self._idcol = id_column
        self._css = css

    def format(self, report):
        text = []
        text.append('<!DOCTYPE html>')
        text.append('<html>')
        text.append('<title>{}</title>'.format(report.header.title))
        text.append('<head>')
        if self._css:
            text.append('<style>')
            text.append(self._css)
            text.append('</style>')
        text.append('</head>')
        text.append('<body>')
        text.append('<h1>{}</h1>'.format(report.header.title))
        text.append('<dl class="rptmeta">')
        for key, value in report.header:
            text.append('<dt>{}</dt>'.format(key))
            text.append('<dd>{}</dd>'.format(value))
        text.append('</dl>')
        for section in report:
            text.append('<h2>{}</h2>'.format(section.header.title))
            text.append('<dl class="sectmeta">')
            for key, value in section.header:
                text.append('<dt>{}</dt>'.format(key))
                text.append('<dd>{}</dd>'.format(value))
            text.append('</dl>')
            for cond_section in section:
                text.append('<h3>{}</h3>'.format(cond_section.header.title))
                text.append('<dl class="subsectmeta">')
                for key, value in cond_section.header:
                    text.append('<dt>{}</dt>'.format(key))
                    text.append('<dd>{}</dd>'.format(value))
                text.append('</dl>')
                text.append('<table>')
                text.append('<tr>')
                for name in cond_section.body.column_names:
                    text.append('<th>{}</th>'.format(name))
                text.append('</tr>')
                prev_key, i = None, 0
                for row in cond_section.body:
                    row = list(row)
                    key = row[self._idcol]
                    if prev_key and key == prev_key:
                        row[self._idcol] = ''
                    else:
                        prev_key = key
                        i += 1
                    rclass = ('even', 'odd')[i % 2]
                    text.append('<tr class="{}">'.format(rclass))
                    for value in row:
                        text.append('<td>{}</td>'.format(value))
                    text.append('</tr>')
                text.append('</table>')
        text.append('</body>')
        text.append('</html>')
        return self._sep.join(text)


class JSONFormatter:
    """Format a report as JSON.
    """
    def __init__(self, id_column=0, indent=2):
        self._indent = indent
        self._idcol = id_column

    def format(self, report):
        obj = dict(
            title=report.header.title,
            info=report.header,
            sections=[
                dict(title=s.header.title,
                     info=s.header,
                     conditions=[dict(
                         title=cs.header.title,
                         info=cs.header,
                         violations=cs.body)
                         for cs in s
                     ]
                )
                for s in report
            ]
        )
        return json.dumps(obj, indent=self._indent, cls=MongoJSONEncoder)


class ReportJSONEncoder(MongoJSONEncoder):
    def default(self, o):
        if isinstance(o, Header):
            return o.to_dict()
        elif isinstance(o, Table):
            return o.values
        return MongoJSONEncoder.default(self, o)


class MarkdownFormatter:
    """Format a report as markdown
    """
    def __init__(self, id_column=0):
        self._idcol = id_column

    def _mapdump(self, d):
        return ', '.join((('{}={}'.format(k, v) for k, v in d.iteritems())))

    def _fixed_width(self, values, widths):
        s = ''.join(["{{:{:d}s}}".format(w + 1).format(str(v))
                    for w, v in zip(widths, values)])
        return s

    def format(self, report):
        lines = []
        self._append_heading(lines, 1, report.header.title)
        self._append_info_section(lines, report.header)
        for section in report:
            self._append_heading(lines, 2, section.header.title)
            self._append_info_section(lines, section.header)
            for cond in section:
                self._append_heading(lines, 3, cond.header.title)
                self._append_info_section(lines, cond.header)
                self._append_violations(lines, cond.body)
        return '\n'.join(lines)

    def _append_info_section(self, lines, info):
        if not info:
            return
        infodict = info.to_dict()
        if infodict:
            text = 'Info: {}'.format(self._mapdump(infodict))
            lines.append(text)

    def _append_heading(self, lines, level, title):
        hashes = '#' * level
        text = '\n{} {} {}\n'.format(hashes, title, hashes)
        lines.append(text)

    def _append_violations(self, lines, data):
        lines.append('\nViolations:\n')
        indent = '    '
        lines.append(indent + self._fixed_width(data.column_names, data.column_widths))
        for row in data:
            lines.append(indent + self._fixed_width(row, data.column_widths))


class Emailer(DoesLogging):
    """Send a report to an email recipient.
    """
    def __init__(self, sender='me@localhost', recipients=('you@remote.host',),
                 subject='Report', server='localhost', port=None, **kwargs):
        """Send reports as email.

        :param: sender Sender of the email
        :param: recipients List of _recipients of the email
        :param: subject Email _subject line
        :param: server SMTP server host
        :param: port SMTP server port (None for default)
        """
        DoesLogging.__init__(self, 'mg.emailer')
        self._sender, self._recipients, self._subject = sender, recipients, subject
        self._server, self._port = server, port
        self._message = ""

    def send(self, text, fmt):
        """Send the email message.

        :param text: The text to send
        :type text: str
        :param fmt: The name of the format of the text
        :type fmt: str
        :return: Number of recipients it was sent to
        :rtype: int
        """
        num_recip = 0
        main_fmt, sub_fmt = fmt.split('/')
        mime_class = dict(text=MIMEText).get(main_fmt, MIMEText)
        msg = mime_class(text, sub_fmt)
        msg['Subject'] = self._subject
        msg['From'] = self._sender
        msg['To'] = ', '.join(self._recipients)
        if self._port is None:
            conn_kwargs = dict(host=self._server)
        else:
            conn_kwargs = dict(host=self._server, port=self._port)
        self._log.info("connect to email server {}".format(conn_kwargs))
        try:
            s = smtplib.SMTP(**conn_kwargs)
            s.sendmail(self._sender, self._recipients, msg.as_string())
            s.quit()
            n_recip = len(self._recipients)
        except Exception, err:
            self._log.error("connection to SMTP server failed: {}".format(err))
            n_recip = 0
        return n_recip


# ---------------
# Diff formatting
# ---------------

class DiffFormatter(object):
    """Base class for formatting a 'diff' report.
    """

    TITLE = "Materials Project Database Diff Report"

    def __init__(self, meta, title=TITLE):
        """Constructor.

        :param meta: Report metadata, must have the following keys:
                     - start_time, end_time: string repr of report gen. times
                     - elapsed: float #sec for end_time - start_time
                     - db1, db2: string repr of 2 input database/collections.
        :type meta: dict
        """
        self.meta = meta

    def format(self, result):
        """Format a report from a result object.

        :return: Report body
        :rtype: str
        """
        raise NotImplementedError()


class DiffHtmlFormatter(DiffFormatter):
    """Format an HTML diff report.
    """

    CSS = DEFAULT_CSS + css_minify("""
    body {background-color: #F3F3F3; margin: 1em;}
    .header {padding: 5px; margin: 0 5px;}
    .header h1 {color: #165F4B; font-size: 20; text-align: left; margin-left: 20px;}
    .header p {color: #666666; margin-left: 20px; height: 12px;}
    .header p em {color: #4169E1; font-style: normal;}
    .content {padding: 15px; padding-top: 0px; margin: 0;}
    .content h2 {color: #2C3E50; font-size: 16px;}
    .empty { font-size: 14px; font-style: italic;}
    .section {padding: 5px; margin: 10px; background-color: #E2E2E2; border-radius: 5px;}
    .section div {margin-left: 10px;}
    .section table {margin-left: 5px;}
    tr:nth-child(even) { background-color: white; }
    tr:nth-child(odd) { background-color: #F5F5F5; }
    tr:nth-child(1) { background-color: #778899; font-weight: 500;}
    th, td {padding: 0.2em 0.5em;}
    th { text-align: left;  color: white; margin: 0;}
    """)

    def format(self, result):
        """Generate HTML report.

        :return: Report body
        :rtype: str
        """
        return ("<html><head><style>{css}</style><body>{header}{body}</body></html>"
                .format(css=self.CSS, header=self._header(),
                body=self._body(result)))

    def _header(self):
        s = "<div class='header'><h1>{}</h1>".format(self.TITLE)
        s += "<p>Compared <em>{db1}</em> with <em>{db2}</em></p>"
        s += "<p>Run time: <em>{start_time}</em> to <em>{end_time}</em> "
        s += "(<em>{elapsed:.1f}</em> sec)</p>"
        return (s + "</div>").format(**self.meta)

    def _body(self, result):
        body = ["<div class='content'>"]
        for section in "additional", "missing", "different":
            body.append("<div class='section'><h2>{}</h2>".format(section.title()))
            if len(result[section]) == 0:
                body.append("<div class='empty'>Empty</div>")
            else:
                body.extend(self._table(result[section]))
            body.append("</div>")
        body.append("</div>")
        return ''.join(body)

    def _table(self, rows):
        table = ["<table>"]
        cols = sorted(rows[0].keys())
        table.extend(["<tr>"] + ["<th>{}</th>".format(c) for c in cols] + ["</tr>"])
        for r in rows:
            table.extend(["<tr>"] + ["<td>{}</td>".format(r[c]) for c in cols] + ["</tr>"])
        table.append("</table>")
        return table


class DiffTextFormatter(DiffFormatter):
    """Format a plain-text diff report.
    """

    def format(self, result):
        """Generate plain text report.

        :return: Report body
        :rtype: str
        """
        m = self.meta
        lines = ['-' * len(self.TITLE),
                 self.TITLE,
                 '-' * len(self.TITLE),
                 "Compared: {db1} <-> {db2}".format(**m),
                 "Run time: {start_time} -- {end_time} ({elapsed:.1f} sec)".format(**m),
                 ""]
        for section in result.keys():
            lines.append("* " + section.title())
            indent = " " * 4
            if len(result[section]) == 0:
                lines.append("{}EMPTY".format(indent))
            else:
                for v in result[section]:
                    lines.append("{}{}".format(indent, self._record(v)))
        return '\n'.join(lines)

    def _record(self, rec):
        fields = ['{}: {}'.format(k, v) for k, v in rec.iteritems()]
        return '{' + ', '.join(fields) + '}'
