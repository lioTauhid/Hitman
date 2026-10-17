"""Generate client code snippets from a resolved request."""

from __future__ import annotations

import json
from pathlib import PurePath
from urllib.parse import urlencode

from hitman.core.http import ResolvedRequest

# (id, display name, library)
LANGUAGES = [
    ("curl", "cURL", "Shell"),
    ("python", "Python", "requests"),
    ("fetch", "JavaScript", "fetch"),
    ("go", "Go", "net/http"),
    ("dart", "Dart", "http package"),
]

KEYWORDS = {
    "curl": ["curl"],
    "python": ["import", "from", "as", "True", "False", "None", "print", "def", "return"],
    "fetch": ["const", "await", "async", "new", "true", "false", "null", "return"],
    "go": ["package", "import", "func", "if", "err", "nil", "defer", "return", "var", "true", "false"],
    "dart": ["import", "final", "await", "async", "Future", "void", "true", "false", "null", "as"],
}
HASH_COMMENTS = {"curl", "python"}


def _sq(text: str) -> str:
    """Single-quote for a POSIX shell."""
    return "'" + text.replace("'", "'\\''") + "'"


def _dq(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _dart_q(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'").replace("$", "\\$").replace("\n", "\\n") + "'"


def _indent_tail(text: str, pad: str) -> str:
    lines = text.split("\n")
    return "\n".join([lines[0]] + [pad + line for line in lines[1:]])


def _file_name(path: str) -> str:
    return PurePath(path.replace("\\", "/")).name or "file"


def generate(lang: str, req: ResolvedRequest, include_auth: bool = True) -> str:
    headers = [(k, v) for k, v in req.headers if include_auth or k.lower() not in req.auth_headers]
    gen = _GENERATORS.get(lang, _curl)
    return gen(req, headers)


def _parsed_json(req: ResolvedRequest):
    if req.body_kind != "raw":
        return None
    try:
        return json.loads(req.body)
    except ValueError:
        return None


# ----------------------------------------------------------------- languages

def _curl(req: ResolvedRequest, headers: list[tuple[str, str]]) -> str:
    parts = [f"curl --request {req.method}", f"  --url {_sq(req.url)}"]
    parts += [f"  --header {_sq(f'{k}: {v}')}" for k, v in headers]
    parsed = _parsed_json(req)
    if req.body_kind == "raw":
        body = json.dumps(parsed, indent=2, ensure_ascii=False) if parsed is not None else req.body
        parts.append(f"  --data {_sq(body)}")
    elif req.body_kind == "urlencoded":
        parts += [f"  --data-urlencode {_sq(f'{k}={v}')}" for k, v in req.form]
    elif req.body_kind == "form":
        # --form treats values starting with @ or < as files, so such text goes through --form-string.
        parts += [f"  --{'form-string' if v[:1] in '@<' else 'form'} {_sq(f'{k}={v}')}" for k, v in req.form]
        parts += [f"  --form {_sq(f'{k}=@{path}')}" for k, path in req.files]
    return " \\\n".join(parts)


def _python(req: ResolvedRequest, headers: list[tuple[str, str]]) -> str:
    lines = ["import requests", "", f"url = {_dq(req.url)}"]
    if headers:
        lines.append("headers = {")
        lines += [f"    {_dq(k)}: {_dq(v)}," for k, v in headers]
        lines.append("}")
    body_arg = ""
    parsed = _parsed_json(req)
    if req.body_kind == "raw":
        if parsed is not None:
            lines.append("payload = " + _to_python(parsed))
            body_arg = ", json=payload"
        else:
            lines.append(f"payload = {_dq(req.body)}")
            body_arg = ", data=payload"
    elif req.body_kind in ("urlencoded", "form"):
        if req.form:
            lines.append("payload = {")
            lines += [f"    {_dq(k)}: {_dq(v)}," for k, v in req.form]
            lines.append("}")
        if req.body_kind == "urlencoded":
            body_arg = ", data=payload" if req.form else ""
        elif req.files:
            lines.append("files = [")
            lines += [f"    ({_dq(k)}, open({_dq(path)}, \"rb\"))," for k, path in req.files]
            lines.append("]")
            body_arg = (", data=payload" if req.form else "") + ", files=files"
        elif req.form:  # passing the fields as files makes requests send multipart/form-data
            body_arg = ", files={k: (None, v) for k, v in payload.items()}"
    args = "url" + (", headers=headers" if headers else "") + body_arg
    lines += ["", f"response = requests.request({_dq(req.method)}, {args}, timeout=30)",
              "print(response.status_code)"]
    if req.method != "HEAD":
        lines.append("print(response.text)")
    return "\n".join(lines)


def _to_python(value, indent: int = 0) -> str:
    pad, inner = "    " * indent, "    " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{inner}{_dq(str(k))}: {_to_python(v, indent + 1)}," for k, v in value.items()]
        return "{\n" + "\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [f"{inner}{_to_python(v, indent + 1)}," for v in value]
        return "[\n" + "\n".join(items) + f"\n{pad}]"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if value is None:
        return "None"
    if isinstance(value, str):
        return _dq(value)
    return json.dumps(value)


def _fetch(req: ResolvedRequest, headers: list[tuple[str, str]]) -> str:
    lines = []
    if req.body_kind == "form":
        if req.files:
            lines += ['import { openAsBlob } from "node:fs";  // Node.js 19.8+; in a browser use a File object', ""]
        lines.append("const form = new FormData();")
        lines += [f"form.append({_dq(k)}, {_dq(v)});" for k, v in req.form]
        lines += [f"form.append({_dq(k)}, await openAsBlob({_dq(path)}), {_dq(_file_name(path))});"
                  for k, path in req.files]
        lines.append("")
    lines += [f"const response = await fetch({_dq(req.url)}, {{", f"  method: {_dq(req.method)},"]
    if headers:
        lines.append("  headers: {")
        lines += [f"    {_dq(k)}: {_dq(v)}," for k, v in headers]
        lines.append("  },")
    parsed = _parsed_json(req)
    if req.body_kind == "raw":
        if parsed is not None:
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            lines.append(f"  body: JSON.stringify({_indent_tail(pretty, '  ')}),")
        else:
            lines.append(f"  body: {_dq(req.body)},")
    elif req.body_kind == "urlencoded":
        lines.append(f"  body: new URLSearchParams({_dq(urlencode(req.form))}),")
    elif req.body_kind == "form":
        lines.append("  body: form,")
    lines += ["});", "", "console.log(response.status);"]
    if req.method != "HEAD":
        lines.append("console.log(await response.text());")
    return "\n".join(lines)


def _go(req: ResolvedRequest, headers: list[tuple[str, str]]) -> str:
    multipart = req.body_kind == "form"
    text_body = ""
    if req.body_kind == "raw":
        parsed = _parsed_json(req)
        text_body = json.dumps(parsed, indent=2, ensure_ascii=False) if parsed is not None else req.body
    elif req.body_kind == "urlencoded":
        text_body = urlencode(req.form)
    has_body = bool(text_body) or multipart

    if multipart:
        imports = ['"bytes"', '"fmt"', '"io"', '"mime/multipart"', '"net/http"'] + (['"os"'] if req.files else [])
    else:
        imports = ['"fmt"', '"io"', '"net/http"'] + (['"strings"'] if text_body else [])
    lines = ["package main", "", "import ("] + [f"\t{i}" for i in sorted(imports)] + [")", "", "func main() {"]
    if multipart:
        lines += ["\tbody := &bytes.Buffer{}", "\twriter := multipart.NewWriter(body)"]
        lines += [f"\twriter.WriteField({_dq(k)}, {_dq(v)})" for k, v in req.form]
        for key, path in req.files:
            lines += ["\t{", f"\t\tfile, err := os.Open({_dq(path)})", "\t\tif err != nil {", "\t\t\tpanic(err)", "\t\t}",
                      f"\t\tpart, err := writer.CreateFormFile({_dq(key)}, {_dq(_file_name(path))})",
                      "\t\tif err != nil {", "\t\t\tpanic(err)", "\t\t}", "\t\tio.Copy(part, file)",
                      "\t\tfile.Close()", "\t}"]
        lines += ["\twriter.Close()", ""]
    elif text_body:
        lines.append("\tbody := strings.NewReader(`" + _indent_tail(text_body.replace("`", "` + \"`\" + `"), "\t") + "`)")
    lines += [f"\treq, err := http.NewRequest({_dq(req.method)}, {_dq(req.url)}, {'body' if has_body else 'nil'})",
              "\tif err != nil {", "\t\tpanic(err)", "\t}"]
    lines += [f"\treq.Header.Set({_dq(k)}, {_dq(v)})" for k, v in headers]
    if multipart:
        lines.append('\treq.Header.Set("Content-Type", writer.FormDataContentType())')
    elif req.body_kind == "urlencoded" and not any(k.lower() == "content-type" for k, _ in headers):
        lines.append('\treq.Header.Set("Content-Type", "application/x-www-form-urlencoded")')
    lines += ["", "\tres, err := http.DefaultClient.Do(req)", "\tif err != nil {", "\t\tpanic(err)", "\t}",
              "\tdefer res.Body.Close()", "", "\tdata, _ := io.ReadAll(res.Body)",
              "\tfmt.Println(res.Status)", "\tfmt.Println(string(data))", "}"]
    return "\n".join(lines)


def _dart(req: ResolvedRequest, headers: list[tuple[str, str]]) -> str:
    fn = {"GET": "get", "POST": "post", "PUT": "put", "PATCH": "patch", "DELETE": "delete", "HEAD": "head"}.get(req.method)
    lines = ["import 'dart:convert';", "import 'package:http/http.dart' as http;", "",
             "Future<void> main() async {"]
    if req.body_kind == "form":
        lines.append(f"  final request = http.MultipartRequest({_dart_q(req.method)}, Uri.parse({_dart_q(req.url)}));")
        if headers:
            lines.append("  request.headers.addAll({")
            lines += [f"    {_dart_q(k)}: {_dart_q(v)}," for k, v in headers]
            lines.append("  });")
        lines += [f"  request.fields[{_dart_q(k)}] = {_dart_q(v)};" for k, v in req.form]
        lines += [f"  request.files.add(await http.MultipartFile.fromPath({_dart_q(k)}, {_dart_q(path)}));"
                  for k, path in req.files]
        lines.append("  final response = await http.Response.fromStream(await request.send());")
    elif fn:
        lines += [f"  final response = await http.{fn}(", f"    Uri.parse({_dart_q(req.url)}),"]
        if headers:
            lines.append("    headers: {")
            lines += [f"      {_dart_q(k)}: {_dart_q(v)}," for k, v in headers]
            lines.append("    },")
        if fn not in ("get", "head"):
            parsed = _parsed_json(req)
            if req.body_kind == "raw":
                if parsed is not None:
                    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
                    lines.append(f"    body: jsonEncode({_indent_tail(pretty, '    ')}),")
                else:
                    lines.append(f"    body: {_dart_q(req.body)},")
            elif req.body_kind == "urlencoded":
                lines.append("    body: {")
                lines += [f"      {_dart_q(k)}: {_dart_q(v)}," for k, v in req.form]
                lines.append("    },")
        lines.append("  );")
    else:
        lines.append(f"  final request = http.Request({_dart_q(req.method)}, Uri.parse({_dart_q(req.url)}));")
        lines += [f"  request.headers[{_dart_q(k)}] = {_dart_q(v)};" for k, v in headers]
        lines.append("  final response = await http.Response.fromStream(await request.send());")
    lines += ["  print(response.statusCode);", "  print(response.body);", "}"]
    return "\n".join(lines)


_GENERATORS = {"curl": _curl, "python": _python, "fetch": _fetch, "go": _go, "dart": _dart}
