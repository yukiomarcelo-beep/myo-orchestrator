#!/usr/bin/env python3
"""
Reconstruct correct 4-space indentation in myo_server.py.

The file had ALL leading indentation collapsed to exactly 1 space per line
(regardless of original depth). This script reconstructs the correct indentation
by parsing the Python structure.

Algorithm:
- Maintain a stack of indent levels
- When a line ends with ':', push +1 onto stack
- Dedent keywords (else/elif/except/finally) pop back to their matching level
- Blank lines and comment-only lines are preserved
- Lines inside multi-line strings are preserved as-is
- Continuation lines (inside open brackets) get extra indent
"""

import ast
import re

INPUT = "/Users/marceloyukio/Documents/orchestrator/myo_server.py"

src = open(INPUT, encoding='utf-8').read()
orig_lines = src.splitlines()

INDENT = '    '  # 4 spaces per level


# ======================================================================
# 1. Find multi-line string interior lines
# ======================================================================

def find_string_interiors(lines):
    """
    Returns set of 1-based line numbers that are INTERIOR to a multiline string
    (not the opening or first-content line, but lines where Python indentation
    doesn't apply).

    Returns: set of line numbers to preserve as-is.
    """
    interior = set()
    in_string = False
    delim = None

    for i, line in enumerate(lines):
        line_no = i + 1

        if not in_string:
            # Look for an unmatched opening triple-quote
            pos = 0
            while pos < len(line):
                # Skip escaped chars
                if pos < len(line) - 2 and line[pos:pos+3] in ('"""', "'''"):
                    d = line[pos:pos+3]
                    rest = line[pos+3:]
                    close = rest.find(d)
                    if close == -1:
                        # Opens but doesn't close on this line
                        in_string = True
                        delim = d
                        break
                    else:
                        pos = pos + 3 + close + 3
                        continue
                pos += 1
        else:
            # We are inside a string
            interior.add(line_no)
            if delim in line:
                # This line closes the string
                in_string = False
                delim = None

    return interior


string_interior = find_string_interiors(orig_lines)

# ======================================================================
# 2. Helper functions
# ======================================================================

def get_code_part(line):
    """Get the code part of a line, stripping trailing comments (simplified)."""
    # Simplified: just strip the line
    return line.strip()

def ends_with_colon(stripped):
    """True if the code line ends with ':' (block opener)."""
    # Strip inline comments first
    # Simple approach: check if stripped ends with ':'
    # Handles: def f():, if x:, else:, class C:, for x in y:, etc.
    s = stripped
    # Remove string literals at end (simplified)
    if s.endswith(':'):
        # Make sure it's not a dict literal like {k: v}
        # For our purposes, if the line contains typical Python block starters
        # and ends with ':', it's a block opener
        return True
    return False

def is_dedent_keyword(stripped):
    """True if line starts with else/elif/except/finally (block continuers)."""
    return re.match(r'^(else\s*:|elif\s+|elif\s*:|except\s*:|except\s+|finally\s*:)', stripped) is not None

def count_brackets(line):
    """Count net open brackets on this line (positive = more open than close)."""
    count = 0
    in_str = False
    str_char = None
    escape = False
    i = 0
    while i < len(line):
        c = line[i]
        if escape:
            escape = False
        elif c == '\\':
            escape = True
        elif in_str:
            if c == str_char:
                in_str = False
        else:
            if c in ('"', "'"):
                # Check for triple quotes
                if line[i:i+3] in ('"""', "'''"):
                    # Find matching triple quote
                    end = line.find(line[i:i+3], i+3)
                    if end != -1:
                        i = end + 3
                        continue
                    # Else: opens but doesn't close — stop bracket counting here
                    break
                in_str = True
                str_char = c
            elif c in ('(', '[', '{'):
                count += 1
            elif c in (')', ']', '}'):
                count -= 1
        i += 1
    return count

def is_blank_or_comment(stripped):
    return not stripped or stripped.startswith('#')

# ======================================================================
# 3. Main reconstruction loop
# ======================================================================

result_lines = []

# Stack of indent levels — each entry is the indent level for a block
# We start at level 0
indent_stack = [0]  # current indent level at top

bracket_depth = 0  # tracks unclosed brackets (continuation lines)
pending_indent = False  # if True, next code line should be indented +1

def current_level():
    return indent_stack[-1]

for i, line in enumerate(orig_lines):
    line_no = i + 1

    # Blank lines
    if not line.strip():
        result_lines.append('')
        bracket_depth = max(0, bracket_depth)  # can't be negative
        continue

    stripped = line.strip()

    # Comments at top level (non-indented) — preserve as-is
    if stripped.startswith('#') and not line.startswith(' '):
        result_lines.append(stripped)
        continue

    # Interior of multiline string — preserve exactly
    if line_no in string_interior:
        result_lines.append(line)
        continue

    # Decorator lines
    if stripped.startswith('@') and bracket_depth == 0 and not pending_indent:
        # Same level as current
        level = current_level()
        result_lines.append(INDENT * level + stripped)
        bracket_depth += count_brackets(stripped)
        continue

    # Handle continuation lines (inside open brackets)
    if bracket_depth > 0:
        # Continuation line — indent at current level + 1
        level = current_level()
        result_lines.append(INDENT * level + INDENT + stripped)
        bracket_depth += count_brackets(stripped)
        if bracket_depth < 0:
            bracket_depth = 0
        # If bracket depth returns to 0, check if line ends with ':'
        if bracket_depth == 0 and ends_with_colon(stripped):
            pending_indent = True
        continue

    # Normal Python code line
    # Determine the correct indentation level

    if pending_indent:
        # This line should be indented one more level than the opener
        new_level = current_level() + 1
        indent_stack.append(new_level)
        pending_indent = False
    elif is_dedent_keyword(stripped):
        # else/elif/except/finally — pop back to previous block level
        # These are at the same level as the matching if/try
        if len(indent_stack) > 1:
            indent_stack.pop()
        new_level = current_level()
    else:
        new_level = current_level()

    result_lines.append(INDENT * new_level + stripped)

    # Update bracket depth
    bracket_depth += count_brackets(stripped)

    # Set pending_indent for next code line
    if bracket_depth == 0 and ends_with_colon(stripped):
        pending_indent = True

    # Check if this line is a "block ender" — for simplicity, we don't
    # automatically dedent; instead we rely on the actual structure.
    # The key insight: in the original file, the code structure is correct,
    # just the whitespace is wrong. We track indent_stack by analyzing
    # what the code is doing.

fixed = '\n'.join(result_lines) + '\n'

# Check parse
try:
    ast.parse(fixed)
    print("SUCCESS: File parses correctly!")
    with open(INPUT, 'w', encoding='utf-8') as f:
        f.write(fixed)
    print(f"Written to {INPUT}")
except SyntaxError as e:
    print(f"FAILED: SyntaxError at line {e.lineno}: {e.msg}")
    if e.lineno:
        ctx_start = max(0, e.lineno - 8)
        ctx_end = min(len(result_lines), e.lineno + 5)
        for j in range(ctx_start, ctx_end):
            marker = ">>>" if j + 1 == e.lineno else "   "
            print(f"{marker} {j+1:4d}: {repr(result_lines[j][:80])}")
    with open(INPUT + '.fixed_attempt', 'w', encoding='utf-8') as f:
        f.write(fixed)
    print(f"Attempt saved to {INPUT}.fixed_attempt for inspection")
