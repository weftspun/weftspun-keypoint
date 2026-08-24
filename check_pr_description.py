# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Gate: a pull request description in THIS repository has the shape people actually scan -
either no headings or at least two, every heading with content under it, paragraphs short
enough to be read rather than skipped, and any number of tables, lists and diagrams.

WHY THIS EXISTS, AND WHY ONLY HERE. This repository holds one file. `default.xml` says what
is in the keypoint goal and which side each project sits on, and a change to it is usually a
line or two. The reasoning still has to travel, because `CLAUDE.md` sends it to the commit
message and the pull request rather than into the file.

THE SHAPE, AS BLOCK NODES AT THE TOP LEVEL OF THE AST:

    heading         0, or 2 and up      never exactly one
    heading         never two in a row  every heading introduces content
    paragraph       1 and up            each at most 35 words
    table           any number          any size, uncounted
    list            any number          any size, uncounted
    fenced diagram  any number          any size, uncounted
    all prose       at most 72 words    headings and paragraphs together
    anything else   rejected

WHY THIS SHAPE AND NOT ANOTHER. It is not taste. Pernice (2019) [1] names two patterns a
reader falls into. The LAYER-CAKE pattern - fixating on headings, dropping into the body text
between them only deliberately - happens on pages with visually distinct headings, and it is
the efficient one: a reader scans straight to the section they need. The F-PATTERN happens
instead when a page is "columns of text with little text that stands out", and is the
low-efficiency case, where people "inadvertently miss meaningful information".

That finding is about which shape gets read, not about which is prettier, which is why it is
the one worth encoding. The measurement on pull requests specifically agrees: Watanabe et al.
(2026) [2] scored description characteristics as densities per 1,000 characters and found
header density and list density associated with faster reviewer response and shorter
completion time, reporting a medium-to-large effect size for structure against completion
time, and naming limited use of headers and lists as a cause of reduced readability.

Both are associational rather than causal, and [2] says so itself: presentation does not
determine acceptance, and code quality remains the central factor in whether a pull request
lands. What is being claimed here is narrower and is all the rule needs - that this shape is
read more completely than the alternative, not that it makes a change correct.

RETRACTED: NO HEADINGS AT ALL. An earlier version of this gate rejected every heading. The
argument was that a lone heading restates the pull request title one line below the pull
request title, and that argument is correct - it is why "exactly one" is still rejected
below. What it did not survive is generalisation. A heading that is one of several is not
restating the title, it is naming a section, and banning all of them to stop the degenerate
case forced every description into the F-pattern shape NN/g measured as the one where
readers miss things. The rule is kept where it holds and dropped where it does not.

EVERY HEADING INTRODUCES CONTENT. Two headings in a row means the first named a section with
nothing in it. The guidance in [1] is that a subheading is "descriptive of all topics in the
section, and only topics in the section", which an empty section cannot satisfy. This is
also the cheapest way a document fakes structure: stack the headings, and it looks scannable
in outline and delivers nothing when scanned.

PARAGRAPHS ARE BOUNDED INDIVIDUALLY, NOT ONLY IN TOTAL. A single 72-word block is exactly
the "little text that stands out" case. Guidance for scannable prose puts a paragraph at two
to four sentences; the gate bounds words instead, at 35, because words are countable exactly
and sentences are not - splitting on full stops mistakes every abbreviation for a sentence
end, which is the convenient proxy rather than the quantity. 35 words is roughly two
sentences of ordinary technical prose, and the conversion is stated here rather than buried
in a constant, so that a reader can disagree with it.

THE TWO BOUNDS HAVE TO STAY APART TO BOTH MEAN SOMETHING. Halving the total without halving
the paragraph would have left the per-paragraph rule binding only in the two-word window
between 70 and 72 - a rule that has stopped doing anything while still appearing in the
output as though it had. The ratio is what carries the design: roughly two paragraphs to the
budget, so each bound still catches a shape the other cannot.

STRUCTURE IS NEVER MEASURED FOR SIZE. A table is scanned by column, a list by item, a diagram
by following an arrow, and a reader takes what they need and stops. An earlier version
counted table cells against the prose budget, which priced the most scannable thing in a
description as if it were the least, and in practice made the author shorten accurate prose
to afford a table. What goes first under a word budget is the qualifying clause - the
retraction, the baseline, the cost stated rather than hidden - which is what this workspace
asks a description to carry.

Read from the AST rather than from the source text, because a `#` inside a code span is not
a heading and a hard-wrapped sentence is not two paragraphs. Paragraphs nested inside list
items or table cells belong to their container: not counted against the paragraph rules, and
their words not counted against the budget.

Tables are GFM rather than core CommonMark, so the parser is CommonMark with the table rule
enabled - the dialect GitHub actually renders the description in. A gate measuring a
different grammar than the reader sees would be measuring the convenient proxy.

REFERENCES. Cited in full rather than linked, because a bare URL rots and a reader six
months from now needs to know whose finding this was and when.

[1] Pernice, Kara. "The Layer-Cake Pattern of Scanning Content on the Web."
    Nielsen Norman Group, 4 August 2019.
    https://www.nngroup.com/articles/layer-cake-pattern-scanning/

[2] Watanabe, Kan; Tsuchida, Rikuto; Monno, Takahiro; Huang, Bin; Yamasaki, Kazuma;
    Fan, Youmei; Shimari, Kazumasa; Matsumoto, Kenichi. "How AI Coding Agents Communicate:
    A Study of Pull Request Description Characteristics and Human Review Responses."
    arXiv:2602.17084, 19 February 2026. https://arxiv.org/abs/2602.17084

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

MAX_PROSE_WORDS = 72       # headings and paragraphs together
MAX_PARAGRAPH_WORDS = 35   # about two sentences; see the docstring for the conversion
# Tables and lists carry the entries; a fence carries a diagram. Anything absent from these
# two sets is rejected by omission, so a block type nobody anticipated fails loudly rather
# than passing quietly.
STRUCTURE = {"bullet_list_open", "ordered_list_open", "table_open", "fence", "code_block"}
PROSE = {"heading_open", "paragraph_open"}


def parser():
    return MarkdownIt("commonmark").enable("table")


def top_level(body):
    """Every top-level block token, as (type, source line span), in document order.

    Selected by `block` rather than by a name ending in `_open`, because not every block
    node is a container: `hr`, `fence`, `code_block` and `html_block` are standalone tokens,
    and a filter written around `_open` skips all four. The horizontal-rule control in
    self_test() is here because that is exactly the hole it found.

    Document order is preserved and load-bearing: two headings in a row is a rule below, and
    it cannot be seen from counts alone.
    """
    return [(t.type, t.map) for t in parser().parse(body)
            if t.level == 0 and t.block and not t.type.endswith("_close")]


def words_in(body, span):
    """Words on a block's source lines. Markup counts, which over-counts against the author.

    That is the direction an upper bound should err: the gate never reports fewer words than
    a reader would find.
    """
    lines = body.splitlines()
    return sum(len(lines[n].split()) for n in range(*span)) if span else 0


def check(body, verbose=True):
    """(failures, blocks). Every rule reports a line; none of them can be skipped."""
    blocks = top_level(body)
    kinds = [k for k, _ in blocks]
    headings = kinds.count("heading_open")
    para_words = [words_in(body, s) for k, s in blocks if k == "paragraph_open"]
    other = [k for k in kinds if k not in STRUCTURE and k not in PROSE]
    stacked = sum(1 for a, b in zip(kinds, kinds[1:])
                  if a == "heading_open" and b == "heading_open")
    over = [n for n in para_words if n > MAX_PARAGRAPH_WORDS]
    prose = sum(words_in(body, s) for k, s in blocks if k in PROSE)
    free = sum(1 for k in kinds if k in STRUCTURE)

    rules = [
        (headings != 1, "headings",
         "%d (0 or 2+; exactly one restates the PR title)" % headings),
        (stacked == 0, "heading order",
         "%d heading(s) with nothing under them" % stacked if stacked
         else "every heading introduces content"),
        (len(para_words) >= 1, "paragraphs", "%d (at least one)" % len(para_words)),
        (not over, "paragraph size",
         "longest %d words (at most %d each)"
         % (max(para_words or [0]), MAX_PARAGRAPH_WORDS)),
        (not other, "block types",
         "disallowed: %s" % ", ".join(sorted(set(other))) if other
         else "%d table/list/diagram block(s), all unmeasured" % free),
        (prose <= MAX_PROSE_WORDS, "prose words",
         "%d of %d in headings and paragraphs" % (prose, MAX_PROSE_WORDS)),
    ]
    failures = []
    for ok, name, detail in rules:
        if verbose:
            print("  %-4s %-15s %s" % ("ok" if ok else "FAIL", name, detail))
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

    The positive controls run first and on their own terms: if the gate rejects a body that
    is already correct, every rejection below is noise rather than evidence.
    """
    para = "A short paragraph of prose saying what changed and why it changed.\n"
    layered = ("## First section\n\n" + para + "\n| a | b |\n| - | - |\n| 1 | 2 |\n\n"
               "## Second section\n\n" + para + "\n- an entry\n\n"
               "```mermaid\ngraph LR\nA-->B\n```\n")
    headless = para + "\n- an entry\n"
    # The exemption is a claim in its own right, so it gets its own positive control. A gate
    # that quietly counted table cells or list items would pass every other case here.
    big_structure = (
        para + "\n| a | b |\n| - | - |\n"
        + "".join("| %s | %s |\n" % (" ".join("w%d" % j for j in range(12)),
                                     " ".join("x%d" % j for j in range(12)))
                  for _ in range(60))
        + "\n" + "".join("- %s\n" % " ".join("item%d" % j for j in range(12))
                         for _ in range(60))
        + "\n```mermaid\ngraph LR\n"
        + "\n".join("N%d-->N%d" % (i, i + 1) for i in range(400)) + "\n```\n")

    def prose_of(total):
        """A heading-free body of exactly `total` prose words, in legal-sized paragraphs.

        Exactly, because the total rule is the one bound whose edge nothing else pins. The
        per-paragraph edge is already pinned from both sides: its negative is MAX + 1 words
        and the total's negative below contains paragraphs of exactly MAX, which the
        equality check requires NOT to trip paragraph size.
        """
        n, out = 0, []
        while n < total:
            take = min(MAX_PARAGRAPH_WORDS, total - n)
            out.append(" ".join("w%d" % i for i in range(n, n + take)))
            n += take
        return "\n\n".join(out) + "\n"

    positives = [
        ("two headings, short paragraphs, table, list and diagram", layered),
        ("no headings at all, which is still a legal shape", headless),
        ("a 60-row table, a 60-item list and an 800-line diagram cost nothing",
         big_structure),
        # The budget is a ceiling that INCLUDES its own value. Without this, `<=` turning
        # into `<` rejects every body at exactly the limit and no control says a word.
        ("a body of exactly %d prose words, which is legal" % MAX_PROSE_WORDS,
         prose_of(MAX_PROSE_WORDS)),
    ]
    # Paragraphs at exactly the per-paragraph bound, and enough of them to break the total.
    # Both numbers are DERIVED rather than typed: a literal that is legal under one pair of
    # bounds trips a different rule under another, and the loop below would still print ok.
    # That is the hole the expected-rule column below closes.
    # Third field: the rule each body must fail ON. A negative control rejected for some
    # other reason has not tested what it names, and reads identically in the output.
    negatives = [
        ("exactly one heading, which restates the title", "## Only one\n\n" + para,
         "headings"),
        ("two headings in a row, the first naming an empty section",
         "## First\n\n## Second\n\n" + para, "heading order"),
        ("no paragraph anywhere",
         "## First\n\n- only a list\n\n## Second\n\n- another\n", "paragraphs"),
        ("one paragraph of %d words" % (MAX_PARAGRAPH_WORDS + 1),
         " ".join("w%d" % i for i in range(MAX_PARAGRAPH_WORDS + 1)) + "\n",
         "paragraph size"),
        # ONE word over, not comfortably over. The earlier version of this control totalled
        # about 105 against a budget of 72, so raising or lowering the budget by one left it
        # rejecting just the same - it proved the rule existed and said nothing about where
        # it sits. Paired with the positive above, these two bodies differ by a single word
        # and straddle the edge. The per-paragraph rule cannot catch this body and the total
        # cannot catch a single long paragraph, so the two bounds each keep their own control.
        ("a body of %d prose words, one over the budget" % (MAX_PROSE_WORDS + 1),
         prose_of(MAX_PROSE_WORDS + 1), "prose words"),
        ("a blockquote", headless + "\n> quoted prose\n", "block types"),
        ("a horizontal rule", headless + "\n---\n", "block types"),
        ("a raw HTML block", headless + "\n<div>raw</div>\n", "block types"),
    ]

    for name, body in positives:
        failures, blocks = check(body, verbose=False)
        print("  %-4s positive control: %s" % ("ok" if not failures else "FAIL", name))
        if failures:
            print("       rejected a correct body: %s"
                  % "; ".join("%s %s" % (n, d) for n, d in failures))
            print("       the controls below would prove nothing. blocks: %s"
                  % [k for k, _ in blocks])
            return 1

    bad = 0
    for name, body, rule in negatives:
        fired = [n for n, _ in check(body, verbose=False)[0]]
        # EXACTLY the named rule, not merely including it. A body that trips three rules
        # proves nothing about any one of them, and "rule in fired" would call that ok -
        # which is how a control keeps reading green after the thing it isolates has moved.
        caught = fired == [rule]
        print("  %-4s negative control: %s is rejected on %s"
              % ("ok" if caught else "FAIL", name, rule))
        if not caught:
            bad += 1
            print("       fired instead: %s" % (", ".join(fired) or "nothing"))
    if bad:
        print("       %d shape(s) the gate claims to reject on a named rule and does not."
              % bad)
        return 1
    print("  %d of %d rejected." % (len(negatives), len(negatives)))
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
        print("Sections a reader can scan: no headings or two, each with content under it,")
        print("paragraphs of %d words or fewer, %d words of prose in total."
              % (MAX_PARAGRAPH_WORDS, MAX_PROSE_WORDS))
        print("Tables, lists and diagrams are unlimited. Move detail into one of those,")
        print("or into the commit message, which has no bound at all.")
        return 1
    print("Within the shape: scannable sections, paragraphs of %d words or fewer,"
          % MAX_PARAGRAPH_WORDS)
    print("%d words of prose, tables, lists and diagrams unmeasured." % MAX_PROSE_WORDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
