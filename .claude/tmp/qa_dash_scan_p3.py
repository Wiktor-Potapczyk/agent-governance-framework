import subprocess, sys, os

VAULT = r"C:\Users\WiktorPotapczyk\Desktop\Vault"
BANNED = {
    0x2014: "U+2014 EM DASH",
    0x2013: "U+2013 EN DASH",
    0x2012: "U+2012 FIGURE DASH",
    0x2212: "U+2212 MINUS SIGN",
    0x2015: "U+2015 HORIZONTAL BAR",
}

artifacts = [
    r"Projects\Agent-Governance-Research\work\2026-08-18-hermes-p3-build-record.md",
    r"Projects\Agent-Governance-Research\work\2026-08-18-hermes-p3-implementation-plan.md",
    r"Projects\Agent-Governance-Research\work\2026-08-18-hermes-p3-sink-vocabulary-baseline.md",
]

total_hits = 0

def scan_text(label, text):
    global total_hits
    hits = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        for ch in line:
            cp = ord(ch)
            if cp in BANNED:
                hits += 1
                total_hits += 1
                print(f"HIT {label} line {lineno}: {BANNED[cp]} :: {line[:80]!r}")
    print(f"{label}: {hits} banned dash hits")

for rel in artifacts:
    p = os.path.join(VAULT, rel)
    with open(p, "rb") as f:  # byte-safe read, no stdin pipe
        raw = f.read()
    scan_text(rel, raw.decode("utf-8"))

# P3-added region of hook_activity_report.py: added lines of commit e18f0fc
r = subprocess.run(
    ["git", "-C", VAULT, "diff", "e18f0fc^", "e18f0fc", "--",
     ".claude/scripts/hook_activity_report.py"],
    capture_output=True)
if r.returncode != 0:
    print("GIT DIFF FAILED:", r.stderr.decode("utf-8", "replace")); sys.exit(2)
diff_text = r.stdout.decode("utf-8", "replace")
added = [l[1:] for l in diff_text.splitlines()
         if l.startswith("+") and not l.startswith("+++")]
print(f"diff added lines count: {len(added)}")
scan_text("hook_activity_report.py (P3 added lines, e18f0fc)", "\n".join(added))

print(f"TOTAL banned-dash hits: {total_hits}")
sys.exit(0 if total_hits == 0 else 1)
