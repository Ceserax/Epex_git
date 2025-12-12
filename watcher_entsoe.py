import time
import pandas as pd
from entsoe import EntsoePandasClient

TZ = "Europe/Amsterdam"

def _expected_hours(start, end):
    return len(pd.date_range(start, end, freq="H", inclusive="left", tz=TZ))

def _fetch(client, eic, start, end):
    s = client.query_day_ahead_prices(eic, start=start, end=end)
    if s is None or len(s) == 0:
        return None
    if getattr(s.index, "tz", None) is None:
        s.index = s.index.tz_localize("UTC")
    return s.tz_convert(TZ).sort_index()

def wait_for_day_ahead(api_key: str, zones: dict, target_date: pd.Timestamp,
                       poll_seconds: int = 60, timeout_minutes: int = 90):
    client = EntsoePandasClient(api_key=api_key)

    start = pd.Timestamp(target_date.date(), tz=TZ)
    end = start + pd.Timedelta(days=1)
    exp = _expected_hours(start, end)

    deadline = time.time() + timeout_minutes * 60
    last = None

    while time.time() < deadline:
        out = {}
        ok = True

        for code, eic in zones.items():
            try:
                s = _fetch(client, eic, start, end)
            except Exception:
                s = None
            out[code] = s
            if s is None or len(s.dropna()) < exp:
                ok = False

        status = {k: (None if v is None else int(v.dropna().shape[0])) for k, v in out.items()}
        if status != last:
            print(f"[watcher] completeness expected {exp}: {status}")
            last = status

        if ok:
            print("[watcher] Day-ahead complete.")
            return out

        time.sleep(poll_seconds)

    raise TimeoutError("Day-ahead not complete within timeout.")