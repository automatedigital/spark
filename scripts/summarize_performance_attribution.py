"""Summarize retained P09 attempts without changing any capture or old report.

Run AFTER measurements end. Inputs are prefix-matched attempt directories;
output must not already exist. Heap groups are shallow post-GC node sizes,
not dominator/retaining-path attribution.
"""
import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def stats(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    ordered = sorted(values)
    return {"n": len(values), "raw": values,
            "median": statistics.median(values) if values else None,
            "p95NearestRank": ordered[math.ceil(len(values) * .95) - 1] if values else None}


def stream_summary(stream):
    phases = stream["phases"]
    manual = [e for e in phases if e["phase"] == "flush" and e.get("buffer")]
    spans = []
    for flush in manual:
        preceding = [e for e in phases if e["at"] <= flush["at"]]
        schedule = next((e for e in reversed(preceding) if e["phase"] == "flush:scheduled"), None)
        timer = next((e for e in reversed(preceding) if e["phase"] == "flush:timer"), None)
        layout = next((e for e in phases if e["phase"] == "react:layout" and e["at"] >= flush["at"]), None)
        if schedule and timer and schedule["at"] <= timer["at"]:
            spans.append({"scheduledAt": schedule["at"], "timerAt": timer["at"], "flushAt": flush["at"],
                          "requestedDelay": schedule["delay"],
                          "timerMs": timer["at"] - schedule["at"],
                          "rafWaitMs": flush["at"] - timer["at"],
                          "flushToLayoutMs": layout["at"] - flush["at"] if layout else None,
                          "buffer": flush["buffer"]})
    samples = stream["samples"]
    largest = None
    if len(samples) > 1:
        before, after = max(zip(samples, samples[1:], strict=False), key=lambda pair: pair[1]["at"] - pair[0]["at"])
        span = next((s for s in reversed(spans)
                     if s["flushAt"] <= after["at"] and f"token {after['visibleTokens']}." in s["buffer"]), None)
        largest = {"gapMs": after["at"] - before["at"], "before": before, "after": after}
        if span:
            largest["decomposition"] = {
                "previousDOMToScheduleMs": span["scheduledAt"] - before["at"],
                "timerMs": span["timerMs"], "rafWaitMs": span["rafWaitMs"],
                "flushToDOMMs": after["at"] - span["flushAt"],
            }
    return {"initialDelay": stream.get("initialDelay", 60),
            **{key: stream[key] for key in ("startedAt", "samples", "firstVisibleTokenMs", "maxVisibleUpdateGapMs", "updateCount", "finalVisibleTokenCount")},
            "phaseCounts": {p: sum(e["phase"] == p for e in phases) for p in sorted({e["phase"] for e in phases})},
            "flushSpans": spans, "largestGap": largest,
            "observedFinalToken": stream["finalVisibleTokenCount"] == 16,
            "multipleVisibleUpdates": len(samples) > 1}


def heap_summary(samples):
    warm = [s for s in samples if s["cycle"] >= 2]
    xs = [s["cycle"] for s in warm]
    ys = [s["JSHeapUsedSize"] / 2**20 for s in warm]
    x_mean, y_mean = statistics.mean(xs), statistics.mean(ys)
    slope = sum((x-x_mean)*(y-y_mean) for x, y in zip(xs, ys, strict=True)) / sum((x-x_mean)**2 for x in xs)
    return {"samples": samples, "warmCycleStart": 2, "olsMiBPerCycle": slope,
            "warmStartMiB": ys[0], "endMiB": ys[-1], "warmDeltaMiB": ys[-1]-ys[0],
            "rSquared": 1 - sum((y-y_mean-slope*(x-x_mean))**2 for x, y in zip(xs, ys, strict=True)) / sum((y-y_mean)**2 for y in ys)}


def heap_groups(file):
    snapshot = json.loads(file.read_text())
    meta = snapshot["snapshot"]["meta"]
    fields, types = meta["node_fields"], meta["node_types"][0]
    width = len(fields)
    ti, ni, si = (fields.index(x) for x in ("type", "name", "self_size"))
    groups = defaultdict(lambda: [0, 0])
    nodes, strings = snapshot["nodes"], snapshot["strings"]
    for offset in range(0, len(nodes), width):
        key = (types[nodes[offset+ti]], strings[nodes[offset+ni]])
        groups[key][0] += 1
        groups[key][1] += nodes[offset+si]
    return groups


def heap_difference(root):
    start = heap_groups(root / "heap-cycle-2.heapsnapshot")
    end = heap_groups(root / "heap-cycle-12.heapsnapshot")
    diff = [{"type": key[0], "name": key[1], "countDelta": end[key][0]-start[key][0],
             "shallowBytesDelta": end[key][1]-start[key][1]}
            for key in start.keys() | end.keys()]
    return {"label": "Post-GC live-node shallow size/count delta; NOT dominator retained bytes or owner proof",
            "largestPositiveGroups": sorted(diff, key=lambda g: g["shallowBytesDelta"], reverse=True)[:30],
            "largestNegativeGroups": sorted(diff, key=lambda g: g["shallowBytesDelta"])[:10]}


def requests(root):
    log = next(iter(root.glob("run-01/backend.log")), root / "backend.log")
    return [json.loads(line.removeprefix("ATTR_REQUEST ")) for line in log.read_text().splitlines()
            if line.startswith("ATTR_REQUEST ")]


def summarize(root):
    attempt = json.loads((root / "attempt.json").read_text())
    result = {"directory": str(root), "attempt": attempt,
              "preparation": json.loads((root / "preparation.json").read_text())}
    if attempt["probe"] == "thread":
        file = next(iter(root.glob("run-01/baseline-*.json")), root / "run-01/failure.json")
        report = json.loads(file.read_text())
        result["failure"] = report.get("error")
        if not report.get("cases"):
            result["captureIncomplete"] = True
            return result
        case = report["cases"][0]
        result["errors"] = case["errors"]
        result["history"] = {k: case["history"][k] for k in ("pagesLoaded", "fullyLoaded", "requestCount")}
        result["anchor"] = case["scrollDrift"]
        result["streams"] = [stream_summary(s) for s in [case["stream"], *case["streamTrials"]]]
        result["maximumGapMs"] = stats(s["maxVisibleUpdateGapMs"] for s in result["streams"])
        result["heap"] = heap_summary(case["heap"]) if case["heap"] else None
        if result["heap"]:
            result["heap"]["snapshotDifference"] = heap_difference(root)
    else:
        report = json.loads((root / "sidebar.json").read_text())
        result["failure"] = report.get("failure")
        result["errors"] = report["errors"]
        result["browserElapsedMs"] = stats(s["elapsed"] for s in report["searchTrials"])
        result["browserFetchToHeadersMs"] = stats(
            next(p["at"] for p in s["phases"] if p["phase"] == "search:headers")
            - next(p["at"] for p in s["phases"] if p["phase"] == "search:fetch") for s in report["searchTrials"])
        result["directHTTPMs"] = stats(report["directSearchTrials"])
        searches = [r for r in requests(root) if r["path"] == "/api/sessions/search"]
        result["serverSearchRequests"] = searches
        result["serverPhasesMs"] = {}
        for direct in (False, True):
            subset = [r for r in searches if ("attr_direct=" in r["query"]) == direct]
            result["serverPhasesMs"]["direct" if direct else "browser"] = {
                "asgiToHeaders": stats((r["headersNs"]-r["startNs"])/1e6 for r in subset),
                **{phase: stats((s["endNs"]-s["startNs"])/1e6 for r in subset for s in r["spans"] if s["phase"] == phase)
                   for phase in ("__init__", "_init_schema", "search_messages", "close")}}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    prefix, output = Path(args.prefix), Path(args.output)
    assert not output.exists(), "Never overwrite evidence"
    roots = sorted(p for p in prefix.parent.glob(prefix.name + "-*") if (p / "attempt.json").exists())
    attempts = [summarize(root) for root in roots]
    artifacts = []
    for root in roots:
        for file in sorted(root.rglob("*")):
            if file.is_file():
                artifacts.append({"path": str(file), "bytes": file.stat().st_size,
                                  "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    output.write_text(json.dumps({"schema": "spark.app-upgrade.performance-attribution.v1",
                                  "attempts": attempts, "artifacts": artifacts}, indent=2) + "\n")
    print(f"Summarized {len(attempts)} attempts and {len(artifacts)} artifact hashes: {output}")


if __name__ == "__main__":
    main()
