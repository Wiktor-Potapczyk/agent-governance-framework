"""Weekly usage summary — resets Friday 8PM local time."""

from datetime import datetime, timedelta
from claude_monitor.data.reader import load_usage_entries
from claude_monitor.core.models import CostMode
import sys


def get_hours_since_last_friday_8pm():
    """Calculate hours since last Friday 8:00 PM local time."""
    now = datetime.now()
    # Find last Friday 8PM
    days_since_friday = (now.weekday() - 4) % 7  # Friday = 4
    last_friday = now.replace(hour=20, minute=0, second=0, microsecond=0) - timedelta(days=days_since_friday)
    # If we're before 8PM on Friday, go back another week
    if last_friday > now:
        last_friday -= timedelta(days=7)
    diff = now - last_friday
    return int(diff.total_seconds() / 3600)


def main():
    hours = get_hours_since_last_friday_8pm()
    entries, _ = load_usage_entries(hours_back=hours, mode=CostMode.AUTO)

    total_input = sum(e.input_tokens for e in entries)
    total_output = sum(e.output_tokens for e in entries)
    total_cache_read = sum(e.cache_read_tokens for e in entries)
    total_cache_create = sum(e.cache_creation_tokens for e in entries)
    total_cost = sum(e.cost_usd for e in entries if e.cost_usd)
    total_messages = len(entries)

    # Group by model
    models = {}
    for e in entries:
        m = e.model or "unknown"
        if m not in models:
            models[m] = {"input": 0, "output": 0, "cost": 0.0, "count": 0}
        models[m]["input"] += e.input_tokens
        models[m]["output"] += e.output_tokens
        models[m]["cost"] += e.cost_usd or 0
        models[m]["count"] += 1

    # Group by day
    days = {}
    for e in entries:
        day = e.timestamp.strftime("%Y-%m-%d (%a)")
        if day not in days:
            days[day] = {"tokens": 0, "cost": 0.0, "count": 0}
        days[day]["tokens"] += e.input_tokens + e.output_tokens
        days[day]["cost"] += e.cost_usd or 0
        days[day]["count"] += 1

    print(f"\n{'='*60}")
    print(f"  WEEKLY USAGE (since Friday 8PM, {hours}h ago)")
    print(f"{'='*60}")
    print(f"  Messages:     {total_messages:,}")
    print(f"  Input tokens: {total_input:,}")
    print(f"  Output tokens:{total_output:,}")
    print(f"  Cache read:   {total_cache_read:,}")
    print(f"  Cache create: {total_cache_create:,}")
    print(f"  Total tokens: {total_input + total_output:,}")
    print(f"  Est. cost:    ${total_cost:,.2f}")
    print(f"\n  BY MODEL:")
    for m, d in sorted(models.items(), key=lambda x: -x[1]["cost"]):
        print(f"    {m}: {d['count']} msgs, {d['input']+d['output']:,} tokens, ${d['cost']:.2f}")
    print(f"\n  BY DAY:")
    for day, d in sorted(days.items()):
        print(f"    {day}: {d['count']} msgs, {d['tokens']:,} tokens, ${d['cost']:.2f}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
