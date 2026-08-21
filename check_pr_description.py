# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Gate: a pull request description in THIS repository is one heading, one paragraph,
tables, lists and diagrams, and at most 144 words of prose.

WHY THIS EXISTS, AND WHY ONLY HERE. This repository holds one file. `default.xml` says what
is in the keypoint goal and which side each project sits on, and a change to it is usually a
line or two. The reasoning still has to travel, because `CLAUDE.md` sends it to the commit
message and the pull request rather than into the file.

Those two destinations are not the same size. A commit message is read by whoever runs
`git log` and may run as long as it needs to. A pull request description is read once, in a
review tab, by somebody deciding whether a two-line manifest change is right, and at that
length prose stops being evidence and becomes a wall. The bound is tight enough to force the
shape: state it, table the entries, draw it, stop.

THIS BOUND IS LOCAL AND MUST NOT LEAK. Elsewhere the opposite rule holds. `weftspun/logbook`
and `weftspun/request-for-discussion` want the measurement, the apparatus and the retraction
written out, and 144 words would truncate all three. So this gate ships in the manifest
repository and travels with nothing.

THE SHAPE, AS BLOCK NODES AT THE TOP LEVEL OF THE AST:

    heading                 at most one
    paragraph               exactly one
    table, list, fence      any number
    anything else           rejected

Read from the AST rather than from the source text, because a `#` inside a code span is not
a heading and a hard-wrapped sentence is not two paragraphs. Paragraphs nested inside list
items or table cells belong to their container and are not counted against the one; a list
whose items may not contain prose is not a list anybody can use.

Tables are GFM rather than core CommonMark, so the parser is CommonMark with the table rule
enabled - the dialect GitHub actually renders the description in. A gate measuring a
different grammar than the reader sees would be measuring the convenient proxy.

WORDS ARE PROSE ONLY, AND DIAGRAMS ARE UNBOUNDED. Fenced blocks are excluded from the count
entirely, however long they run. A diagram is not read at the speed prose is: a reader scans
it or skips it, and charging it against the same budget would price the clearest thing in
the description as if it were the most expensive. Everything outside a fence counts,
including table cells and markup, which over-counts slightly against the author - the
direction an upper bound should err.

Run:  python check_pr_description.py --pr 3 [--repo owner/name]
      python check_pr_description.py --body-file draft.md
      python check_pr_description.py --self-test
"""

import argparse
import json
import subprocess
import sys

try:
    from markdown_it import MarkdownIt
except ImportError:  # reported as a FAIL by main(), never as a clean run
    MarkdownIt = None

MAX_WORDS = 144
MAX_HEADINGS = 1
EXACT_PARAGRAPHS = 1
# Tables and lists carry the entries; a fence carries a diagram. Anything absent from this
# set is rejected by omission, so a block type nobody anticipated fails loudly rather than
# passing quietly.
REPEATABLE = {"bullet_list_open", "ordered_list_open", "table_open", "fence", "code_block"}
DIAGRAM = {"fence", "code_block"}


def parser():
    return MarkdownIt("commonmark").enable("table")


def top_level(body):
    """Every top-level block token, with its source line span.

    Selected by `block` rather than by a name ending in `_open`, because not every block
    node is a container: `hr`, `fence`, `code_block` and `html_block` are standalone tokens,
    and a filter written around `_open` skips all four. The horizontal-rule control in
    self_test() is here because that is exactly the hole it found.
    """
    return [(t.type, t.map) for t in parser().parse(body)
            if t.level == 0 and t.block and not t.type.endswith("_close")]


def prose_words(body, blocks):
    """Words outside every fenced block. Diagrams are unbounded, so they do not count."""
    lines = body.splitlines()
    inside = set()
    for kind, span in blocks:
        if kind in DIAGRAM and span:
            inside.update(range(span[0], span[1]))
    return sum(len(line.split()) for n, line in enumerate(lines) if n not in inside)


def check(body, verbose=True):
    """(failures, blocks). Every rule reports a line; none of them can be skipped."""
    blocks = top_level(body)
    kinds = [k for k, _ in blocks]
    headings = kinds.count("heading_open")
    paragraphs = kinds.count("paragraph_open")
    other = [k for k in kinds
             if k not in REPEATABLE and k not in ("heading_open", "paragraph_open")]
    words = prose_words(body, blocks)
    diagrams = sum(1 for k in kinds if k in DIAGRAM)

    rules = [
        (headings <= MAX_HEADINGS, "headings", "%d (at most %d)" % (headings, MAX_HEADINGS)),
        (paragraphs == EXACT_PARAGRAPHS, "paragraphs",
         "%d (exactly %d)" % (paragraphs, EXACT_PARAGRAPHS)),
        (not other, "block types",
         "disallowed: %s" % ", ".join(sorted(set(other))) if other
         else "tables, lists and diagrams only"),
        (words <= MAX_WORDS, "prose words",
         "%d of %d, with %d diagram(s) exempt" % (words, MAX_WORDS, diagrams)),
    ]
    failures = []
    for ok, name, detail in rules:
        if verbose:
            print("  %-4s %-12s %s" % ("ok" if ok else "FAIL", name, detail))
        if not ok:
            failures.append((name, detail))
    return failures, blocks


def fetch(repo, number):
    cmd = ["gh", "pr", "view", str(number), "--json", "body"]
    if repo:
        cmd += ["--repo", repo]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode:
        return None, out.stderr.strip()
    return json.loads(out.stdout)["body"], None


def self_test():
    """NEGATIVE CONTROLS, one per way the shape can be wrong.

    The positive control runs first and on its own terms: if the gate rejects a body that is
    already correct, every rejection below it is noise rather than evidence.
    """
    good = ("## Title\n\nOne paragraph saying what changed and why.\n\n"
            "| a | b |\n| - | - |\n| 1 | 2 |\n\n- an entry\n\n```mermaid\ngraph LR\nA-->B\n```\n")
    huge = "```mermaid\ngraph LR\n" + "\n".join(
        "N%d-->N%d" % (i, i + 1) for i in range(400)) + "\n```\n"

    controls = [
        ("two paragraphs", good.replace("and why.\n", "and why.\n\nA second paragraph.\n")),
        ("two headings", good + "\n## Another heading\n"),
        ("no paragraph at all", "## Title\n\n- only a list\n"),
        ("a blockquote", good + "\n> quoted prose\n"),
        ("a horizontal rule", good + "\n---\n"),
        ("%d prose words" % (MAX_WORDS + 1),
         "## T\n\n" + " ".join("w%d" % i for i in range(MAX_WORDS + 1)) + "\n"),
        ("%d words hidden in a table" % (MAX_WORDS + 1),
         "## T\n\nx\n\n| a |\n| - |\n" + "".join(
             "| %s |\n" % " ".join("w%d" % j for j in range(10))
             for _ in range((MAX_WORDS // 10) + 2))),
    ]

    failures, blocks = check(good, verbose=False)
    print("  %-4s positive control: heading, paragraph, table, list and diagram pass"
          % ("ok" if not failures else "FAIL"))
    if failures:
        print("       rejected a correct body (%s); the controls below prove nothing."
              % ", ".join(n for n, _ in failures))
        print("       blocks seen: %s" % [k for k, _ in blocks])
        return 1

    # The exemption is a claim in its own right and needs its own positive control. Without
    # it, a gate that silently counted fence lines would still pass every case above.
    big = check(good + "\n" + huge, verbose=False)[0]
    print("  %-4s positive control: an 800-line diagram does not spend the word budget"
          % ("ok" if not big else "FAIL"))
    if big:
        print("       diagrams are supposed to be unbounded and this one was charged.")
        return 1

    bad = 0
    for name, body in controls:
        caught = bool(check(body, verbose=False)[0])
        print("  %-4s negative control: %s is rejected" % ("ok" if caught else "FAIL", name))
        if not caught:
            bad += 1
    if bad:
        print("       %d shape(s) the gate claims to reject and does not." % bad)
        return 1
    print("  %d of %d rejected." % (len(controls), len(controls)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", type=int, help="pull request number to read with gh")
    ap.add_argument("--repo", default=None, help="owner/name; defaults to the checkout")
    ap.add_argument("--body-file", help="read the description from a file instead")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the gate rejects each way the shape can be wrong")
    args = ap.parse_args()

    if MarkdownIt is None:
        # An unmet precondition is a FAIL. A missing parser must not read as a clean run.
        print("FAIL markdown-it-py is not installed, so the shape cannot be measured.")
        print("     pip install markdown-it-py")
        return 1

    if args.self_test and self_test():
        return 1

    if args.body_file:
        with open(args.body_file, encoding="utf8") as fh:
            body = fh.read()
    elif args.pr:
        body, err = fetch(args.repo, args.pr)
        if body is None:
            print("FAIL could not read PR #%d: %s" % (args.pr, err))
            return 1
    elif args.self_test:
        return 0
    else:
        ap.error("one of --pr, --body-file or --self-test is required")

    if not body.strip():
        print("FAIL the description is empty.")
        return 1

    print()
    failures, _ = check(body)
    print()
    if failures:
        print("The description is outside the shape this repository allows, on %d rule(s)."
              % len(failures))
        print("One heading, one paragraph, tables, lists and diagrams, %d words of prose."
              % MAX_WORDS)
        print("Longer reasoning belongs in the commit message, which has no bound.")
        return 1
    print("Within the shape: one heading, one paragraph, tables, lists and diagrams,")
    print("%d words of prose, diagrams unbounded." % MAX_WORDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
