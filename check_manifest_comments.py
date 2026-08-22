# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Gate: the manifest carries no XML comments. Like JSON, it holds data and nothing else.

WHY THIS EXISTS. A comment beside a `<project>` is prose that no tool reads, nothing
renders, and no review process is obliged to keep true. It sits in the one file whose whole
job is to be machine-read, and it decays there quietly: the entry it explains gets a new
path, a new revision, or is deleted outright, and the paragraph above it goes on describing
the arrangement it was written for. Nothing in `repo`, in CI, or in a diff reports that the
two have parted company.

That failure has a name here already. It is the same one behind the submodule blocklist,
the `.local` rule and the `uv` rule: a fact in a second place, visible to nothing that
checks. A manifest comment is the purest form of it, because the manifest is otherwise
entirely checkable -- every path can be resolved, every revision fetched, every linkfile
followed -- and a comment is the one thing in the file that cannot be.

WHERE THE REASONING GOES INSTEAD, because it does not disappear. A commit message and a
pull request description carry it, which is where CLAUDE.md already sends the reasoning for
changes to other people's codebases. Both are attached to the change that made the decision
rather than floating above the line it affected, both are reviewed at the moment they are
written, and neither can go stale in place, because neither claims to describe the current
state of anything. An RFD carries the durable version.

THE COST, STATED RATHER THAN HIDDEN. CLAUDE.md's argument for manifests over submodules
says a bumped submodule "appears in a diff as a bare hash with no name, no branch and no
reason attached", and offers as the manifest's advantage that "a comment can sit beside the
entry". After this gate that clause is no longer true, and the section should be corrected
rather than left to be discovered. What survives is the larger half: a `<project>` entry
still carries a name, a path, a remote and a revision where `.gitmodules` carries a hash.

DETECTION FLOOR. None, and the reason is structural rather than statistical. XML forbids a
raw `<` inside an attribute value, so the string `<!--` cannot occur anywhere in a
well-formed manifest except as a comment open. The scan is therefore exact rather than
sampled, and it is a scan of text rather than of a parse tree because `ElementTree` discards
comments while reading -- parsing the file and looking for them finds nothing, always, which
is a check that passes on known-broken input.

Every file is also parsed, because a gate that only counts comment markers would accept a
manifest that no longer parses at all.

Run:  python check_manifest_comments.py [manifest ...] [--self-test]
"""

import pathlib
import re
import sys
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
COMMENT = re.compile(r"<!--(.*?)-->", re.S)


def default_manifests():
    return sorted(HERE.glob("*.xml"))


def check(paths):
    if not paths:
        print("  FAIL no manifest given and none found. A gate over nothing certifies nothing.")
        return 1

    failures = []
    for path in paths:
        if not path.exists():
            failures.append(f"{path}: does not exist")
            continue
        text = path.read_text(encoding="utf-8")

        try:
            ET.parse(path)
        except ET.ParseError as exc:
            failures.append(f"{path.name}: does not parse: {exc}")
            continue

        found = []
        for m in COMMENT.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            body = " ".join(m.group(1).split())
            found.append((line, len(m.group(0).splitlines()), body[:60]))

        if found:
            for line, span, body in found:
                plural = "" if span == 1 else "s"
                failures.append(
                    f"{path.name}:{line}: comment spanning {span} line{plural}: {body}..."
                )
            failures.append(
                f"{path.name}: {len(found)} comment(s). Put the reasoning in the commit "
                f"message and the pull request description, where it is reviewed and cannot "
                f"go stale in place."
            )
        else:
            elements = sum(1 for _ in ET.parse(path).getroot().iter())
            print(f"  ok   {path.name}: parses, {elements} elements, no comments")

    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


# --- negative controls ----------------------------------------------------------------
#
# Every manifest passing proves the manifests are clean. It does not prove this would
# notice one that is not, which is the only claim worth making. Four must fail and one
# must pass.


def self_test():
    import contextlib
    import io
    import tempfile

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="manifest-gate-"))
    clean = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n'
        '  <remote name="weftspun" fetch="https://github.com/weftspun" />\n'
        '  <project name="logbook" path="2-contract/logbook" remote="weftspun" '
        'revision="main" />\n</manifest>\n'
    )

    cases = [
        ("a block comment above an entry", False,
         clean.replace("  <project", "  <!-- The logbook is the record\n       others cite. -->\n  <project")),
        ("a one-line comment", False, clean.replace("  <project", "  <!-- placed here -->\n  <project")),
        ("a comment nested inside a project", False,
         clean.replace(' revision="main" />',
                       ' revision="main">\n    <!-- linked, not copied -->\n  </project>')),
        # Not a comment but worse: a gate that only counted `<!--` would wave this through.
        ("a manifest that does not parse", False, clean.replace("</manifest>", "")),
        ("a manifest with no comments", True, clean),
    ]

    print("controls:")
    bad = []
    for i, (label, should_pass, text) in enumerate(cases):
        # A distinct filename per case. Reusing one would hand a case its predecessor's
        # file, which is how a control ends up firing for somebody else's defect.
        dst = tmp / f"case{i}.xml"
        dst.write_text(text, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = check([dst])
        first = next((ln.strip() for ln in buf.getvalue().splitlines() if "FAIL" in ln), "")
        passed = rc == 0
        if passed == should_pass:
            print(f"  ok   {label}: " + ("passes, correctly" if passed else f"fails: {first[:96]}"))
        else:
            print(f"  BAD  {label}: " + ("passed and should not have" if passed
                                         else f"failed and should not have: {first[:70]}"))
            bad.append(label)
        dst.unlink()

    if bad:
        print(f"\n{len(bad)} control(s) wrong. The gate is decoration until they are not.")
        return 1
    print(f"\nAll {len(cases)} controls behaved.")
    return 0


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if "--self-test" in argv[1:] and not args:
        return self_test()
    rc = check([pathlib.Path(a) for a in args] or default_manifests())
    if "--self-test" in argv[1:]:
        print()
        rc |= self_test()
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
