import sys, json
d = json.load(sys.stdin)
print("last_step:", d.get("last_step"), "| error:", d.get("error"))
print("parsed_count:", d.get("parsed_count"), "| enriched:", d.get("enriched"))
# Show detail for rows that are real PMs (have asset or procedure)
shown = 0
for r in (d.get("sample_parsed") or []):
    det = (r.get("raw") or {}).get("detail") or {}
    print("\nWO:", r.get("wo_number"), "| closed_by:", r.get("closed_by"), "| close_date:", r.get("close_date"))
    print("  detail.final_url:", det.get("final_url"))
    print("  detail.raw_len:", det.get("raw_len"))
    print("  detail.raw_head:", (det.get("raw_head") or "")[:700])
    shown += 1
    if shown >= 3:
        break
