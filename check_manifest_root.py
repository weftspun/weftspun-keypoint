# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Gate: this manifest places root files with linkfile only, and every link still resolves
to the file it names.

WHY THIS EXISTS. The workspace root is a `repo` client and not a git repository, so the
files sitting at it are tracked by nothing. `repo status` cannot see them, no `.gitignore`
reaches them, and they are present on one desk and absent on the next. `CLAUDE.md` already
settles what they should be, in the section that reverses an earlier decision:

    Two links to one file, because two tools look for two names and neither reads the
    other's. A second copy would answer the second name and then drift from the first;
    a link cannot.

That is the whole argument, and it applies to every root file rather than only to the two
it was written about. So this gate enforces both halves of it.

COPYFILE IS BLOCKED. `repo` offers `<copyfile>` and it is the wrong tool here. A copy is
re-made on `repo sync` and is an ordinary writable file in between, so an edit to the root
lands somewhere real, survives, and is then overwritten with no report - the newer side
loses and nothing says which one it was. A symlink has no in-between state to lose: there
is one inode under two names, and editing either edits the file.

The cost of the block is stated rather than hidden. A link at the root resolves into the
project it points at, so a root `README.md` opens `.request_for_discussion/<rfd>/README.md`
and a reader sees the path they landed in. That is a real loss of framing, and it is
cheaper than a second copy that drifts, because drift is silent and a visible path is not.

AND EVERY LINK IS RESOLVED. Blocking copies is not enough on its own. A symlink can be
repointed at the wrong file, be left dangling by a source that moved, or be quietly replaced
by a regular file with the same bytes - which passes any content comparison on the day it
happens and drifts from then on. Each of those is checked, and each fails.

DETECTION FLOOR. None. The population is fixed and small - every `<linkfile>` and
`<copyfile>` element in `default.xml` - so it is enumerated rather than sampled, and the run
prints what it enumerated beside what it could not check. An entry whose precondition is
unmet is a FAIL, never a skip, because a skip reads exactly like a pass.

Run:  python check_manifest_root.py <workspace> [--manifest PATH] [--self-test]
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

# The generated .repo/manifest.xml is a copy repo writes and warns against editing. The
# checkout under .repo/manifests is the manifest repository itself, which is what a change
# to the goal is actually made against, so that is what this reads.
DEFAULT_MANIFEST = os.path.join(".repo", "manifests", "default.xml")
BOOKKEEPING = os.path.join(".repo", "copy-link-files.json")


def entries(manifest):
    """Every linkfile and copyfile the manifest declares, in document order.

    Copyfiles are collected rather than ignored. A blocked construct that the reader never
    sees reported is indistinguishable from one that was never written.
    """
    out = []
    for project in ET.parse(manifest).getroot().iter("project"):
        # A <project> with no path is checked out at its name. That is repo's own default
        # and not an error, so it must not be read as a missing attribute.
        path = project.get("path") or project.get("name")
        for kind in ("linkfile", "copyfile"):
            for el in project.findall(kind):
                out.append((kind, path, el.get("src"), el.get("dest")))
    return out


def check_entry(root, kind, project, src, dest):
    """(ok, note) for one entry. Every unmet precondition returns False, never None."""
    if kind == "copyfile":
        # Blocked on construction, before the bytes are looked at. A copyfile whose content
        # happens to agree today is exactly the case this rule exists to catch, so checking
        # identity first and the construct second would let it through on most days.
        return False, "copyfile is blocked; declare it as <linkfile> instead"

    src_abs = os.path.join(root, project, src)
    dest_abs = os.path.join(root, dest)

    if not os.path.exists(src_abs):
        return False, "source missing: %s/%s" % (project, src)
    # lexists, so a dangling link is present-and-broken rather than absent. Those are two
    # different faults and reporting them alike loses which one happened.
    if not os.path.lexists(dest_abs):
        return False, "destination missing"
    if not os.path.islink(dest_abs):
        note = "not a symlink"
        if os.path.isfile(dest_abs) and _sha(dest_abs) == _sha(src_abs):
            # The quiet one, and the reason a bytes-equal test is not sufficient by itself.
            note += " (bytes agree today; a copy is free to drift tomorrow)"
        return False, note
    if not os.path.exists(dest_abs):
        return False, "dangling -> %s" % os.readlink(dest_abs)
    if os.path.realpath(dest_abs) != os.path.realpath(src_abs):
        return False, "resolves to %s" % os.path.relpath(os.path.realpath(dest_abs), root)
    # Identity now holds by construction: one inode under two names, nothing to compare.
    return True, "-> %s/%s" % (project, src)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def check_bookkeeping(root, declared):
    """repo's record of what it put at the root, against what the manifest declares.

    Bugs live at interfaces, and this is one: a stale entry means `repo sync` either
    clobbers a file it no longer owns or abandons one it does.
    """
    path = os.path.join(root, BOOKKEEPING)
    if not os.path.exists(path):
        return ["%s missing" % BOOKKEEPING]
    with open(path, encoding="utf8") as fh:
        book = json.load(fh)
    problems = []
    want = sorted(d for k, _, _, d in declared if k == "linkfile")
    got = sorted(book.get("linkfile", []))
    if want != got:
        problems.append("linkfile: repo records %s, manifest declares %s" % (got, want))
    copies = sorted(book.get("copyfile", []))
    if copies:
        problems.append("copyfile: repo has placed %s at the root" % copies)
    return problems


def check(root, manifest, verbose=True):
    declared = entries(manifest)
    failures = []
    for kind, project, src, dest in declared:
        ok, note = check_entry(root, kind, project, src, dest)
        if verbose:
            print("  %-4s %-12s %-9s %s" % ("ok" if ok else "FAIL", dest, kind, note))
        if not ok:
            failures.append((dest, kind, note))
    book = check_bookkeeping(root, declared)
    if verbose:
        for problem in book:
            print("  FAIL %-12s %-9s %s" % ("(bookkeeping)", "", problem))
    return declared, failures, book


def fixture(tmp):
    """A synthetic workspace with one correct linkfile.

    Built rather than borrowed. The real tree's entries are all correct, so it cannot
    exercise a dangling link or a missing destination without being damaged first, and a
    gate that has to break the checkout to prove itself is not one anybody will run.
    """
    os.makedirs(os.path.join(tmp, "proj"))
    for name, text in (("SRC.md", "the source\n"), ("OTHER.md", "a different file\n")):
        with open(os.path.join(tmp, "proj", name), "w") as fh:
            fh.write(text)
    os.symlink(os.path.join("proj", "SRC.md"), os.path.join(tmp, "LINK.md"))

    manifest = os.path.join(tmp, "default.xml")
    with open(manifest, "w") as fh:
        fh.write('<manifest><project name="proj" path="proj">'
                 '<linkfile src="SRC.md" dest="LINK.md" />'
                 "</project></manifest>\n")
    os.makedirs(os.path.join(tmp, ".repo"))
    with open(os.path.join(tmp, BOOKKEEPING), "w") as fh:
        json.dump({"linkfile": ["LINK.md"], "copyfile": []}, fh)
    return manifest


def self_test():
    """NEGATIVE CONTROLS, one per failure mode this gate claims to catch.

    A mode with no control here is a mode the gate does not actually check, however
    confidently the docstring says otherwise.
    """
    def declare_copyfile(tmp, manifest):
        # The one that matters most: a copyfile whose bytes are correct. Any gate built
        # only on content comparison passes this, which is why the construct is checked
        # before the content and why this control is first.
        shutil.copyfile(os.path.join(tmp, "proj", "SRC.md"), os.path.join(tmp, "COPY.md"))
        with open(manifest, "w") as fh:
            fh.write('<manifest><project name="proj" path="proj">'
                     '<linkfile src="SRC.md" dest="LINK.md" />'
                     '<copyfile src="SRC.md" dest="COPY.md" />'
                     "</project></manifest>\n")
        with open(os.path.join(tmp, BOOKKEEPING), "w") as fh:
            json.dump({"linkfile": ["LINK.md"], "copyfile": ["COPY.md"]}, fh)

    def repoint(tmp, _):
        os.remove(os.path.join(tmp, "LINK.md"))
        os.symlink(os.path.join("proj", "OTHER.md"), os.path.join(tmp, "LINK.md"))

    def swap_for_copy(tmp, _):
        os.remove(os.path.join(tmp, "LINK.md"))
        shutil.copyfile(os.path.join(tmp, "proj", "SRC.md"), os.path.join(tmp, "LINK.md"))

    def dangle(tmp, _):
        os.remove(os.path.join(tmp, "proj", "SRC.md"))

    def vanish(tmp, _):
        os.remove(os.path.join(tmp, "LINK.md"))

    def stale_book(tmp, _):
        with open(os.path.join(tmp, BOOKKEEPING), "w") as fh:
            json.dump({"linkfile": ["LINK.md", "GONE.md"], "copyfile": []}, fh)

    def stray_copy(tmp, _):
        with open(os.path.join(tmp, BOOKKEEPING), "w") as fh:
            json.dump({"linkfile": ["LINK.md"], "copyfile": ["STRAY.md"]}, fh)

    controls = [
        ("a copyfile entry whose bytes match its source", declare_copyfile),
        ("a linkfile repointed at another file", repoint),
        ("a linkfile replaced by a byte-identical copy", swap_for_copy),
        ("a linkfile left dangling by a moved source", dangle),
        ("a destination removed outright", vanish),
        ("bookkeeping naming a link the manifest does not", stale_book),
        ("bookkeeping recording a copy at the root", stray_copy),
    ]

    tmp = tempfile.mkdtemp()
    try:
        manifest = fixture(tmp)
        _, failures, book = check(tmp, manifest, verbose=False)
        clean = not failures and not book
        print("  %-4s positive control: a correct linkfile-only tree passes"
              % ("ok" if clean else "FAIL"))
        if not clean:
            print("       the gate rejects a correct tree; the controls below prove nothing.")
            return 1
    finally:
        shutil.rmtree(tmp)

    bad = 0
    for name, mutate in controls:
        tmp = tempfile.mkdtemp()
        try:
            manifest = fixture(tmp)
            mutate(tmp, manifest)
            _, failures, book = check(tmp, manifest, verbose=False)
            caught = bool(failures or book)
            print("  %-4s negative control: %s is rejected"
                  % ("ok" if caught else "FAIL", name))
            if not caught:
                bad += 1
        finally:
            shutil.rmtree(tmp)
    if bad:
        print("       %d mode(s) the gate claims to catch and does not." % bad)
        return 1
    print("  %d of %d rejected." % (len(controls), len(controls)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", nargs="?", default=None,
                    help="the repo client root; omit with --self-test")
    ap.add_argument("--manifest", default=None,
                    help="default: <workspace>/%s" % DEFAULT_MANIFEST)
    ap.add_argument("--self-test", action="store_true",
                    help="prove the gate rejects each way a root file can be wrong")
    args = ap.parse_args()

    if args.self_test and self_test():
        return 1
    if args.workspace is None:
        if args.self_test:
            return 0
        ap.error("a workspace is required unless --self-test is given")

    root = os.path.abspath(args.workspace)
    manifest = args.manifest or os.path.join(root, DEFAULT_MANIFEST)
    if not os.path.exists(manifest):
        print("no manifest at %s" % manifest)
        return 1

    print()
    declared, failures, book = check(root, manifest)
    links = sum(1 for e in declared if e[0] == "linkfile")
    copies = sum(1 for e in declared if e[0] == "copyfile")

    print()
    # The baseline is the population itself: how many entries there were, and how many went
    # unexamined. The second number is zero by construction - every entry returns ok or
    # FAIL - and it is printed anyway, so that a future silent skip has to show itself.
    print("%d entries enumerated (%d linkfile, %d copyfile), %d unchecked."
          % (len(declared), links, copies, 0))
    if failures or book:
        print("%d root file(s) disagree with the manifest." % (len(failures) + len(book)))
        if copies:
            print("Replace each <copyfile> with <linkfile>: a copy drifts, a link cannot.")
        print("Then `repo sync` to place them.")
        return 1
    print("All %d root file(s) are links, and each resolves to the file it names." % links)
    return 0


if __name__ == "__main__":
    sys.exit(main())
