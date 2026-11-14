"""Prepare runtime configuration and version metadata for the frozen engine."""
import re
from pathlib import Path


def replace_sysconfig(pure, code_cache, workpath, name, values, prefix):
    index, = (i for i, entry in enumerate(pure) if entry[0] == name)
    # Paths occur in plain values, lists, assignments and compiler include/library flags.
    path = re.compile(r"(?:(?<![^\s=:,'\"])|(?<=-I)|(?<=-L)|(?<=-F))" + re.escape(prefix)
                      + r"(?=/|[\s:,'\"]|$)")
    lines = ["from sys import prefix", "build_time_vars = {"]
    for key, value in values.items():
        parts = path.split(value) if isinstance(value, str) else []
        expression = " + prefix + ".join(map(repr, parts)) if len(parts) > 1 else repr(value)
        lines.append(f"    {key!r}: {expression},")
    lines.append("}")
    destination = Path(workpath) / (name + ".py")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pure[index] = (name, str(destination), pure[index][2])
    if code_cache is not None:
        code_cache.pop(name, None)


def project_metadata(datas, document):
    """Keep the project version document and the dependency resources selected by Analysis."""
    project_directory = re.compile(r"home_screen_organizer(?:-[0-9][^/]*)?\.(?:dist|egg)-info/")
    return [entry for entry in datas if entry[0] == document or not project_directory.match(entry[0])]
