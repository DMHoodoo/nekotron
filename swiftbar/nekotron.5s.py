#!/usr/bin/env python3
"""Nekotron menu bar extra (SwiftBar plugin, 5s refresh).

Menu bar: ᓚᘏᗢ + the number that matters (attention in red, else working).
Dropdown: every session with state dot, title, ctx/cost — click to jump.
"""
import glob
import json
import os
import subprocess

KITTEN = "/Applications/kitty.app/Contents/MacOS/kitten"
if not os.path.exists(KITTEN):
    KITTEN = "/opt/homebrew/bin/kitten"
DIR = "/tmp/claude-kitty-status"
JUMP = os.path.expanduser("~/bin/fleet-jump")

C = {"working": "#4f8ef7", "done": "#4cc38a", "attention": "#f0803c", "neutral": "#6b7394"}
DOT = {"working": "●", "done": "●", "attention": "●", "neutral": "○"}


def live_sock():
    for s in sorted(glob.glob("/tmp/kitty-ctl-*"), key=os.path.getmtime, reverse=True):
        try:
            os.kill(int(s.rsplit("-", 1)[-1]), 0)
            return s
        except (ValueError, ProcessLookupError):
            continue
        except PermissionError:
            return s
    return None


def sessions():
    sock = live_sock()
    if not sock:
        return None, []
    kpid = sock.rsplit("-", 1)[-1]
    try:
        ls = json.loads(subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "ls"],
                                       capture_output=True, text=True, timeout=4).stdout)
    except Exception:
        return sock, []
    out = []
    for osw in ls:
        for tab in osw.get("tabs", []):
            wins = [w for w in tab.get("windows", [])
                    if not (w.get("title") or "").startswith("imgrail-")]
            if not wins:
                continue
            w = wins[0]
            wid = w.get("id")

            def rd(prefix=""):
                try:
                    return open(f"{DIR}/{prefix}{kpid}-{wid}").read().strip()
                except OSError:
                    return ""
            state = rd() or "neutral"
            if state not in C:
                state = "neutral"
            ctx = rd("ctx-")
            cost = rd("usage-")
            title = (tab.get("title") or "").strip() or f"window {wid}"
            out.append({"wid": wid, "title": title[:48], "state": state,
                        "ctx": ctx, "cost": cost})
    return sock, out


def main():
    sock, ses = sessions()
    att = [s for s in ses if s["state"] == "attention"]
    work = [s for s in ses if s["state"] == "working"]
    done = [s for s in ses if s["state"] == "done"]

    if sock is None:
        print("ᓚᘏᗢ 𝘻 | color=#6b7394 size=13")
    elif att:
        print(f"ᓚᘏᗢ ●{len(att)} | color=#f0803c size=13")
    elif work:
        print(f"ᓚᘏᗢ ●{len(work)} | color=#4f8ef7 size=13")
    else:
        print(f"ᓚᘏᗢ ✓ | color=#4cc38a size=13")

    print("---")
    if sock is None:
        print("kitty is not running | color=#6b7394")
        return
    hdr = []
    if att:
        hdr.append(f"NEEDS YOU · {len(att)}")
    if work:
        hdr.append(f"WORKING · {len(work)}")
    if done:
        hdr.append(f"DONE · {len(done)}")
    print((" — ".join(hdr) or "ALL QUIET") + " | size=11 color=#8a93b8")
    print("---")
    for s in ses:
        bits = ""
        if s["ctx"]:
            bits += f"  {s['ctx']}%"
        if s["cost"]:
            try:
                bits += f"  ${float(s['cost']):,.0f}"
            except ValueError:
                pass
        print(f"{DOT[s['state']]} {s['title']}{bits} | color={C[s['state']]} "
              f"bash={JUMP} param1={s['wid']} terminal=false refresh=true")
    print("---")
    print(f"Open Fleet Board | bash={JUMP} param1=board terminal=false")
    print(f"New Claude Tab | bash={JUMP} param1=new terminal=false")


main()
